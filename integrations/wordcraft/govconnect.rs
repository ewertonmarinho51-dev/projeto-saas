//! GovConnect's narrow adapter over the actual WordCraft model/session.
//! No authentication, persistence, network, file paths or LLM commands here.
//! The native snapshot retains the fields skipped by Document's plain JSON.
#![deny(clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::unimplemented, clippy::todo, clippy::unreachable)]

use std::collections::BTreeMap;
use std::io::{self, Write};
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use wordcraft_doc::{Block, Document, InlineObject, Paragraph, Path, Pos, StoryRef};
use wordcraft_engine::{CmdError, CommandSpec, Session};

pub const SCHEMA: &str = "gc-wordcraft-snapshot/v1";
pub const MAX_BYTES: usize = 8 * 1024 * 1024;
const MAX_DEPTH: usize = 32;
const PATCH_SCHEMA: &str = "gc-wordcraft-native-patch/v1";
const PATCH_COMMAND: &str = "govconnect.apply_patch";
const MAX_PATCH_BYTES: usize = 1024 * 1024;
const MAX_PATCH_OPERATIONS: usize = 32;
const MAX_PATCH_TEXT: usize = 100 * 1024;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct NativePatchPlan {
    schema: String,
    source_hash: String,
    source_revision: u32,
    operations: Vec<NativeReplacement>,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct NativeReplacement {
    op: String,
    story: StoryRef,
    path: Path,
    start_byte: usize,
    end_byte: usize,
    old_text: String,
    new_text: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct NativePatchRequest {
    current_revision: u32,
    observed_source_hash: String,
    plan: NativePatchPlan,
}

fn patch_error() -> String {
    "native patch refused".into()
}

fn sha256(bytes: &[u8]) -> String {
    Sha256::digest(bytes).iter().map(|byte| format!("{byte:02x}")).collect()
}

fn inline_patch_text(text: &str) -> bool {
    !text.chars().any(|c| c.is_control() || matches!(c, '\u{2028}' | '\u{2029}' | '\u{FFFC}'))
}

fn uniform_patch_paragraph(para: &Paragraph) -> bool {
    let Some(first) = para.runs.first() else { return false };
    if !para.objects.is_empty()
        || para.text.contains('\u{FFFC}')
        || first.props.ins.is_some()
        || first.props.del.is_some()
        || first.props.fmt_change.is_some()
    {
        return false;
    }
    let mut end = 0_usize;
    for run in &para.runs {
        let Some(next) = end.checked_add(run.len) else { return false };
        if run.len == 0 || run.props != first.props || !para.text.is_char_boundary(next) {
            return false;
        }
        end = next;
    }
    end == para.text.len()
}

/// Validate against the source, then order edits backwards. No positional guesses.
fn patch_operations(doc: &Document, request: &NativePatchRequest) -> Result<Vec<NativeReplacement>, String> {
    let plan = &request.plan;
    if plan.schema != PATCH_SCHEMA
        || request.current_revision == 0
        || plan.source_revision != request.current_revision
        || plan.source_hash != request.observed_source_hash
        || plan.source_hash.len() != 64
        || !plan.source_hash.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        || plan.operations.is_empty()
        || plan.operations.len() > MAX_PATCH_OPERATIONS
        || doc.settings.track_changes
        || doc.settings.protection.is_some()
    {
        return Err(patch_error());
    }
    let mut text_bytes = 0_usize;
    for operation in &plan.operations {
        text_bytes = text_bytes.checked_add(operation.new_text.len()).ok_or_else(patch_error)?;
        if operation.op != "replace_text"
            || operation.path.0.is_empty()
            || operation.path.0.len() > 1 + 3 * MAX_DEPTH
            || operation.path.0.len() % 3 != 1
            || operation.start_byte >= operation.end_byte
            || operation.old_text.len() > MAX_PATCH_TEXT
            || text_bytes > MAX_PATCH_TEXT
            || !inline_patch_text(&operation.old_text)
            || !inline_patch_text(&operation.new_text)
        {
            return Err(patch_error());
        }
        let para = doc.para(operation.story, &operation.path).ok_or_else(patch_error)?;
        if !uniform_patch_paragraph(para) || para.text.get(operation.start_byte..operation.end_byte) != Some(operation.old_text.as_str()) {
            return Err(patch_error());
        }
    }
    let mut operations = plan.operations.clone();
    operations.sort_by(|a, b| (&a.story, &a.path, a.start_byte).cmp(&(&b.story, &b.path, b.start_byte)));
    for pair in operations.windows(2) {
        let [first, next] = pair else { return Err(patch_error()) };
        if first.story == next.story && first.path == next.path && next.start_byte < first.end_byte {
            return Err(patch_error());
        }
    }
    operations.reverse();
    Ok(operations)
}

/// Compare the native result, masking only authorized paragraphs in a check copy.
/// This never constructs or applies a document patch by rewriting JSON.
fn verify_native_patch(before: &Document, after: &Document, operations: &[NativeReplacement]) -> Result<(), String> {
    let mut paragraphs = BTreeMap::new();
    let mut expected_text = BTreeMap::new();
    for operation in operations {
        let key = (operation.story, operation.path.clone());
        let original = before.para(operation.story, &operation.path).ok_or_else(patch_error)?;
        paragraphs.entry(key.clone()).or_insert_with(|| original.clone());
        let expected = expected_text.entry(key).or_insert_with(|| original.text.clone());
        if expected.get(operation.start_byte..operation.end_byte) != Some(operation.old_text.as_str()) {
            return Err(patch_error());
        }
        // A text-only postcondition oracle. The real edit goes through Session::run.
        expected.replace_range(operation.start_byte..operation.end_byte, &operation.new_text);
    }
    let mut outside = after.clone();
    for ((story, path), original) in paragraphs {
        let result = after.para(story, &path).ok_or_else(patch_error)?;
        let expected = expected_text.get(&(story, path.clone())).ok_or_else(patch_error)?;
        let style = original.runs.first().ok_or_else(patch_error)?;
        let mut run_bytes = 0_usize;
        for run in &result.runs {
            run_bytes = run_bytes.checked_add(run.len).ok_or_else(patch_error)?;
            if run.props != style.props || !result.text.is_char_boundary(run_bytes) {
                return Err(patch_error());
            }
        }
        if result.text != *expected
            || run_bytes != result.text.len()
            || result.props != original.props
            || result.mark != original.mark
            || result.objects != original.objects
            || result.section != original.section
        {
            return Err(patch_error());
        }
        *outside.para_mut(story, &path).map_err(|_| patch_error())? = original;
    }
    if outside != *before {
        return Err(patch_error());
    }
    let snapshot = serialize(after)?;
    if load_bytes(&snapshot)? != *after {
        return Err(patch_error());
    }
    Ok(())
}

fn native_patch_command(session: &mut Session, value: &Value) -> wordcraft_engine::CmdResult {
    let apply = || -> Result<(Document, wordcraft_engine::Selection), String> {
        let request: NativePatchRequest = serde_json::from_value(value.clone()).map_err(|_| patch_error())?;
        let operations = patch_operations(&session.doc, &request)?;
        let mut copy = Session::new(session.doc.clone());
        restrict_embedded_session(&mut copy);
        copy.author = session.author.clone();
        copy.prefs.typing_replaces_selection = true;
        copy.prefs.overtype = false;
        copy.prefs.autocorrect.enabled = false;
        for operation in &operations {
            let para = session.doc.para(operation.story, &operation.path).ok_or_else(patch_error)?;
            copy.pending = Some(para.runs.first().ok_or_else(patch_error)?.props.clone());
            let anchor = Pos::new(operation.story, operation.path.clone(), operation.start_byte);
            let focus = Pos::new(operation.story, operation.path.clone(), operation.end_byte);
            copy.run("select.range", &json!({"anchor": anchor, "focus": focus})).map_err(|_| patch_error())?;
            if copy.sel.anchor != anchor || copy.sel.focus != focus {
                return Err(patch_error());
            }
            copy.run("text.insert", &json!({"text": operation.new_text, "raw": true})).map_err(|_| patch_error())?;
        }
        verify_native_patch(&session.doc, &copy.doc, &operations)?;
        Ok((copy.doc, copy.sel))
    };
    let (document, selection) = apply().map_err(|_| CmdError::Failed(patch_error()))?;
    session.doc = document;
    session.sel = selection;
    Ok(json!({"applied": true}))
}

/// Internal work-session batch. The public pure API never changes a live editor.
fn apply_native_patch(session: &mut Session, request: NativePatchRequest) -> Result<(), String> {
    let before = session.doc.clone();
    let operations = patch_operations(&before, &request)?;
    let params = serde_json::to_value(&request).map_err(|_| patch_error())?;
    let snapshot = session.edit_snapshot();
    let original_registry = session.registry.clone();
    let mut specs: Vec<_> = original_registry.all().iter().filter(|spec| spec.id != PATCH_COMMAND).cloned().collect();
    specs.push(CommandSpec::new(PATCH_COMMAND, "GovConnect patch", "GovConnect", native_patch_command));
    session.registry = Arc::new(wordcraft_engine::Registry::new(specs));
    let result = session.run(PATCH_COMMAND, &params).map_err(|_| patch_error()).and_then(|_| verify_native_patch(&before, &session.doc, &operations));
    session.registry = original_registry;
    if result.is_err() {
        session.restore(snapshot);
    }
    result
}

/// Apply a closed, server-authorized text plan to a copy using the native engine.
/// ACL/policy/diff approval/CAS remain GovConnect responsibilities. Errors are closed.
pub fn apply_patch(bytes: &[u8], current_revision: u32, plan_json: &[u8]) -> Result<Vec<u8>, String> {
    let apply = || -> Result<Vec<u8>, String> {
        if bytes.is_empty() || bytes.len() > MAX_BYTES || plan_json.is_empty() || plan_json.len() > MAX_PATCH_BYTES {
            return Err(patch_error());
        }
        let plan: NativePatchPlan = serde_json::from_slice(plan_json).map_err(|_| patch_error())?;
        let observed_source_hash = sha256(bytes);
        if plan.source_hash != observed_source_hash {
            return Err(patch_error());
        }
        let mut session = Session::new(load_bytes(bytes)?);
        restrict_embedded_session(&mut session);
        apply_native_patch(&mut session, NativePatchRequest { current_revision, observed_source_hash, plan })?;
        serialize(&session.doc)
    };
    apply().map_err(|_| patch_error())
}

struct BoundedBytes(Vec<u8>);

impl Write for BoundedBytes {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if self.0.len().saturating_add(bytes.len()) > MAX_BYTES {
            return Err(io::Error::other("checkpoint exceeds byte limit"));
        }
        self.0.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn validate_object(object: &InlineObject, depth: usize) -> Result<(), String> {
    if depth > MAX_DEPTH {
        return Err("nested objects exceed snapshot limit".into());
    }
    match object {
        InlineObject::Image { ole: Some(_), .. } => {
            return Err("embedded OLE requires the original DOCX compatibility path".into());
        }
        InlineObject::Graphic { graphic, .. } if graphic.source.is_some() => {
            return Err("opaque graphics require the original DOCX compatibility path".into());
        }
        InlineObject::Group { children, .. } => {
            if children.len() > 1000 {
                return Err("too many grouped objects".into());
            }
            for child in children {
                validate_object(&child.obj, depth + 1)?;
            }
        }
        _ => {}
    }
    Ok(())
}

fn validate_blocks(blocks: &[Arc<Block>], depth: usize) -> Result<(), String> {
    if depth > MAX_DEPTH {
        return Err("nested tables exceed snapshot limit".into());
    }
    for block in blocks {
        match block.as_ref() {
            Block::Para(p) => {
                for object in &p.objects {
                    validate_object(object, 0)?;
                }
            }
            Block::Table(table) => {
                for row in &table.rows {
                    for cell in &row.cells {
                        validate_blocks(&cell.blocks, depth + 1)?;
                    }
                }
            }
        }
    }
    Ok(())
}

fn validate_doc(doc: &Document) -> Result<(), String> {
    validate_blocks(&doc.body, 0)?;
    for part in doc.parts.values() {
        validate_blocks(&part.blocks, 0)?;
    }
    for (assets, passthrough) in [(&doc.media, false), (&doc.passthrough, true)] {
        if assets.len() > 1024 {
            return Err("too many snapshot assets".into());
        }
        for (key, bytes) in assets {
            // These exact keys are bookkeeping, not OPC paths. The pinned
            // docx::package reader creates them for embedded parts/custom XML.
            // Keep them only in passthrough; never allow arbitrary ':' paths.
            let metadata =
                passthrough && matches!(key.as_str(), "wordcraft:embedded.parts" | "wordcraft:customXml.roots" | "wordcraft:vbaProject.related");
            if key.is_empty()
                || key.len() > 240
                || key.contains('\\')
                || (key.contains(':') && !metadata)
                || key.starts_with('/')
                || key.split('/').any(|s| matches!(s, "" | "." | ".."))
                || bytes.len() > MAX_BYTES
            {
                return Err("invalid snapshot asset".into());
            }
        }
    }
    Ok(())
}

/// Encode a bounded, versioned checkpoint. Does not mark the Session saved.
pub fn serialize(doc: &Document) -> Result<Vec<u8>, String> {
    validate_doc(doc)?;
    let mut out = BoundedBytes(Vec::new());
    out.write_all(b"{\"schema\":").map_err(|e| e.to_string())?;
    serde_json::to_writer(&mut out, SCHEMA).map_err(|e| e.to_string())?;
    out.write_all(b",\"document\":").map_err(|e| e.to_string())?;
    serde_json::to_writer(&mut out, doc).map_err(|e| e.to_string())?;
    out.write_all(b",\"media\":").map_err(|e| e.to_string())?;
    serde_json::to_writer(&mut out, &doc.media).map_err(|e| e.to_string())?;
    out.write_all(b",\"passthrough\":").map_err(|e| e.to_string())?;
    serde_json::to_writer(&mut out, &doc.passthrough).map_err(|e| e.to_string())?;
    out.write_all(b"}").map_err(|e| e.to_string())?;
    Ok(out.0)
}

/// Decode entirely before replacing the live document. No silent plain-JSON fallback.
pub fn load_bytes(bytes: &[u8]) -> Result<Document, String> {
    if bytes.is_empty() || bytes.len() > MAX_BYTES {
        return Err("checkpoint size invalid".into());
    }
    let value: Value = serde_json::from_slice(bytes).map_err(|_| "invalid checkpoint JSON".to_string())?;
    let Value::Object(mut root) = value else {
        return Err("checkpoint must be an object".into());
    };
    if root.len() != 4
        || root.get("schema").and_then(Value::as_str) != Some(SCHEMA)
        || !root.contains_key("document")
        || !root.contains_key("media")
        || !root.contains_key("passthrough")
    {
        return Err("checkpoint schema or fields invalid".into());
    }
    let doc_value = root.remove("document").ok_or("missing document")?;
    if !doc_value.get("body").is_some_and(Value::is_array) {
        return Err("missing document body".into());
    }
    let mut doc: Document = serde_json::from_value(doc_value.clone()).map_err(|_| "invalid document model".to_string())?;
    // Serde's permissive model decoder otherwise drops unknown nested fields.
    // Compare JSON values, not bytes: object order is irrelevant to this check.
    // Use the same bounded writer as snapshots. to_value promotes f32 directly
    // to f64 and can spuriously change 0.1 into 0.10000000149011612.
    let mut normalized = BoundedBytes(Vec::new());
    serde_json::to_writer(&mut normalized, &doc).map_err(|_| "model cannot be serialized".to_string())?;
    let normalized_value: Value = serde_json::from_slice(&normalized.0).map_err(|_| "model JSON invalid".to_string())?;
    if normalized_value != doc_value {
        return Err("checkpoint contains unsupported or noncanonical model fields".into());
    }
    for (name, target) in [("media", &mut doc.media), ("passthrough", &mut doc.passthrough)] {
        let value = root.remove(name).ok_or("missing assets")?;
        *target = serde_json::from_value::<BTreeMap<String, Arc<Vec<u8>>>>(value).map_err(|_| "invalid assets".to_string())?;
    }
    validate_doc(&doc)?;
    Ok(doc)
}

/// Replace only after successful decoding; callers must authorize document and revision.
pub fn load_into(session: &mut Session, bytes: &[u8]) -> Result<(), String> {
    let doc = load_bytes(bytes)?;
    session.set_document(doc);
    Ok(())
}

/// DOCX bytes only; the trusted backend must admit ZIP/OPC parts before calling.
/// The fixed internal name selects the existing importer, never a client path.
/// Importing neither replaces a live session nor acknowledges persistence.
pub fn import_docx(bytes: &[u8]) -> Result<Vec<u8>, String> {
    if bytes.is_empty() || bytes.len() > MAX_BYTES || !bytes.starts_with(b"PK\x03\x04") {
        return Err("DOCX byte bound or signature invalid".into());
    }
    let doc = wordcraft_engine::io::open_bytes("document.docx", bytes)?;
    let checkpoint = serialize(&doc)?;
    if load_bytes(&checkpoint)? != doc {
        return Err("imported checkpoint changed the native document".into());
    }
    Ok(checkpoint)
}

/// Selection is context, never an authorization decision. Paths are revision-bound.
pub fn selection(session: &Session) -> Result<Value, String> {
    let positions = serde_json::to_value(&session.sel).map_err(|e| e.to_string())?;
    Ok(json!({"positions": positions, "text": session.selected_text()}))
}

/// Typed direct-user edits only; AI proposals still use GovConnect's canonical applicator.
pub enum UserEdit {
    InsertText(String),
    SelectText(String),
    Bold,
    Undo,
    Redo,
}

/// Remove file/session/environment actions from the embedded ribbon and shortcut registry.
/// The host owns opening, checkpoints and authorized exports. No provider/network automation.
pub fn restrict_embedded_session(session: &mut Session) {
    let specs = session
        .registry
        .all()
        .iter()
        .filter(|spec| !["file.", "font.", "mailings.", "tools.", "zotero."].iter().any(|prefix| spec.id.starts_with(prefix)))
        .cloned()
        .collect();
    session.registry = Arc::new(wordcraft_engine::Registry::new(specs));
    session.autosave = false;
    session.path = None;
    session.user_dict_path = None;
}

pub fn command(session: &mut Session, edit: UserEdit) -> Result<Value, String> {
    let (id, params) = match edit {
        UserEdit::InsertText(text) | UserEdit::SelectText(text) if text.len() > 100_000 => {
            return Err("edit text exceeds limit".into());
        }
        UserEdit::InsertText(text) => ("text.insert", json!({"text": text})),
        UserEdit::SelectText(text) => ("select.text", json!({"text": text})),
        UserEdit::Bold => ("format.bold", json!({})),
        UserEdit::Undo => ("edit.undo", json!({})),
        UserEdit::Redo => ("edit.redo", json!({})),
    };
    session.run(id, &params).map_err(|e| e.to_string())
}

pub enum ExportFormat {
    Docx,
    Pdf,
}

/// Byte export only, no file names/URLs/clipboard/print commands supplied by callers.
pub fn export(session: &Session, format: ExportFormat) -> Result<Vec<u8>, String> {
    let name = match format {
        ExportFormat::Docx => "document.docx",
        ExportFormat::Pdf => "document.pdf",
    };
    wordcraft_engine::io::save_bytes(name, &session.doc)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn example() -> Document {
        let mut doc = Document::from_text("Município — contratação pública\nJustificativa com ação e órgão.");
        doc.media.insert("logo.png".into(), Arc::new(vec![0, 1, 127, 255]));
        doc.passthrough.insert("customXml/item1.xml".into(), Arc::new(b"<source>synthetic</source>".to_vec()));
        doc
    }

    #[test]
    fn checkpoint_preserves_images_and_source_parts() {
        let doc = example();
        let bytes = serialize(&doc).unwrap();
        let back = load_bytes(&bytes).unwrap();
        assert_eq!(back, doc);
        assert_eq!(serialize(&back).unwrap(), bytes);
    }

    #[test]
    fn pinned_docx_bookkeeping_is_preserved_only_in_passthrough() {
        for key in ["wordcraft:embedded.parts", "wordcraft:customXml.roots", "wordcraft:vbaProject.related"] {
            let mut doc = example();
            doc.passthrough.insert(key.into(), Arc::new(b"synthetic metadata".to_vec()));
            let bytes = serialize(&doc).unwrap();
            let back = load_bytes(&bytes).unwrap();
            assert_eq!(back, doc);
            assert_eq!(serialize(&back).unwrap(), bytes);
            doc.media.insert(key.into(), Arc::new(vec![1]));
            assert!(serialize(&doc).is_err(), "metadata is not a media filename");
        }
        for key in ["wordcraft:unknown", "wordcraft:embedded.parts/../outside", "C:/file", "https://example.invalid/file"] {
            let mut doc = example();
            doc.passthrough.insert(key.into(), Arc::new(vec![1]));
            assert!(serialize(&doc).is_err(), "only exact pinned bookkeeping keys may contain a colon");
        }
    }

    #[test]
    fn plain_native_json_is_not_a_checkpoint() {
        let doc = example();
        let plain = wordcraft_engine::io::save_bytes("x.json", &doc).unwrap();
        let lossy = wordcraft_engine::io::open_bytes("x.json", &plain).unwrap();
        assert!(lossy.media.is_empty());
        assert!(load_bytes(&plain).is_err());
    }

    #[test]
    fn failed_load_keeps_live_session_and_undo() {
        let mut s = Session::new(example());
        command(&mut s, UserEdit::InsertText("prefix ".into())).unwrap();
        let before = serialize(&s.doc).unwrap();
        assert!(load_into(&mut s, b"{}").is_err());
        assert_eq!(serialize(&s.doc).unwrap(), before);
        command(&mut s, UserEdit::Undo).unwrap();
        assert_eq!(serialize(&s.doc).unwrap(), serialize(&example()).unwrap());
    }

    #[test]
    fn typed_edit_and_reopen_use_the_same_session_model() {
        let mut s = Session::new(example());
        command(&mut s, UserEdit::SelectText("contratação".into())).unwrap();
        assert_eq!(selection(&s).unwrap()["text"], "contratação");
        command(&mut s, UserEdit::InsertText("aquisição".into())).unwrap();
        assert!(s.dirty);
        let bytes = serialize(&s.doc).unwrap();
        assert!(s.dirty, "serialization is not a backend save ACK");
        let mut reopened = Session::new(Document::new());
        load_into(&mut reopened, &bytes).unwrap();
        assert_eq!(reopened.doc, s.doc);
    }

    #[test]
    fn invalid_schema_extra_fields_and_asset_paths_are_rejected() {
        let bytes = serialize(&example()).unwrap();
        for change in ["schema", "extra", "path"] {
            let mut value: Value = serde_json::from_slice(&bytes).unwrap();
            match change {
                "schema" => value["schema"] = json!("future/v9"),
                "extra" => value["tenant_id"] = json!("not-authority"),
                _ => value["media"]["../outside"] = json!([1, 2]),
            }
            assert!(load_bytes(&serde_json::to_vec(&value).unwrap()).is_err());
        }
    }

    #[test]
    fn unknown_model_fields_cannot_be_silently_discarded() {
        for nested in [false, true] {
            let mut value: Value = serde_json::from_slice(&serialize(&example()).unwrap()).unwrap();
            let target = if nested { &mut value["document"]["body"][0] } else { &mut value["document"] };
            target["unsupported_future_field"] = json!({"text": "must not disappear"});
            let bytes = serde_json::to_vec(&value).unwrap();
            assert!(load_bytes(&bytes).is_err());
            let mut live = Session::new(example());
            let before = serialize(&live.doc).unwrap();
            assert!(load_into(&mut live, &bytes).is_err());
            assert_eq!(serialize(&live.doc).unwrap(), before);
        }
    }

    #[test]
    fn fractional_page_geometry_keeps_the_snapshot_writer_precision() {
        let mut doc = example();
        doc.last_section.page_w = 595.3;
        doc.last_section.page_h = 841.89;
        doc.last_section.margin_left = 42.1;
        let bytes = serialize(&doc).unwrap();
        let loaded = load_bytes(&bytes).unwrap();
        assert_eq!(loaded, doc);
        assert_eq!(serialize(&loaded).unwrap(), bytes);
    }

    #[test]
    fn payload_bounds_are_enforced() {
        assert!(load_bytes(&vec![b' '; MAX_BYTES + 1]).is_err());
        let mut doc = example();
        doc.media.insert("large".into(), Arc::new(vec![255; MAX_BYTES]));
        assert!(serialize(&doc).is_err());
    }

    #[test]
    fn opaque_objects_are_refused_before_data_can_be_lost() {
        let object = InlineObject::Image {
            media: "preview.png".into(),
            w: 10.0,
            h: 10.0,
            alt: String::new(),
            float: Default::default(),
            crop: [0.0; 4],
            ole: Some(Arc::new(wordcraft_doc::graphic::Embedded::default())),
        };
        assert!(validate_object(&object, 0).is_err());
        let group = InlineObject::Group {
            w: 10.0,
            h: 10.0,
            float: Default::default(),
            ch_w: 10.0,
            ch_h: 10.0,
            children: vec![wordcraft_doc::para::GroupChild { x: 0.0, y: 0.0, obj: object }],
            canvas: None,
        };
        assert!(validate_object(&group, 0).is_err());
        let graphic = InlineObject::Graphic {
            w: 10.0,
            h: 10.0,
            alt: String::new(),
            float: Default::default(),
            graphic: Arc::new(wordcraft_doc::graphic::Graphic {
                source: Some(Arc::new(wordcraft_doc::graphic::Embedded::default())),
                ..Default::default()
            }),
        };
        assert!(validate_object(&graphic, 0).is_err());
    }

    #[test]
    fn embedded_registry_denies_files_and_environment_but_keeps_typing() {
        let mut session = Session::new(Document::new());
        restrict_embedded_session(&mut session);
        for id in ["file.new", "file.open", "file.save", "font.add", "tools.macros", "mailings.finish"] {
            assert!(session.registry.get(id).is_none(), "{id}");
            assert!(session.run(id, &json!({})).is_err(), "{id}");
        }
        command(&mut session, UserEdit::InsertText("ação".into())).unwrap();
        command(&mut session, UserEdit::Undo).unwrap();
        assert!(session.path.is_none() && session.user_dict_path.is_none() && !session.autosave);
    }

    #[test]
    fn exported_docx_comes_from_edited_model() {
        let mut s = Session::new(Document::from_text("Licitação"));
        command(&mut s, UserEdit::InsertText("Nova ".into())).unwrap();
        let bytes = export(&s, ExportFormat::Docx).unwrap();
        let back = wordcraft_engine::io::open_bytes("x.docx", &bytes).unwrap();
        assert!(String::from_utf8(wordcraft_engine::io::save_bytes("x.txt", &back).unwrap()).unwrap().contains("Nova Licitação"));
    }

    #[test]
    fn imported_docx_uses_the_existing_codec_and_keeps_the_original_session() {
        let session = Session::new(example());
        let before = serialize(&session.doc).unwrap();
        let docx = export(&session, ExportFormat::Docx).unwrap();
        let checkpoint = import_docx(&docx).unwrap();
        let document = load_bytes(&checkpoint).unwrap();
        let text = wordcraft_engine::io::save_bytes("document.txt", &document).unwrap();
        assert!(String::from_utf8(text).unwrap().contains("Município — contratação pública"));
        assert_eq!(serialize(&document).unwrap(), checkpoint);
        assert_eq!(serialize(&session.doc).unwrap(), before);
    }

    #[test]
    fn docx_import_never_falls_back_to_text_json_or_an_unbounded_input() {
        for bytes in [b"plain text".as_slice(), b"{}", b"%PDF-document", b"PK\x03\x04invalid ZIP", b""] {
            assert!(import_docx(bytes).is_err());
        }
        assert!(import_docx(&vec![0; MAX_BYTES + 1]).is_err());
    }

    fn replace(story: StoryRef, path: Vec<u32>, start: usize, old: &str, new: &str) -> Value {
        json!({"op":"replace_text", "story":story, "path":path, "start_byte":start,
            "end_byte":start + old.len(), "old_text":old, "new_text":new})
    }

    fn patch_plan(bytes: &[u8], operations: Vec<Value>) -> Value {
        json!({"schema":PATCH_SCHEMA, "source_hash":sha256(bytes), "source_revision":1,
            "operations":operations})
    }

    #[test]
    fn patch_replaces_native_utf8_ranges_backwards_without_offset_drift() {
        let original = Document::from_text("Ação pública e órgão seguro.");
        let bytes = serialize(&original).unwrap();
        let plan = patch_plan(
            &bytes,
            vec![
                replace(StoryRef::Body, vec![0], "Ação pública e ".len(), "órgão", "município"),
                replace(StoryRef::Body, vec![0], 0, "Ação", "Atuação"),
            ],
        );
        let result = apply_patch(&bytes, 1, &serde_json::to_vec(&plan).unwrap()).unwrap();
        let document = load_bytes(&result).unwrap();
        assert_eq!(document.para(StoryRef::Body, &Path::top(0)).unwrap().text, "Atuação pública e município seguro.");
        assert_eq!(serialize(&original).unwrap(), bytes, "pure apply never changes the source");
    }

    #[test]
    fn patch_batch_is_one_native_work_session_undo_and_redo() {
        let bytes = serialize(&Document::from_text("Primeiro alvo.\nSegundo alvo.")).unwrap();
        let plan = patch_plan(
            &bytes,
            vec![replace(StoryRef::Body, vec![0], 0, "Primeiro", "Novo primeiro"), replace(StoryRef::Body, vec![1], 0, "Segundo", "Novo segundo")],
        );
        let mut session = Session::new(load_bytes(&bytes).unwrap());
        restrict_embedded_session(&mut session);
        let request = NativePatchRequest { current_revision: 1, observed_source_hash: sha256(&bytes), plan: serde_json::from_value(plan).unwrap() };
        apply_native_patch(&mut session, request).unwrap();
        let applied = serialize(&session.doc).unwrap();
        assert_ne!(applied, bytes);
        assert_eq!(session.undo_depth(), 1);
        assert_eq!(session.undo_label(), Some("GovConnect patch"));
        assert!(session.registry.get(PATCH_COMMAND).is_none());
        command(&mut session, UserEdit::Undo).unwrap();
        assert_eq!(serialize(&session.doc).unwrap(), bytes);
        command(&mut session, UserEdit::Redo).unwrap();
        assert_eq!(serialize(&session.doc).unwrap(), applied);
    }

    #[test]
    fn patch_preserves_uniform_bold_format_and_other_blocks_assets_and_stories() {
        let mut doc = example();
        let bold = wordcraft_doc::props::CharProps { bold: Some(true), ..Default::default() };
        let mut paragraph = Paragraph::with_text("Texto autorizado permanece.", bold.clone());
        paragraph.props.style = Some("Heading1".into());
        doc.body.insert(0, wordcraft_doc::para_block(paragraph));
        doc.parts.insert(
            7,
            wordcraft_doc::Part {
                kind: wordcraft_doc::PartKind::Header,
                blocks: vec![wordcraft_doc::para_block(Paragraph::with_text("Cabeçalho preservado", Default::default()))],
                ..Default::default()
            },
        );
        let bytes = serialize(&doc).unwrap();
        let plan = patch_plan(&bytes, vec![replace(StoryRef::Body, vec![0], "Texto ".len(), "autorizado", "corrigido")]);
        let result = load_bytes(&apply_patch(&bytes, 1, &serde_json::to_vec(&plan).unwrap()).unwrap()).unwrap();
        let paragraph = result.para(StoryRef::Body, &Path::top(0)).unwrap();
        assert_eq!(paragraph.text, "Texto corrigido permanece.");
        assert_eq!(paragraph.props.style.as_deref(), Some("Heading1"));
        assert!(paragraph.runs.iter().all(|run| run.props == bold));
        let request = NativePatchRequest { current_revision: 1, observed_source_hash: sha256(&bytes), plan: serde_json::from_value(plan).unwrap() };
        verify_native_patch(&doc, &result, &patch_operations(&doc, &request).unwrap()).unwrap();
    }

    #[test]
    fn patch_edits_a_table_cell_without_changing_table_geometry_or_neighbor_cells() {
        let mut doc = Document::new();
        let mut table = wordcraft_doc::Table::new(2, 2, 432.0);
        table.rows[0].cells[0].blocks = vec![wordcraft_doc::para_block(Paragraph::with_text("Célula autorizada", Default::default()))];
        table.rows[1].cells[1].blocks = vec![wordcraft_doc::para_block(Paragraph::with_text("Vizinha intacta", Default::default()))];
        doc.body = vec![Arc::new(Block::Table(table.clone()))];
        doc.ensure_nonempty();
        let bytes = serialize(&doc).unwrap();
        let plan = patch_plan(&bytes, vec![replace(StoryRef::Body, vec![0, 0, 0, 0], "Célula ".len(), "autorizada", "corrigida")]);
        let result = load_bytes(&apply_patch(&bytes, 1, &serde_json::to_vec(&plan).unwrap()).unwrap()).unwrap();
        assert_eq!(result.para(StoryRef::Body, &Path(vec![0, 0, 0, 0])).unwrap().text, "Célula corrigida");
        let mut actual = result.table(StoryRef::Body, &Path::top(0)).unwrap().clone();
        actual.rows[0].cells[0] = table.rows[0].cells[0].clone();
        assert_eq!(actual, table);
    }

    #[test]
    fn patch_stale_hash_revision_and_second_operation_failure_leave_source_and_undo_intact() {
        let bytes = serialize(&Document::from_text("Primeiro alvo.\nSegundo alvo.")).unwrap();
        let good = patch_plan(&bytes, vec![replace(StoryRef::Body, vec![0], 0, "Primeiro", "Novo")]);
        let mut plans = Vec::new();
        let mut hash = good.clone();
        hash["source_hash"] = json!("0".repeat(64));
        plans.push(hash);
        let mut revision = good.clone();
        revision["source_revision"] = json!(2);
        plans.push(revision);
        let mut second = good.clone();
        second["operations"].as_array_mut().unwrap().push(replace(StoryRef::Body, vec![1], 0, "Texto divergente", "Novo"));
        plans.push(second);
        for plan in plans {
            assert_eq!(apply_patch(&bytes, 1, &serde_json::to_vec(&plan).unwrap()).unwrap_err(), "native patch refused");
            let mut session = Session::new(load_bytes(&bytes).unwrap());
            let request =
                NativePatchRequest { current_revision: 1, observed_source_hash: sha256(&bytes), plan: serde_json::from_value(plan).unwrap() };
            assert!(apply_native_patch(&mut session, request).is_err());
            assert_eq!(serialize(&session.doc).unwrap(), bytes);
            assert_eq!(session.undo_depth(), 0);
        }
    }

    #[test]
    fn patch_refuses_overlapping_utf8_boundaries_control_characters_and_unknown_fields() {
        let bytes = serialize(&Document::from_text("Ação pública segura")).unwrap();
        let good = patch_plan(&bytes, vec![replace(StoryRef::Body, vec![0], 0, "Ação", "Atuação")]);
        let mut plans = Vec::new();
        let mut overlap = good.clone();
        overlap["operations"].as_array_mut().unwrap().push(replace(StoryRef::Body, vec![0], 0, "Ação", "Outra"));
        plans.push(overlap);
        let mut utf8 = good.clone();
        utf8["operations"][0]["end_byte"] = json!(2);
        plans.push(utf8);
        let mut unknown = good.clone();
        unknown["tenant_id"] = json!("untrusted");
        plans.push(unknown);
        let mut operation = good.clone();
        operation["operations"][0]["command"] = json!("file.open");
        plans.push(operation);
        let mut path = good.clone();
        path["operations"][0]["path"] = json!([0, 0]);
        plans.push(path);
        let mut missing = good.clone();
        missing["operations"][0]["path"] = json!([999]);
        plans.push(missing);
        let mut table = good.clone();
        table["operations"][0]["op"] = json!("insert_table");
        plans.push(table);
        for forbidden in ["linha\nnova", "coluna\ttab", "novo\rparágrafo", "objeto\u{FFFC}", "separador\u{2029}"] {
            let mut text = good.clone();
            text["operations"][0]["new_text"] = json!(forbidden);
            plans.push(text);
        }
        for plan in plans {
            assert!(apply_patch(&bytes, 1, &serde_json::to_vec(&plan).unwrap()).is_err());
        }
        let mut duplicate = serde_json::to_vec(&good).unwrap();
        duplicate.pop();
        duplicate.extend_from_slice(b",\"source_revision\":1}");
        assert!(apply_patch(&bytes, 1, &duplicate).is_err());
        assert!(apply_patch(&bytes, 0, &serde_json::to_vec(&good).unwrap()).is_err());
    }

    #[test]
    fn patch_refuses_mixed_runs_objects_tracking_and_protected_documents() {
        let mut mixed = Document::new();
        let mut paragraph = Paragraph::with_text("Texto ", Default::default());
        paragraph.insert_text(paragraph.len(), "misto", &wordcraft_doc::props::CharProps { bold: Some(true), ..Default::default() }).unwrap();
        mixed.body = vec![wordcraft_doc::para_block(paragraph)];
        let mut objects = Document::from_text("Texto simples");
        objects
            .para_mut(StoryRef::Body, &Path::top(0))
            .unwrap()
            .insert_object(0, InlineObject::Field { instr: "PAGE".into(), result: "1".into(), locked: false, code: false }, &Default::default())
            .unwrap();
        let mut tracking = Document::from_text("Texto simples");
        tracking.settings.track_changes = true;
        let mut protected = Document::from_text("Texto simples");
        protected.settings.protection = Some("readOnly".into());
        for doc in [mixed, objects, tracking, protected] {
            let bytes = serialize(&doc).unwrap();
            let text = &doc.para(StoryRef::Body, &Path::top(0)).unwrap().text;
            let start = text.find("Texto").unwrap();
            let plan = patch_plan(&bytes, vec![replace(StoryRef::Body, vec![0], start, "Texto", "Trecho")]);
            assert!(apply_patch(&bytes, 1, &serde_json::to_vec(&plan).unwrap()).is_err());
        }
    }

    #[test]
    fn patch_limits_and_unauthorized_native_side_effects_are_rejected() {
        let bytes = serialize(&Document::from_text("Texto simples")).unwrap();
        let good = patch_plan(&bytes, vec![replace(StoryRef::Body, vec![0], 0, "Texto", "Trecho")]);
        let mut empty = good.clone();
        empty["operations"] = json!([]);
        let mut excessive = good.clone();
        excessive["operations"] = json!(vec![good["operations"][0].clone(); MAX_PATCH_OPERATIONS + 1]);
        let mut large = good.clone();
        large["operations"][0]["new_text"] = json!("x".repeat(MAX_PATCH_TEXT + 1));
        for plan in [empty, excessive, large] {
            assert!(apply_patch(&bytes, 1, &serde_json::to_vec(&plan).unwrap()).is_err());
        }
        assert!(apply_patch(&bytes, 1, &vec![b' '; MAX_PATCH_BYTES + 1]).is_err());
        let applied = apply_patch(&bytes, 1, &serde_json::to_vec(&good).unwrap()).unwrap();
        let request = NativePatchRequest { current_revision: 1, observed_source_hash: sha256(&bytes), plan: serde_json::from_value(good).unwrap() };
        let original = load_bytes(&bytes).unwrap();
        let operations = patch_operations(&original, &request).unwrap();
        let mut changed = load_bytes(&applied).unwrap();
        changed.core.title = "Unauthorized metadata".into();
        assert!(verify_native_patch(&original, &changed, &operations).is_err());
    }

    #[test]
    fn patch_native_postcondition_failure_after_valid_edits_keeps_original_history() {
        let bold = wordcraft_doc::props::CharProps { bold: Some(true), ..Default::default() };
        let mut paragraph = Paragraph::with_text("Primeiro", bold);
        // A legal paragraph can have a different paragraph-mark format. Native
        // whole-paragraph replacement changes that mark; the adapter must refuse
        // the entire batch instead of silently broadening its formatting scope.
        paragraph.mark = Default::default();
        let mut doc = Document::from_text("unused\nSegundo alvo");
        doc.body[0] = wordcraft_doc::para_block(paragraph);
        let bytes = serialize(&doc).unwrap();
        let plan = patch_plan(
            &bytes,
            vec![replace(StoryRef::Body, vec![0], 0, "Primeiro", "Novo"), replace(StoryRef::Body, vec![1], 0, "Segundo", "Outro")],
        );
        let request = NativePatchRequest { current_revision: 1, observed_source_hash: sha256(&bytes), plan: serde_json::from_value(plan).unwrap() };
        assert!(patch_operations(&doc, &request).is_ok(), "preconditions pass before the native postcondition rejects");
        let mut session = Session::new(doc);
        assert!(apply_native_patch(&mut session, request).is_err());
        assert_eq!(serialize(&session.doc).unwrap(), bytes);
        assert_eq!(session.undo_depth(), 0);
        assert!(!session.dirty);
    }

    #[test]
    fn patch_deletes_a_range_and_can_address_a_real_header_story() {
        let mut doc = Document::from_text("Texto simples preservado");
        doc.parts.insert(
            7,
            wordcraft_doc::Part {
                kind: wordcraft_doc::PartKind::Header,
                blocks: vec![wordcraft_doc::para_block(Paragraph::with_text("Órgão antigo", Default::default()))],
                ..Default::default()
            },
        );
        let bytes = serialize(&doc).unwrap();
        let plan = patch_plan(
            &bytes,
            vec![
                replace(StoryRef::Body, vec![0], "Texto ".len(), "simples ", ""),
                replace(StoryRef::Part(7), vec![0], "Órgão ".len(), "antigo", "novo"),
            ],
        );
        let result = load_bytes(&apply_patch(&bytes, 1, &serde_json::to_vec(&plan).unwrap()).unwrap()).unwrap();
        assert_eq!(result.para(StoryRef::Body, &Path::top(0)).unwrap().text, "Texto preservado");
        assert_eq!(result.para(StoryRef::Part(7), &Path::top(0)).unwrap().text, "Órgão novo");
    }
}
