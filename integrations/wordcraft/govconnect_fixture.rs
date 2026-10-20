//! Local QA executable only. Not a production file/import or persistence API.
//! The workflow verifies the synthetic corpus hashes before invoking this tool.
use std::io::Read;
use std::path::Path;

use govconnect_wordcraft::{self as adapter, ExportFormat};
use wordcraft_engine::Session;

fn main() -> Result<(), String> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 3 {
        return Err("usage: govconnect_fixture SYNTHETIC_INPUT.docx NEW_OUTPUT_DIR".into());
    }
    let input = Path::new(&args[1]);
    let output = Path::new(&args[2]);
    if output.exists() {
        return Err("QA output directory must not already exist".into());
    }
    let mut bytes = Vec::new();
    std::fs::File::open(input)
        .map_err(|e| e.to_string())?
        .take((adapter::MAX_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    if bytes.is_empty() || bytes.len() > adapter::MAX_BYTES || !bytes.starts_with(b"PK\x03\x04") {
        return Err("QA input is not a bounded DOCX ZIP".into());
    }
    let doc = wordcraft_engine::io::open_bytes("synthetic.docx", &bytes)?;
    let checkpoint = adapter::serialize(&doc)?;
    let reopened = adapter::load_bytes(&checkpoint)?;
    if reopened != doc {
        return Err("native checkpoint changed the imported model".into());
    }
    let mut session = Session::new(reopened);
    adapter::restrict_embedded_session(&mut session);
    let docx = adapter::export(&session, ExportFormat::Docx)?;
    let pdf = adapter::export(&session, ExportFormat::Pdf)?;
    let text = wordcraft_engine::io::save_bytes("synthetic.txt", &session.doc)?;
    if !docx.starts_with(b"PK\x03\x04") || !pdf.starts_with(b"%PDF-") {
        return Err("native exporter returned an unexpected file type".into());
    }
    if docx.len() > 64 * 1024 * 1024 || pdf.len() > 64 * 1024 * 1024 {
        return Err("QA export exceeds the artifact byte bound".into());
    }
    std::fs::create_dir_all(output).map_err(|e| e.to_string())?;
    for (name, content) in [("checkpoint.json", checkpoint), ("roundtrip.docx", docx), ("roundtrip.pdf", pdf), ("model.txt", text)] {
        std::fs::write(output.join(name), content).map_err(|e| e.to_string())?;
    }
    println!("synthetic DOCX imported, native checkpoint equality verified, and DOCX/PDF emitted; fidelity approval pending");
    Ok(())
}
