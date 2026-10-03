//! Notizer Desktop-App: startet den Notizer Core als Hintergrundprozess und
//! gibt Port und Zugriffstoken an die Oberfläche weiter.
//!
//! - Release: Der Core liegt als `notizer-core(.exe)` neben der App (von Tauri
//!   über `externalBin` mitgeliefert).
//! - Entwicklung (`npm run tauri dev`): Der Core wird direkt aus dem Ordner
//!   `core/` mit Python gestartet, ohne vorher eine Binärdatei zu bauen.
//!
//! Der Core beendet sich selbst, sobald seine Standardeingabe geschlossen wird.
//! Das passiert automatisch, wenn die App endet oder abstürzt.

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::{Manager, RunEvent};

#[derive(Clone, Serialize, Deserialize)]
struct CoreInfo {
    port: u16,
    token: String,
}

#[derive(Default)]
struct CoreState {
    info: Mutex<Option<CoreInfo>>,
    child: Mutex<Option<Child>>,
}

/// Port und Token des Cores, sobald er bereit ist (sonst `null`).
#[tauri::command]
fn core_info(state: tauri::State<'_, CoreState>) -> Option<CoreInfo> {
    state.info.lock().ok().and_then(|g| g.clone())
}

fn core_command() -> Command {
    if cfg!(debug_assertions) {
        // Entwicklung: python -m notizer_core aus dem Ordner core/
        let core_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../core");
        let venv_python = if cfg!(windows) {
            core_dir.join(".venv/Scripts/python.exe")
        } else {
            core_dir.join(".venv/bin/python")
        };
        let python = std::env::var("NOTIZER_PYTHON").map(PathBuf::from).unwrap_or_else(|_| {
            if venv_python.exists() {
                venv_python
            } else if cfg!(windows) {
                PathBuf::from("python")
            } else {
                PathBuf::from("python3")
            }
        });
        let mut cmd = Command::new(python);
        cmd.args(["-m", "notizer_core"]).current_dir(core_dir);
        cmd
    } else {
        // Release: Binärdatei neben der App
        let exe = std::env::current_exe().expect("Pfad der App nicht ermittelbar");
        let dir = exe.parent().expect("Ordner der App nicht ermittelbar");
        let name = if cfg!(windows) { "notizer-core.exe" } else { "notizer-core" };
        Command::new(dir.join(name))
    }
}

fn start_core(app: &tauri::AppHandle) -> std::io::Result<()> {
    let mut cmd = core_command();
    cmd.arg("--exit-on-stdin-close")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = cmd.spawn()?;
    let stdout = child.stdout.take().expect("stdout des Cores fehlt");
    let handle = app.clone();

    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Some(json) = line.strip_prefix("NOTIZER_READY ") {
                match serde_json::from_str::<CoreInfo>(json) {
                    Ok(info) => {
                        let state = handle.state::<CoreState>();
                        if let Ok(mut guard) = state.info.lock() {
                            *guard = Some(info);
                        };
                    }
                    Err(err) => eprintln!("[notizer] Unerwartete Meldung vom Core: {err}"),
                }
            } else {
                println!("[core] {line}");
            }
        }
    });

    *app.state::<CoreState>().child.lock().unwrap() = Some(child);
    Ok(())
}

fn stop_core(app: &tauri::AppHandle) {
    if let Some(mut child) = app.state::<CoreState>().child.lock().unwrap().take() {
        drop(child.stdin.take()); // Core beendet sich selbst
        std::thread::sleep(std::time::Duration::from_millis(300));
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(CoreState::default())
        .invoke_handler(tauri::generate_handler![core_info])
        .setup(|app| {
            if let Err(err) = start_core(app.handle()) {
                eprintln!("[notizer] Core konnte nicht gestartet werden: {err}");
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Notizer konnte nicht gestartet werden")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                stop_core(app);
            }
        });
}
