/**
 * Shared API base URL with dynamic port from Tauri event.
 * Fallback to 8765 when not running inside Tauri (e.g. dev convenience).
 */
let _backendPort = 8765

export function setBackendPort(port: number): void {
  _backendPort = port
}

export function getApiBase(): string {
  return `http://127.0.0.1:${_backendPort}`
}
