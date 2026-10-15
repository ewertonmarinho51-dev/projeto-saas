//! Explicit, document-scoped browser entry point; no file picker/download side channels.
use std::any::Any;

use govconnect_wordcraft::{self as adapter, ExportFormat, UserEdit};
use wasm_bindgen::prelude::*;
use wordcraft_engine::Session;
use wordcraft_ui_egui::{Services, WordApp};

struct EditorApp {
    app: WordApp,
}

impl eframe::App for EditorApp {
    fn logic(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.app.logic(ctx);
    }
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        self.app.ui(ui);
    }
    fn as_any_mut(&mut self) -> Option<&mut dyn Any> {
        Some(self)
    }
    fn raw_input_hook(&mut self, _ctx: &egui::Context, input: &mut egui::RawInput) {
        // Documents/assets enter only through the explicitly authorized host API.
        input.dropped_files.clear();
        input.hovered_files.clear();
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
    started: bool,
}

impl Default for GovConnectEditor {
    fn default() -> Self {
        Self { runner: eframe::WebRunner::new(), context: None, pending: None, started: false }
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
        let mut options = eframe::WebOptions::default();
        if webgl && let eframe::egui_wgpu::WgpuSetup::CreateNew(create) = &mut options.wgpu_options.wgpu_setup {
            create.instance_descriptor.backends = eframe::wgpu::Backends::GL;
        }
        let captured = std::rc::Rc::new(std::cell::RefCell::new(None));
        let captured_in = captured.clone();
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
                    Ok(Box::new(EditorApp { app }))
                }),
            )
            .await?;
        self.context = captured.borrow().clone();
        self.started = true;
        Ok(())
    }

    /// Reload only a clean document. A dirty/conflicted draft needs explicit reconciliation first.
    pub fn load_bytes(&mut self, bytes: Vec<u8>) -> Result<(), JsValue> {
        if self.pending.is_some() {
            return Err(error("checkpoint pending; reconcile before reload"));
        }
        self.with_session(|session| {
            if session.dirty {
                return Err("unsaved local edits; reconcile before reload".into());
            }
            adapter::load_into(session, &bytes)?;
            adapter::restrict_embedded_session(session);
            Ok(())
        })
    }

    pub fn serialize(&self) -> Result<Vec<u8>, JsValue> {
        self.with_session(|session| adapter::serialize(&session.doc))
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
        self.with_session(|session| adapter::command(session, UserEdit::InsertText(text)).map(|_| ()))
    }

    pub fn select_text(&self, text: String) -> Result<(), JsValue> {
        self.with_session(|session| adapter::command(session, UserEdit::SelectText(text)).map(|_| ()))
    }

    pub fn bold(&self) -> Result<(), JsValue> {
        self.with_session(|session| adapter::command(session, UserEdit::Bold).map(|_| ()))
    }

    pub fn undo(&self) -> Result<(), JsValue> {
        self.with_session(|session| adapter::command(session, UserEdit::Undo).map(|_| ()))
    }

    pub fn redo(&self) -> Result<(), JsValue> {
        self.with_session(|session| adapter::command(session, UserEdit::Redo).map(|_| ()))
    }

    pub fn export_docx(&self) -> Result<Vec<u8>, JsValue> {
        self.with_session(|session| adapter::export(session, ExportFormat::Docx))
    }

    pub fn export_pdf(&self) -> Result<Vec<u8>, JsValue> {
        self.with_session(|session| adapter::export(session, ExportFormat::Pdf))
    }

    pub fn dispose(&mut self) {
        self.runner.destroy();
        self.context = None;
        self.pending = None;
        self.started = false;
    }
}
