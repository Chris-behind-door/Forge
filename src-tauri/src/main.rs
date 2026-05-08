// Keep console visible in release for now (sidecar debugging)
// TODO: remove this line once sidecar is stable
// #![cfg_attr(all(not(debug_assertions), not(feature = "console")), windows_subsystem = "windows")]

use std::net::TcpListener;
use std::process::Command;
use tauri::Emitter;
use tauri_plugin_shell::ShellExt;
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

fn spawn_output_reader(mut rx: tauri::async_runtime::Receiver<tauri_plugin_shell::process::CommandEvent>) {
    use tauri_plugin_shell::process::CommandEvent;
    std::thread::spawn(move || {
        while let Some(event) = rx.blocking_recv() {
            match event {
                CommandEvent::Stdout(line) => println!("[backend] {}", String::from_utf8_lossy(&line)),
                CommandEvent::Stderr(line) => eprintln!("[backend:err] {}", String::from_utf8_lossy(&line)),
                CommandEvent::Terminated(status) => {
                    eprintln!("[backend] Process exited with status: {:?}", status);
                    break;
                }
                CommandEvent::Error(err) => {
                    eprintln!("[backend] Error: {}", err);
                    break;
                }
                _ => {}
            }
        }
    });
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            // Generate IPC Token for backend authentication
            let ipc_token = Uuid::new_v4().to_string();

            // Find an available port for the backend
            let backend_port = find_available_port(8765, 100)
                .expect("No available port found in range 8765-8864");

            // In dev mode: run uvicorn on the backend source code directly
            // In prod mode: run the bundled sidecar binary
            if cfg!(debug_assertions) {
                // Dev mode: backend source is at ../backend/
                let manifest_dir = std::env::var("CARGO_MANIFEST_DIR")
                    .expect("CARGO_MANIFEST_DIR not set");
                let backend_dir = std::path::PathBuf::from(manifest_dir)
                    .parent()
                    .expect("Failed to get parent dir")
                    .join("backend");

                // Use venv's uvicorn directly
                let venv_python = backend_dir.join(".venv").join("bin").join("python");
                let venv_uvicorn = backend_dir.join(".venv").join("bin").join("uvicorn");

                println!("Starting backend from: {:?}", backend_dir);
                println!("Using uvicorn: {:?}", venv_uvicorn);
                println!("Backend port: {}", backend_port);

                // Run uvicorn using venv's python
                let _child = Command::new(&venv_python)
                    .args([
                        &venv_uvicorn.to_string_lossy(),
                        "src.main:app",
                        "--host", "127.0.0.1",
                        "--port", &backend_port.to_string(),
                        "--reload",
                    ])
                    .current_dir(&backend_dir)
                    .env("IPC_TOKEN", ipc_token.clone())
                    .spawn()
                    .expect("Failed to spawn backend");
            } else {
                // Prod mode: try sidecar first, fall back to PATH lookup
                println!("[Forge] Attempting to start backend...");
                println!("[Forge] Backend port: {}", backend_port);

                let backend_started = match app.shell().sidecar("binaries/backend") {
                    Ok(cmd) => {
                        match cmd
                            .env("IPC_TOKEN", ipc_token.clone())
                            .env("FORGE_PORT", backend_port.to_string())
                            .spawn()
                        {
                            Ok((rx, child)) => {
                                println!("[Forge] Backend sidecar started (PID: {:?})", child.pid());
                                spawn_output_reader(rx);
                                true
                            }
                            Err(e) => {
                                eprintln!("[Forge] Sidecar spawn failed: {}, trying PATH lookup...", e);
                                false
                            }
                        }
                    }
                    Err(e) => {
                        eprintln!("[Forge] Sidecar not found: {}, trying PATH lookup...", e);
                        false
                    }
                };

                if !backend_started {
                    // Fallback: look for 'backend' in PATH (e.g. /usr/bin/backend)
                    match Command::new("backend")
                        .env("IPC_TOKEN", ipc_token.clone())
                        .env("FORGE_PORT", backend_port.to_string())
                        .env("TMPDIR", dirs::data_local_dir().unwrap_or_else(|| std::path::PathBuf::from("/tmp")))
                        .spawn()
                    {
                        Ok(child) => {
                            println!("[Forge] Backend started via PATH (PID: {:?})", child.id());
                        }
                        Err(e) => {
                            eprintln!("[Forge] ERROR: Failed to start backend: {}", e);
                            eprintln!("[Forge] The application will start without the backend.");
                        }
                    }
                }
            }

            // Give backend time to start
            std::thread::sleep(std::time::Duration::from_millis(1000));

            // Send IPC Token and backend port to frontend
            if let Err(e) = app.emit("ipc-token", &ipc_token) {
                eprintln!("[Forge] Failed to emit ipc-token: {}", e);
            }
            if let Err(e) = app.emit("backend-port", backend_port) {
                eprintln!("[Forge] Failed to emit backend-port: {}", e);
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
