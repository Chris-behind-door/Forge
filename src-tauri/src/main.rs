#![cfg_attr(all(not(debug_assertions), not(feature = "console")), windows_subsystem = "windows")]
// Use `cargo build --features console` to keep console window in release builds.

use std::net::TcpListener;
use std::process::Command;
use tauri::{Emitter, Manager};
use uuid::Uuid;

/// Try to bind to `base_port + i` for i in 0..max_tries, return first available.
fn find_available_port(base_port: u16, max_tries: u16) -> Option<u16> {
    (0..max_tries).find_map(|offset| {
        let port = base_port + offset;
        TcpListener::bind(("127.0.0.1", port))
            .ok()
            .map(|_| port)
    })
}

/// Pipe stdout/stderr from a child process to this process's stdout/stderr.
fn pipe_process_output(child: &mut std::process::Child) {
    use std::io::{BufRead, BufReader};
    if let Some(stdout) = child.stdout.take() {
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines().flatten() {
                println!("[backend] {line}");
            }
        });
    }
    if let Some(stderr) = child.stderr.take() {
        std::thread::spawn(move || {
            for line in BufReader::new(stderr).lines().flatten() {
                eprintln!("[backend:err] {line}");
            }
        });
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            // Set window icon (embedded at compile time, works in all modes)
            if let Some(window) = app.get_webview_window("main") {
                let icon = tauri::image::Image::from_bytes(include_bytes!("../icons/128x128.png"))
                    .expect("Failed to load embedded icon");
                let _ = window.set_icon(icon);
            }
            let ipc_token = Uuid::new_v4().to_string();
            let backend_port = find_available_port(8765, 100)
                .expect("No available port found in range 8765-8864");

            if cfg!(debug_assertions) {
                // Dev mode: run uvicorn directly from backend venv
                let manifest_dir =
                    std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR not set");
                let backend_dir = std::path::PathBuf::from(manifest_dir)
                    .parent()
                    .expect("Failed to get parent dir")
                    .join("backend");
                let venv_python = backend_dir.join(".venv/bin/python");
                let venv_uvicorn = backend_dir.join(".venv/bin/uvicorn");

                println!(
                    "[Forge] Dev mode – starting backend from {:?}",
                    backend_dir
                );
                println!("[Forge] Port: {backend_port}");

                Command::new(&venv_python)
                    .args([
                        &venv_uvicorn.to_string_lossy(),
                        "src.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        &backend_port.to_string(),
                        "--reload",
                    ])
                    .current_dir(&backend_dir)
                    .env("IPC_TOKEN", ipc_token.clone())
                    .spawn()
                    .expect("Failed to spawn backend");
            } else {
                // Prod mode: find backend relative to the executable
                // Linux: /usr/lib/engineer-assistant/backend/backend
                //   or: /usr/bin/backend (fallback)
                // Windows: <install_dir>/backend/backend.exe
                println!("[Forge] Prod mode – starting backend");
                println!("[Forge] Port: {backend_port}");

                let exe_dir = std::env::current_exe()
                    .ok()
                    .and_then(|p| p.parent().map(|d| d.to_path_buf()))
                    .unwrap_or_default();

                // Try relative path first, then PATH
                let backend_path = exe_dir.join("backend").join("backend");
                let backend_cmd = if backend_path.exists() {
                    println!("[Forge] Found backend at: {:?}", backend_path);
                    backend_path.to_string_lossy().to_string()
                } else {
                    println!("[Forge] Using backend from PATH");
                    "backend".to_string()
                };

                match Command::new(&backend_cmd)
                    .env("IPC_TOKEN", ipc_token.clone())
                    .env("FORGE_PORT", backend_port.to_string())
                    .stdout(std::process::Stdio::piped())
                    .stderr(std::process::Stdio::piped())
                    .spawn()
                {
                    Ok(mut child) => {
                        println!("[Forge] Backend started (PID: {:?})", child.id());
                        pipe_process_output(&mut child);
                    }
                    Err(e) => {
                        eprintln!("[Forge] ERROR: Failed to start backend: {e}");
                        eprintln!("[Forge] The application will start without the backend.");
                    }
                }
            }

            // Give backend time to start
            std::thread::sleep(std::time::Duration::from_millis(1000));

            if let Err(e) = app.emit("ipc-token", &ipc_token) {
                eprintln!("[Forge] Failed to emit ipc-token: {e}");
            }
            if let Err(e) = app.emit("backend-port", backend_port) {
                eprintln!("[Forge] Failed to emit backend-port: {e}");
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
