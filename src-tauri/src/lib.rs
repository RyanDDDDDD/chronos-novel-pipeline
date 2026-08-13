mod sidecar;

use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use tauri::RunEvent;

use sidecar::heartbeat_loop;

// The rest of the sidecar lifecycle (spawn/health-poll/navigate/graceful-shutdown-
// with-kill-fallback) only runs in release builds -- dev mode never spawns a sidecar
// (spec D6): `tauri dev` points the window straight at the Vite dev server via devUrl
// in tauri.conf.json, and the backend is already running via the repo root's sequenced
// `npm run dev`. These imports are only needed by that release-only path.
#[cfg(not(debug_assertions))]
use sidecar::{graceful_shutdown, poll_until_healthy, ShutdownOutcome};
#[cfg(not(debug_assertions))]
use std::sync::Mutex;
#[cfg(not(debug_assertions))]
use tauri::Manager;
#[cfg(not(debug_assertions))]
use tauri_plugin_shell::process::CommandChild;
#[cfg(not(debug_assertions))]
use tauri_plugin_shell::ShellExt;
#[cfg(not(debug_assertions))]
use tokio::time::sleep;

// Backend port -- release's sidecar and dev's sequenced `npm run dev` launcher both
// bind here (spec D1 for release; dev mirrors it so the heartbeat loop below, which
// runs in both build modes, can share this constant).
const BACKEND_URL: &str = "http://127.0.0.1:8775";

// Mirrors what the retired release/windows/start.bat used to do before launching
// chronos.exe directly: seed config/config.json from the bundled config.example.json
// (backend's utils/config.py:_load exits immediately if config.json is missing) and
// ensure data/ exists. Idempotent -- only acts on a fresh CHRONOS_ROOT.
#[cfg(not(debug_assertions))]
fn seed_first_run_state(
    app_data_dir: &std::path::Path,
    resource_dir: &std::path::Path,
) -> std::io::Result<()> {
    let config_dir = app_data_dir.join("config");
    std::fs::create_dir_all(&config_dir)?;
    let config_json = config_dir.join("config.json");
    if !config_json.exists() {
        std::fs::copy(resource_dir.join("config.example.json"), &config_json)?;
    }
    let model_catalog_json = config_dir.join("model_catalog.json");
    if !model_catalog_json.exists() {
        std::fs::copy(resource_dir.join("model_catalog.json"), &model_catalog_json)?;
    }
    std::fs::create_dir_all(app_data_dir.join("data"))?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|_app, _args, _cwd| {}))
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            // Dev mode (spec D6): the window already loads devUrl (Vite dev server)
            // per tauri.conf.json, and the backend is already running -- brought up
            // ahead of `cargo run` by the repo root's sequenced `npm run dev`
            // (beforeDevCommand), which waits for it to report healthy before
            // starting Vite. No sidecar to spawn, no health-poll/navigate needed --
            // just start heartbeating so the backend's watchdog (heartbeat_watchdog.py)
            // knows this dev session is alive and can reap itself if it isn't anymore.
            #[cfg(debug_assertions)]
            {
                tauri::async_runtime::spawn(heartbeat_loop(
                    || async {
                        let _ = reqwest::Client::new()
                            .post(format!("{BACKEND_URL}/api/heartbeat"))
                            .send()
                            .await;
                    },
                    Duration::from_secs(5),
                ));
            }

            #[cfg(not(debug_assertions))]
            {
                let app_data_dir = app.path().app_local_data_dir()?;
                let resource_dir = app.path().resource_dir()?;
                seed_first_run_state(&app_data_dir, &resource_dir)
                    .expect("failed to seed first-run config/data directories");

                let shell = app.shell();
                let sidecar_command = shell
                    .sidecar("chronos")?
                    .args(["--port", "8775", "--no-browser"])
                    .env("CHRONOS_ROOT", app_data_dir.to_string_lossy().to_string());
                let (mut _rx, child) = sidecar_command
                    .spawn()
                    .expect("failed to spawn chronos sidecar");
                app.manage(Mutex::new(Some(child)));

                // Drain the sidecar's stdout/stderr so the channel doesn't back up; the
                // backend already writes its own log file (see logs/server.log under
                // CHRONOS_ROOT) so we don't duplicate that here.
                tauri::async_runtime::spawn(async move { while _rx.recv().await.is_some() {} });

                let app_handle = app.handle().clone();
                tauri::async_runtime::spawn(async move {
                    let check = || async {
                        reqwest::get(format!("{BACKEND_URL}/api/health"))
                            .await
                            .map(|r| r.status().is_success())
                            .unwrap_or(false)
                    };
                    let ready = poll_until_healthy(
                        check,
                        Duration::from_secs(15),
                        Duration::from_millis(200),
                    )
                    .await;
                    if ready.is_ok() {
                        if let Some(window) = app_handle.get_webview_window("main") {
                            let _ = window
                                .navigate(BACKEND_URL.parse().expect("BACKEND_URL is a valid URL"));
                        }
                        tauri::async_runtime::spawn(heartbeat_loop(
                            || async {
                                let _ = reqwest::Client::new()
                                    .post(format!("{BACKEND_URL}/api/heartbeat"))
                                    .send()
                                    .await;
                            },
                            Duration::from_secs(5),
                        ));
                    } else {
                        eprintln!("[tauri] backend sidecar never became healthy within 15s");

                        // Sidecar never confirmed healthy -- no point posting /api/shutdown to it,
                        // just kill it directly so it doesn't linger as an orphan. This is a
                        // separate path from the normal ExitRequested handler below: that one
                        // still runs afterwards (app_handle.exit() re-triggers it), but by then
                        // the child is already `None` here so its own kill step is a no-op.
                        let state = app_handle.state::<Mutex<Option<CommandChild>>>();
                        let child = state.lock().expect("sidecar child mutex poisoned").take();
                        if let Some(child) = child {
                            let _ = child.kill();
                        }

                        // Static page bundled in frontendDist -- reachable without the backend.
                        // The window is still showing that same origin's index.html at this point
                        // (nothing has navigated it away yet), so a relative redirect is enough.
                        if let Some(window) = app_handle.get_webview_window("main") {
                            let _ = window.eval("window.location.replace('error.html')");
                        }

                        let app_handle = app_handle.clone();
                        tauri::async_runtime::spawn(async move {
                            sleep(Duration::from_secs(10)).await;
                            app_handle.exit(1);
                        });
                    }
                });
            }

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run({
            let shutting_down = AtomicBool::new(false);
            move |app_handle, event| {
                if let RunEvent::ExitRequested { api, .. } = event {
                    // AppHandle::exit() itself re-triggers ExitRequested, so without this guard
                    // prevent_exit() would fire forever: prevent -> shut down -> exit() -> re-enter
                    // -> prevent again -> ... and the process would never actually terminate.
                    // Only run the graceful-shutdown dance once; let every subsequent
                    // ExitRequested (including the one exit() itself raises) proceed normally.
                    if shutting_down.swap(true, Ordering::SeqCst) {
                        return;
                    }
                    api.prevent_exit();
                    let app_handle = app_handle.clone();
                    tauri::async_runtime::spawn(async move {
                        #[cfg(not(debug_assertions))]
                        {
                            let state = app_handle.state::<Mutex<Option<CommandChild>>>();
                            let child = state.lock().expect("sidecar child mutex poisoned").take();
                            if let Some(child) = child {
                                let post = || async {
                                    reqwest::Client::new()
                                        .post(format!("{BACKEND_URL}/api/shutdown"))
                                        .send()
                                        .await
                                        .map(|r| r.status().is_success())
                                        .unwrap_or(false)
                                };
                                let kill = move || {
                                    let _ = child.kill();
                                };
                                let _: ShutdownOutcome =
                                    graceful_shutdown(post, kill, Duration::from_secs(3)).await;
                            }
                        }
                        // Dev mode: no CommandChild here (this process never spawned the
                        // backend, the sequenced launcher did), so there's no kill
                        // fallback -- best-effort graceful POST only. If it fails (backend
                        // already gone, network hiccup), the heartbeat watchdog's
                        // HEARTBEAT_TIMEOUT_S backstop reaps it once pings stop.
                        #[cfg(debug_assertions)]
                        {
                            let _ = reqwest::Client::new()
                                .post(format!("{BACKEND_URL}/api/shutdown"))
                                .send()
                                .await;
                        }
                        app_handle.exit(0);
                    });
                }
            }
        });
}
