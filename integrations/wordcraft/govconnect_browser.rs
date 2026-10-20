//! Explicit, document-scoped browser entry point; no file picker/download side channels.
use std::any::Any;
use std::cell::Cell;
use std::rc::Rc;

use govconnect_wordcraft::{self as adapter, ExportFormat, UserEdit};
use wasm_bindgen::prelude::*;
use wordcraft_engine::Session;
use wordcraft_ui_egui::{Services, WordApp};

#[derive(Clone, Copy, PartialEq, Eq)]
enum InteractionLock {
    Open,
    Requested,
    Draining,
    Locked,
}

struct EditorApp {
    app: WordApp,
    interaction_lock: Rc<Cell<InteractionLock>>,
    input_ready: Rc<Cell<bool>>,
    ui_passes: u8,
    responsive_initialized: bool,
}

impl eframe::App for EditorApp {
    fn logic(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.app.logic(ctx);
    }
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        if !self.responsive_initialized {
            let compact = ui.available_width() < 600.0;
            if compact {
                // The desktop ribbon and a 100%-zoom A4 page are wider than a
                // phone viewport. Start the embedded editor in WordCraft's own
                // collapsed-ribbon and Page Width modes; both remain available
                // for the user to change afterwards.
                self.app.ui.ribbon_collapsed = true;
                self.app.ui.interface_size =
                    wordcraft_ui_egui::theme::InterfaceSize::from_percent(75.0).expect("the compact interface scale is in range");
                self.app.session.view.fit = "pageWidth".into();
                self.app.session.view.single_column = true;
            }
            self.responsive_initialized = true;
            ui.ctx().request_repaint();
        }
        self.app.ui(ui);
        // WordApp returns early during its first two font-initialization UI passes.
        self.ui_passes = self.ui_passes.saturating_add(1).min(3);
        self.input_ready.set(self.ui_passes == 3);
        if self.interaction_lock.get() == InteractionLock::Draining {
            // raw_input_hook runs BEFORE WordApp's text/IME commands. Only the
            // completed UI pass can attest that captured input reached Session.
            let released = ui.input(|input| !input.pointer.any_down() && input.keys_down.is_empty());
            if released && self.app.canvas.ime_preedit.is_empty() {
                self.interaction_lock.set(InteractionLock::Locked);
            } else {
                // Preserve an active composition/gesture, including its eventual commit/release.
                ui.ctx().request_repaint();
            }
        }
    }
    fn as_any_mut(&mut self) -> Option<&mut dyn Any> {
        Some(self)
    }
    fn raw_input_hook(&mut self, _ctx: &egui::Context, input: &mut egui::RawInput) {
        // Documents/assets enter only through the explicitly authorized host API.
        input.dropped_files.clear();
        input.hovered_files.clear();
        if self.interaction_lock.get() == InteractionLock::Locked {
            // egui 0.36 carries modifier state on individual input events;
            // clearing the queue removes keys, modifiers, text and IME commits.
            input.events.clear();
            input.focused = false;
            return;
        }
        if self.interaction_lock.get() == InteractionLock::Requested {
            self.interaction_lock.set(InteractionLock::Draining);
        }
        // Requested/draining must forward existing input. Hidden tabs have no
        // UI pass; eframe retains their RawInput and readiness remains false.
        self.app.raw_input_hook(input);
    }
}

struct Pending {
    id: String,
    bytes: Vec<u8>,
}

/// Each instance belongs to one authorized document. Dispose on document/tenant/logout change.
/// There are no tokens, database credentials, provider keys or network calls in this API.
#[wasm_bindgen]
pub struct GovConnectEditor {
    runner: eframe::WebRunner,
    context: Option<egui::Context>,
    pending: Option<Pending>,
    persisted_hash: String,
    started: bool,
    interaction_lock: Rc<Cell<InteractionLock>>,
    input_ready: Rc<Cell<bool>>,
}

impl Default for GovConnectEditor {
    fn default() -> Self {
        Self {
            runner: eframe::WebRunner::new(),
            context: None,
            pending: None,
            persisted_hash: String::new(),
            started: false,
            interaction_lock: Rc::new(Cell::new(InteractionLock::Open)),
            input_ready: Rc::new(Cell::new(false)),
        }
    }
}

fn error(message: impl AsRef<str>) -> JsValue {
    JsValue::from_str(message.as_ref())
}

/// Pure model validation, also callable by a pinned server-side WASM runner.
/// Success grants no ACL, persistence, approval or trust to browser-side claims.
#[wasm_bindgen]
pub fn validate_checkpoint(bytes: Vec<u8>) -> Result<(), JsValue> {
    adapter::load_bytes(&bytes).map(|_| ()).map_err(error)
}

/// Pure DOCX import. The server admits the ZIP/OPC package before invoking WASM.
/// Returns the same native checkpoint used by editing, validation and export.
#[wasm_bindgen]
pub fn import_docx(bytes: Vec<u8>) -> Result<Vec<u8>, JsValue> {
    adapter::import_docx(&bytes).map_err(error)
}

/// Pure work-session patch; never loads/replaces an existing browser instance.
/// Authorization, anchor resolution, approval and CAS belong to the server.
#[wasm_bindgen]
pub fn apply_patch(bytes: Vec<u8>, current_revision: u32, plan_json: &str) -> Result<Vec<u8>, JsValue> {
    adapter::apply_patch(&bytes, current_revision, plan_json.as_bytes()).map_err(error)
}

/// Server-side export of the exact validated revision; no canvas or download side channel.
#[wasm_bindgen]
pub fn export_checkpoint(bytes: Vec<u8>, format: &str) -> Result<Vec<u8>, JsValue> {
    let format = match format {
        "docx" => ExportFormat::Docx,
        "pdf" => ExportFormat::Pdf,
        _ => return Err(error("unsupported export format")),
    };
    let mut session = Session::new(adapter::load_bytes(&bytes).map_err(error)?);
    adapter::restrict_embedded_session(&mut session);
    adapter::export(&session, format).map_err(error)
}

impl GovConnectEditor {
    fn ensure_editable(&self) -> Result<(), JsValue> {
        if self.interaction_lock.get() != InteractionLock::Open {
            return Err(error("canvas is locked for a server-bound operation"));
        }
        Ok(())
    }

    fn with_session<T>(&self, action: impl FnOnce(&mut Session) -> Result<T, String>) -> Result<T, JsValue> {
        if !self.started {
            return Err(error("editor is not ready"));
        }
        // EditorApp implements as_any_mut, so WebRunner's concrete-app downcast is valid.
        let mut app = self.runner.app_mut::<EditorApp>().ok_or_else(|| error("editor unavailable"))?;
        let result = action(&mut app.app.session).map_err(error);
        if let Some(ctx) = &self.context {
            ctx.request_repaint();
        }
        result
    }
}

#[wasm_bindgen]
impl GovConnectEditor {
    #[wasm_bindgen(constructor)]
    pub fn new() -> Self {
        Self::default()
    }

    /// Start once with an authorized checkpoint; caller provides the actual canvas (shadow DOM safe).
    pub async fn start(&mut self, canvas: web_sys::HtmlCanvasElement, bytes: Vec<u8>, webgl: bool) -> Result<(), JsValue> {
        if self.started {
            return Err(error("editor already started"));
        }
        let doc = adapter::load_bytes(&bytes).map_err(error)?;
        let persisted_hash = adapter::checkpoint_sha256(&bytes);
        let mut options = eframe::WebOptions::default();
        if webgl && let eframe::egui_wgpu::WgpuSetup::CreateNew(create) = &mut options.wgpu_options.wgpu_setup {
            create.instance_descriptor.backends = eframe::wgpu::Backends::GL;
        }
        let captured = std::rc::Rc::new(std::cell::RefCell::new(None));
        let captured_in = captured.clone();
        let interaction_lock = self.interaction_lock.clone();
        let input_ready = self.input_ready.clone();
        self.runner
            .start(
                canvas,
                options,
                Box::new(move |cc| {
                    captured_in.replace(Some(cc.egui_ctx.clone()));
                    let mut session = Session::new(doc);
                    adapter::restrict_embedded_session(&mut session);
                    let mut app = WordApp::new(session, Services::default());
                    app.autosave = false;
                    app.ui.show_discord = false;
                    app.ui.language = "pt-br".into();
                    Ok(Box::new(EditorApp { app, interaction_lock, input_ready, ui_passes: 0, responsive_initialized: false }))
                }),
            )
            .await?;
        self.context = captured.borrow().clone();
        self.persisted_hash = persisted_hash;
        self.started = true;
        Ok(())
    }

    /// Reload only a clean document. A dirty/conflicted draft needs explicit reconciliation first.
    pub fn load_bytes(&mut self, bytes: Vec<u8>) -> Result<(), JsValue> {
        self.ensure_editable()?;
        if self.pending.is_some() {
            return Err(error("checkpoint pending; reconcile before reload"));
        }
        let persisted_hash = adapter::checkpoint_sha256(&bytes);
        self.with_session(|session| {
            if session.dirty {
                return Err("unsaved local edits; reconcile before reload".into());
            }
            adapter::load_into(session, &bytes)?;
            adapter::restrict_embedded_session(session);
            Ok(())
        })?;
        self.persisted_hash = persisted_hash;
        Ok(())
    }

    pub fn serialize(&self) -> Result<Vec<u8>, JsValue> {
        self.with_session(|session| adapter::serialize(&session.doc))
    }

    /// Read-only UI diagnostics for browser QA; no document data or authority is exposed.
    pub fn responsive_profile(&self) -> Result<String, JsValue> {
        if !self.started {
            return Err(error("editor is not ready"));
        }
        let app = self.runner.app_mut::<EditorApp>().ok_or_else(|| error("editor unavailable"))?;
        Ok(serde_json::json!({
            "initialized": app.responsive_initialized,
            "ribbon_collapsed": app.app.ui.ribbon_collapsed,
            "interface_percent": app.app.ui.interface_size.percent(),
            "fit": app.app.session.view.fit.as_str(),
            "single_column": app.app.session.view.single_column,
        })
        .to_string())
    }

    /// Retry returns exactly the bytes of the same request, even when typing continued.
    pub fn checkpoint(&mut self, request_id: String) -> Result<Vec<u8>, JsValue> {
        if request_id.len() != 36 || !request_id.is_ascii() {
            return Err(error("invalid request id"));
        }
        if let Some(pending) = &self.pending {
            if pending.id == request_id {
                return Ok(pending.bytes.clone());
            }
            return Err(error("another checkpoint is still pending"));
        }
        let bytes = self.serialize()?;
        self.pending = Some(Pending { id: request_id, bytes: bytes.clone() });
        Ok(bytes)
    }

    /// Host calls this only after checking the backend's persisted ACK/revision/hash.
    /// This changes browser state only; it grants no backend approval or persistence.
    pub fn acknowledge_checkpoint(&mut self, request_id: String) -> Result<(), JsValue> {
        let pending = self.pending.as_ref().ok_or_else(|| error("no checkpoint pending"))?;
        if pending.id != request_id {
            return Err(error("ACK request mismatch"));
        }
        let saved = pending.bytes.clone();
        self.with_session(|session| {
            session.dirty = adapter::serialize(&session.doc)? != saved;
            Ok(())
        })?;
        self.persisted_hash = adapter::checkpoint_sha256(&saved);
        self.pending = None;
        Ok(())
    }

    pub fn dirty(&self) -> Result<bool, JsValue> {
        self.with_session(|session| Ok(session.dirty))
    }

    /// Local edit generation, used to debounce checkpoints without serializing on each keystroke.
    pub fn generation(&self) -> Result<String, JsValue> {
        self.with_session(|session| Ok(session.rev().to_string()))
    }

    pub fn selection(&self) -> Result<String, JsValue> {
        self.with_session(|session| adapter::selection(session).map(|v| v.to_string()))
    }

    pub fn insert_text(&self, text: String) -> Result<(), JsValue> {
        self.ensure_editable()?;
        self.with_session(|session| adapter::command(session, UserEdit::InsertText(text)).map(|_| ()))
    }

    pub fn select_text(&self, text: String) -> Result<(), JsValue> {
        self.ensure_editable()?;
        self.with_session(|session| adapter::command(session, UserEdit::SelectText(text)).map(|_| ()))
    }

    /// Apply only to a clean, acknowledged canvas. The caller still owns
    /// backend policy/approval/CAS; this method never claims a saved revision.
    pub fn apply_text_patch(&mut self, current_revision: u32, plan_json: &str) -> Result<(), JsValue> {
        self.ensure_editable()?;
        if self.pending.is_some() {
            return Err(error("checkpoint pending; reconcile before patch"));
        }
        let persisted_hash = self.persisted_hash.clone();
        self.with_session(|session| {
            if session.dirty {
                return Err("unsaved local edits; reconcile before patch".into());
            }
            adapter::apply_session_patch(session, current_revision, &persisted_hash, plan_json.as_bytes())
        })
    }

    pub fn bold(&self) -> Result<(), JsValue> {
        self.ensure_editable()?;
        self.with_session(|session| adapter::command(session, UserEdit::Bold).map(|_| ()))
    }

    pub fn undo(&self) -> Result<(), JsValue> {
        self.ensure_editable()?;
        self.with_session(|session| adapter::command(session, UserEdit::Undo).map(|_| ()))
    }

    pub fn redo(&self) -> Result<(), JsValue> {
        self.ensure_editable()?;
        self.with_session(|session| adapter::command(session, UserEdit::Redo).map(|_| ()))
    }

    pub fn export_docx(&self) -> Result<Vec<u8>, JsValue> {
        self.with_session(|session| adapter::export(session, ExportFormat::Docx))
    }

    pub fn export_pdf(&self) -> Result<Vec<u8>, JsValue> {
        self.with_session(|session| adapter::export(session, ExportFormat::Pdf))
    }

    /// Host coordination only; preserves the document, selection and undo stack.
    /// It is not an ACL, an approval or a server persistence confirmation.
    pub fn set_interaction_locked(&self, locked: bool) -> Result<(), JsValue> {
        if !self.started {
            return Err(error("editor is not ready"));
        }
        if locked {
            if !self.input_ready.get() {
                return Err(error("canvas input is not initialized"));
            }
            if self.interaction_lock.get() == InteractionLock::Open {
                self.interaction_lock.set(InteractionLock::Requested);
            }
        } else {
            self.interaction_lock.set(InteractionLock::Open);
        }
        if let Some(ctx) = &self.context {
            ctx.request_repaint();
        }
        Ok(())
    }

    /// True only AFTER captured RawInput traversed a complete WordApp UI pass.
    /// A requested lock already rejects external editing APIs, but is not a proof.
    pub fn interaction_lock_ready(&self) -> Result<bool, JsValue> {
        if !self.started {
            return Err(error("editor is not ready"));
        }
        Ok(self.interaction_lock.get() == InteractionLock::Locked)
    }

    pub fn dispose(&mut self) {
        self.runner.destroy();
        self.context = None;
        self.pending = None;
        self.started = false;
        self.interaction_lock.set(InteractionLock::Open);
        self.input_ready.set(false);
    }
}
