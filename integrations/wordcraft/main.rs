//! Embedded GovConnect entry point. The authenticated host starts the supplied canvas explicitly.
#![deny(clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::unimplemented, clippy::todo, clippy::unreachable)]

#[cfg(target_arch = "wasm32")]
mod govconnect_browser;

fn main() {}
