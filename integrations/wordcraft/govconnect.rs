//! GovConnect's narrow adapter over the actual WordCraft model/session.
//! No authentication, persistence, network, file paths or LLM commands here.
//! The native snapshot retains the fields skipped by Document's plain JSON.
#![deny(clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::unimplemented, clippy::todo, clippy::unreachable)]

use std::collections::BTreeMap;
use std::io::{self, Write};
use std::sync::Arc;

use serde_json::{Value, json};
use wordcraft_doc::{Block, Document, InlineObject};
use wordcraft_engine::Session;

pub const SCHEMA: &str = "gc-wordcraft-snapshot/v1";
pub const MAX_BYTES: usize = 8 * 1024 * 1024;
const MAX_DEPTH: usize = 32;

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
    for assets in [&doc.media, &doc.passthrough] {
        if assets.len() > 1024 {
            return Err("too many snapshot assets".into());
        }
        for (key, bytes) in assets {
            if key.is_empty()
                || key.len() > 240
                || key.contains(['\\', ':'])
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
    if serde_json::to_value(&doc).map_err(|_| "model cannot be serialized".to_string())? != doc_value {
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
}
