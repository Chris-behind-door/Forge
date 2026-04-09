// Keep console visible in release for now (sidecar debugging)
// TODO: remove this line once sidecar is stable
// #![cfg_attr(all(not(debug_assertions), not(feature = "console")), windows_subsystem = "windows")]

use std::process::Command;
use tauri::Emitter;
use tauri_plugin_shell::ShellExt;
use uuid::Uuid;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            // Generate IPC Token for backend authentication
            let ipc_token = Uuid::new_v4().to_string();

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

                // Run uvicorn using venv's python
                let _child = Command::new(&venv_python)
                    .args([
                        &venv_uvicorn.to_string_lossy(),
                        "src.main:app",
                        "--host", "127.0.0.1",
                        "--port", "8765",
                        "--reload",
                    ])
                    .current_dir(&backend_dir)
                    .env("IPC_TOKEN", ipc_token.clone())
                    .spawn()
                    .expect("Failed to spawn backend");
            } else {
                // Prod mode: use bundled sidecar binary
                println!("[Forge] Attempting to start backend sidecar...");

                let sidecar_command = match app.shell().sidecar("binaries/backend") {
                    Ok(cmd) => cmd,
                    Err(e) => {
                        eprintln!("[Forge] ERROR: Failed to create sidecar command: {}", e);
                        eprintln!("[Forge] The application will start without the backend.");
                        app.emit("ipc-token", &ipc_token).ok();
                        return Ok(());
                    }
                };

                match sidecar_command.env("IPC_TOKEN", ipc_token.clone()).spawn() {
                    Ok((mut rx, child)) => {
                        println!("[Forge] Backend sidecar started successfully (PID: {:?})", child.pid());
                        // Log sidecar output in a background thread
                        std::thread::spawn(move || {
                            use tauri_plugin_shell::process::CommandEvent;
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
                    Err(e) => {
                        eprintln!("[Forge] ERROR: Failed to spawn backend sidecar: {}", e);
                        eprintln!("[Forge] The application will start without the backend.");
                    }
                }
            }

            // Give backend time to start
            std::thread::sleep(std::time::Duration::from_millis(1000));

            // Send IPC Token to frontend
            if let Err(e) = app.emit("ipc-token", &ipc_token) {
                eprintln!("[Forge] Failed to emit ipc-token: {}", e);
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
