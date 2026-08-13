"""Chronos Engine — WebUI startup portal

Usage:
    uv run python run.py [--port 8775] [--no-browser]
    uv run python run.py --dev # engine+gateway dual-process + Vite, Ctrl+C stops both
    uv run python run.py --sequenced # combined single process, sequenced with Vite (root `npm run dev`)

After starting, select a chapter in the browser and click "Start" to trigger the pipeline."""
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

from utils.paths import PROJECT_ROOT as _ROOT

_VITE_CWD = os.path.join(_ROOT, "src", "frontend")


def _is_port_in_use(port: int) -> bool:
    """
Check whether the local port is occupied (TCP connection test)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _find_free_port(
    start: int, reserved: frozenset[int] = frozenset(), max_attempts: int = 50
) -> int:
    """Probe real socket binds starting at `start`, skipping `reserved` ports,
    and return the first port this process can actually claim. A bind test
    (not `_is_port_in_use`'s connect test) is required here -- what we care
    about is whether *we* can listen on it, not whether something else
    currently is."""
    for offset in range(max_attempts):
        port = start + offset
        if port in reserved:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(
        f"未能在 {start}..{start + max_attempts - 1} 范围内找到可用端口"
    )


def _wait_for_health(port: int, timeout: float) -> bool:
    """Poll /api/health until it responds or `timeout` seconds elapse.

    Must fully read the response body before the `with` block closes the connection --
    otherwise closing a socket with unread bytes still sitting in its receive buffer makes
    the OS send a TCP RST instead of a clean FIN, which the backend's asyncio ProactorEventLoop
    (Windows) then logs as a spurious "Exception in callback ... ConnectionResetError" on
    the server side. Harmless either way, but draining the body avoids the noise."""
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.0) as resp:
                resp.read()
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.3)
    return False


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    """End the child process and its descendants (npm→node requires /T to exit simultaneously under Windows)."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _should_relaunch_for_console(
    *,
    dev: bool,
    distributed: bool,
    sequenced: bool,
    platform: str,
    already_relaunched: bool,
    stdin_isatty: bool,
    stdout_isatty: bool,
) -> bool:
    """Decide whether the current invocation should re-exec itself into a
    fresh process with its own real Windows console.

    Only true for the three interactive dev launch flags (--dev/
    --distributed/--sequenced) -- deliberately excludes the bare default
    combined mode, which is exactly what the packaged production Tauri
    sidecar invokes (`chronos --port 8775 --no-browser`, no dev flags).
    Widening this to match the broader `is_dashboard_owner` check in
    main() would pop a stray console window for every end user of the
    shipped desktop app.
    """
    return (
        platform == "win32"
        and (dev or distributed or sequenced)
        and not already_relaunched
        and not (stdin_isatty and stdout_isatty)
    )


def _relaunch_command(root: str, executable: str, argv: list[str]) -> list[str]:
    """Build the command line to re-run this same launch as a fresh process."""
    return [executable, os.path.join(root, "run.py"), *argv]


def _relaunch_in_new_console() -> None:
    """Re-exec the current invocation as a fresh process with its own real
    Windows console, so the interactive dashboard (mouse scroll, text
    selection) works even though the current process's stdio is a pipe
    rather than a real terminal -- e.g. under `tauri dev`'s beforeDevCommand,
    which captures and re-prints child stdout instead of attaching a
    console. CREATE_NEW_CONSOLE only changes console attachment, not the
    parent-child process relationship, so _terminate_process_tree's
    `taskkill /T` still reaches this process and everything it spawns."""
    cmd = _relaunch_command(root=_ROOT, executable=sys.executable, argv=sys.argv[1:])
    env = {**os.environ, "CHRONOS_RELAUNCHED_CONSOLE": "1"}
    proc = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE, env=env)
    print(
        f"[Chronos] 当前终端非真实 TTY，已在独立控制台窗口启动交互式面板"
        f"（PID {proc.pid}）——切换到那个窗口查看/滚动日志。"
    )
    try:
        rc = proc.wait()
    except KeyboardInterrupt:
        _terminate_process_tree(proc)
        rc = 1
    sys.exit(rc)


def _spawn_vite(vite_log_path: str, vite_port: int, backend_port: int) -> subprocess.Popen | None:
    """
Pull up the Vite development server in the front-end directory and redirect stdout/stderr to vite_log_path.

    - If vite_port is already occupied, skip (the user has manually started it).
    - backend_port is exported as CHRONOS_BACKEND_PORT so vite.config.ts can point its /api and /ws
      proxies at wherever the backend actually ended up (see _find_free_port).
    - Return Popen object; please use _terminate_process_tree() to clean up the entire process tree when exiting."""

    if _is_port_in_use(vite_port):
        print(f"[Dev] Vite 已在 :{vite_port} 运行，直接接入。")
        return None

    print(f"[Dev] 启动 Vite 开发服务器（:{vite_port}）...")
    vite_log_f = open(vite_log_path, "w", encoding="utf-8")
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    return subprocess.Popen(
        [npm, "run", "dev"],
        cwd=_VITE_CWD,
        stdin=subprocess.DEVNULL,
        stdout=vite_log_f,
        stderr=subprocess.STDOUT,
        env={**os.environ, "CHRONOS_BACKEND_PORT": str(backend_port)},
    )


def _run_cache_hit_report(log_dir: str) -> None:
    """Best-effort: dump the author/chat/sandbox prompt-cache hit-rate breakdown to
    logs/cache_hit_report.log on every dev-session teardown, so it's there to glance
    at without a manual `scripts/cache_hit_report.py` invocation. Failure here must
    never block shutdown -- swallow and print a one-line note instead."""
    script = os.path.join(_ROOT, "scripts", "cache_hit_report.py")
    out_path = os.path.join(log_dir, "cache_hit_report.log")
    try:
        result = subprocess.run(
            [sys.executable, script, "--verbose"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(result.stdout)
            if result.stderr:
                f.write("\n--- stderr ---\n")
                f.write(result.stderr)
        print(f"[Chronos] cache 命中率报告 → {out_path}")
    except (OSError, subprocess.SubprocessError) as e:
        print(f"[Chronos] cache_hit_report 生成失败（不影响关闭）：{e}")


def _run_launcher(*, dev: bool, hub_port: int, no_browser: bool) -> None:
    """同机拉起 engine(:engine_port, 本机) + gateway(:hub_port, 对外) 子进程（+dev Vite），Ctrl+C 同停。"""
    from utils.config import engine_port, vite_dev_port

    eport = engine_port()
    vport = vite_dev_port()
    log_dir = os.path.join(_ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)

    #── dev：仅清一次引擎累积日志（避免子进程各自 wipe 相互干扰）──
    if dev:
        import shutil

        for _sub in ("engine", "engine_server"):
            try:
                shutil.rmtree(os.path.join(log_dir, _sub))
            except (OSError, FileNotFoundError):
                pass  #不存在或被占用 → 忽略，后续 setup 会重建

    py = sys.executable
    run_py = os.path.join(_ROOT, "run.py")

    def _spawn(role: str, port: int, extra_env: dict, log_name: str) -> subprocess.Popen:
        env = {**os.environ, **extra_env, "CHRONOS_ROLE": role}
        log_f = open(os.path.join(log_dir, log_name), "w", encoding="utf-8")
        return subprocess.Popen(
            [py, run_py, "--role", role, "--port", str(port), "--no-browser"],
            env=env,
            stdout=log_f,
            stderr=subprocess.STDOUT,
        )

    #engine 传 --port hub_port（用于拼 CHRONOS_GATEWAY_WS 缺省），自身 bind engine_port()
    engine_proc = _spawn("engine", hub_port, {
        "CHRONOS_GATEWAY_WS": f"ws://127.0.0.1:{hub_port}/internal/engine",
    }, "engine.console.log")
    gateway_proc = _spawn("gateway", hub_port, {
        "CHRONOS_ENGINE_URL": f"http://127.0.0.1:{eport}",
    }, "gateway.console.log")
    procs: list[subprocess.Popen] = [engine_proc, gateway_proc]

    vite_proc: subprocess.Popen | None = None
    if dev:
        vite_proc = _spawn_vite(os.path.join(log_dir, "vite.log"), vport, hub_port)

    if not no_browser:
        url = f"http://localhost:{vport if dev else hub_port}"

        def _open_browser() -> None:
            time.sleep(2.0)  #等子进程起监听
            webbrowser.open(url)

        threading.Thread(target=_open_browser, daemon=True).start()

    from dev_console import Dashboard, ServiceStatus, _probe_http_health, _probe_tcp

    info_lines = [
        f"gateway http://localhost:{hub_port}",
        f"engine :{eport}",
        f"日志: {log_dir}/server-gateway.log, server-engine.log",
    ]
    if dev:
        info_lines.append(f"前端 http://localhost:{vport}")

    services = [
        ServiceStatus(
            "gateway", hub_port,
            is_alive=lambda: gateway_proc.poll() is None,
            is_healthy=lambda: _probe_http_health(hub_port),
            pid=gateway_proc.pid,
        ),
        ServiceStatus(
            "engine", eport,
            is_alive=lambda: engine_proc.poll() is None,
            is_healthy=lambda: _probe_http_health(eport),
            pid=engine_proc.pid,
        ),
    ]
    if vite_proc is not None:
        services.append(ServiceStatus(
            "vite", vport,
            is_alive=lambda: vite_proc.poll() is None,
            is_healthy=lambda: _probe_tcp(vport),
            pid=vite_proc.pid,
        ))
    elif dev:
        services.append(ServiceStatus(
            "vite", vport, is_alive=lambda: True, is_healthy=lambda: _probe_tcp(vport),
        ))

    dashboard = Dashboard(
        services,
        info_lines,
        still_running=lambda: all(p.poll() is None for p in procs),
        log_paths=[
            os.path.join(log_dir, "server-gateway.log"),
            os.path.join(log_dir, "server-engine.log"),
        ],
    )
    try:
        dashboard.run()
    except KeyboardInterrupt:
        pass
    finally:
        print("[Chronos] 正在同步关闭子进程...")
        for p in ([vite_proc] if vite_proc else []) + procs:
            _terminate_process_tree(p)
        if dev:
            _run_cache_hit_report(log_dir)


def _run_dev_sequenced(hub_port: int, no_browser: bool) -> None:
    """Combined-process dev launcher: bring up the backend on the already-resolved
    hub_port (see main()'s centralized _find_free_port call), wait for it to report
    healthy, *then* start Vite -- Ctrl+C tears both down together.

    Replaces parallel-launching backend+Vite (the old root `npm run dev` via
    `concurrently`): starting both at once raced the frontend's API proxy against
    backend boot, and if the session was killed uncleanly neither side owned the
    other's lifetime, so the backend could survive as an orphan on hub_port and
    break the next launch (see docs/superpowers/specs/2026-07-16-frontend-heartbeat-
    watchdog-design.md background)."""
    from utils.config import vite_dev_port

    vport = vite_dev_port()
    log_dir = os.path.join(_ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)

    py = sys.executable
    run_py = os.path.join(_ROOT, "run.py")
    backend_proc = subprocess.Popen(
        [py, run_py, "--port", str(hub_port), "--no-browser"],
        env={**os.environ, "CHRONOS_CHILD_PROCESS": "1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    print(f"[Dev] 等待后端 :{hub_port} 就绪...")
    if not _wait_for_health(hub_port, timeout=30.0):
        print("[Dev] 后端 30 秒内未就绪，中止启动。", file=sys.stderr)
        _terminate_process_tree(backend_proc)
        sys.exit(1)

    vite_proc = _spawn_vite(os.path.join(log_dir, "vite.log"), vport, hub_port)

    if not no_browser:
        def _open_browser() -> None:
            time.sleep(1.0)
            webbrowser.open(f"http://localhost:{vport}")

        threading.Thread(target=_open_browser, daemon=True).start()

    from dev_console import Dashboard, ServiceStatus, _probe_http_health, _probe_tcp

    services = [
        ServiceStatus(
            "backend", hub_port,
            is_alive=lambda: backend_proc.poll() is None,
            is_healthy=lambda: _probe_http_health(hub_port),
            pid=backend_proc.pid,
        ),
    ]
    if vite_proc is not None:
        services.append(ServiceStatus(
            "vite", vport,
            is_alive=lambda: vite_proc.poll() is None,
            is_healthy=lambda: _probe_tcp(vport),
            pid=vite_proc.pid,
        ))
    else:
        services.append(ServiceStatus(
            "vite", vport, is_alive=lambda: True, is_healthy=lambda: _probe_tcp(vport),
        ))

    server_log = os.path.join(log_dir, "server.log")
    dashboard = Dashboard(
        services,
        [
            f"后端 http://localhost:{hub_port}",
            f"前端 http://localhost:{vport}",
            f"日志: {server_log}",
        ],
        still_running=lambda: (
            backend_proc.poll() is None and (vite_proc is None or vite_proc.poll() is None)
        ),
        log_paths=[server_log],
    )
    try:
        dashboard.run()
    except KeyboardInterrupt:
        pass
    finally:
        print("[Chronos] 正在同步关闭子进程...")
        for p in ([vite_proc] if vite_proc else []) + [backend_proc]:
            _terminate_process_tree(p)
        _run_cache_hit_report(log_dir)


def main() -> None:
    import argparse
    from datetime import datetime

    import uvicorn
    from loguru import logger
    from shared.log import add_setup_chat_tool_sink, setup_engine_logger
    from utils.config import get_config, server_port, vite_dev_port

    cfg = get_config()
    default_hub_port = server_port()
    default_vite_port = vite_dev_port()

    parser = argparse.ArgumentParser(description="Chronos Engine WebUI 服务器")
    parser.add_argument(
        "--port", type=int, default=default_hub_port, help="公共端口（浏览器连接）"
    )
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument(
        "--dev", action="store_true",
        help=f"开发模式：拉起 engine+gateway 双进程 + Vite（:{default_vite_port}），Ctrl+C 同停",
    )
    parser.add_argument(
        "--role", choices=["combined", "engine", "gateway"], default="combined",
        help="进程角色：combined=单进程(默认)；engine/gateway=双进程之一",
    )
    parser.add_argument(
        "--distributed", action="store_true",
        help="生产双进程：同机拉起 engine+gateway（不含 Vite）",
    )
    parser.add_argument(
        "--sequenced", action="store_true",
        help="单进程顺序启动：拉起后端 → 等 /api/health 就绪 → 再拉起 Vite，Ctrl+C 同停",
    )
    args = parser.parse_args()

    if _should_relaunch_for_console(
        dev=args.dev,
        distributed=args.distributed,
        sequenced=args.sequenced,
        platform=sys.platform,
        already_relaunched=bool(os.environ.get("CHRONOS_RELAUNCHED_CONSOLE")),
        stdin_isatty=sys.stdin.isatty(),
        stdout_isatty=sys.stdout.isatty(),
    ):
        _relaunch_in_new_console()
        return

    from utils.config import engine_port

    #── 集中式端口解析：只有"顶层交互式调用"才探测；子进程信任父进程已经解析好的 --port，
    #  因为 engine 子进程根本不绑定这个数字（它绑定自己的 engine_port()，args.port 只是用来拼
    #  CHRONOS_GATEWAY_WS 默认值的字符串），对它重新探测会产生错误的端口漂移 ──
    if args.role == "combined" and not os.environ.get("CHRONOS_CHILD_PROCESS"):
        reserved = (
            frozenset({engine_port(cfg)}) if (args.dev or args.distributed) else frozenset()
        )
        hub_port = _find_free_port(args.port, reserved=reserved)
        if hub_port != args.port:
            print(f"[Chronos] 端口 :{args.port} 被占用，自动切换到 :{hub_port}")
    else:
        hub_port = args.port

    #── 启动器：--dev/--distributed 拉起 engine+gateway（+Vite）双进程，Ctrl+C 同停 ──
    if args.dev or args.distributed:
        _run_launcher(dev=args.dev, hub_port=hub_port, no_browser=args.no_browser)
        return

    #── --sequenced：单进程 combined + 顺序拉起 Vite（根 npm run dev 用这个）──
    if args.sequenced:
        _run_dev_sequenced(hub_port=hub_port, no_browser=args.no_browser)
        return

    role = args.role
    os.environ["CHRONOS_SERVER_PORT"] = str(hub_port)

    #── 按角色选 ASGI app 与 bind：gateway=对外唯一边缘；engine=仅本机；combined=今天单进程 ──
    if role == "gateway":
        os.environ.setdefault("CHRONOS_ENGINE_URL", f"http://127.0.0.1:{engine_port()}")
        from api.gateway_app import app as asgi_app  # noqa: E402
        bind_host, bind_port, log_name = "0.0.0.0", hub_port, "server-gateway.log"
    elif role == "engine":
        os.environ["CHRONOS_ROLE"] = "engine"
        os.environ.setdefault(
            "CHRONOS_GATEWAY_WS", f"ws://127.0.0.1:{hub_port}/internal/engine"
        )
        from api.hub import app as asgi_app  # noqa: E402
        bind_host, bind_port, log_name = "127.0.0.1", engine_port(), "server-engine.log"
    else:  # combined（默认，与今天单进程一致）
        from api.hub import app as asgi_app  # noqa: E402
        bind_host, bind_port, log_name = "127.0.0.1", hub_port, "server.log"

    #── 后端日志文件（按角色分文件，避免双进程写同一 server.log 相互覆盖）──
    log_dir = os.path.join(_ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_name)
    with open(log_path, "w", encoding="utf-8") as _f:
        _f.write(f"{'='*60}\n")
        _f.write(f"  Chronos {role} 服务器日志\n")
        _f.write(f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        _f.write(f"  端口: {bind_port}\n")
        _f.write(f"{'='*60}\n\n")

    #顶层交互式 combined 进程用仪表盘接管终端，不需要再往 stderr 重复打彩色日志；
    #子进程（engine/gateway，以及 --sequenced 派生的 combined 子进程）stdout/stderr 已被
    #父进程重定向到日志文件，这个 sink 写到哪里都不会污染任何人的终端，但没必要浪费这份 I/O。
    is_dashboard_owner = role == "combined" and not os.environ.get("CHRONOS_CHILD_PROCESS")

    #文件 + stderr 双写；NDJSON prompt 日志排除
    logger.remove()
    _log_filter = lambda r: "_ndjson_id" not in r["extra"]  # noqa: E731
    logger.add(
        log_path, format="{time:HH:mm:ss.SSS} | {level:<8} | {message}",
        level="DEBUG", encoding="utf-8", filter=_log_filter,
    )
    if not is_dashboard_owner:
        logger.add(
            sys.stderr,
            format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level:<8}</level> | {message}",
            level="DEBUG", colorize=True, filter=_log_filter,
        )
    setup_engine_logger(0)
    add_setup_chat_tool_sink()

    #── 仅 combined 单进程自动开浏览器（双进程由启动器统一开）──
    if not args.no_browser and role == "combined":
        def _open_browser() -> None:
            time.sleep(1.5)
            webbrowser.open(f"http://localhost:{hub_port}")
        threading.Thread(target=_open_browser, daemon=True).start()

    if is_dashboard_owner:
        from dev_console import Dashboard, ServiceStatus, _probe_http_health

        server = uvicorn.Server(
            uvicorn.Config(asgi_app, host=bind_host, port=bind_port, log_level="warning")
        )
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()

        services = [ServiceStatus(
            "chronos", bind_port,
            is_alive=server_thread.is_alive,
            is_healthy=lambda: _probe_http_health(bind_port),
            pid=os.getpid(),
        )]
        dashboard = Dashboard(
            services,
            [f"http://localhost:{bind_port}", f"日志: {log_path}"],
            still_running=server_thread.is_alive,
            log_paths=[log_path],
        )
        try:
            dashboard.run()
        except KeyboardInterrupt:
            pass
        finally:
            server.should_exit = True
            server_thread.join(timeout=10)
    else:
        print(f"[Chronos] {role} 启动 → http://localhost:{bind_port}")
        print(f"[Chronos] 日志文件 → {log_path}")
        uvicorn.run(asgi_app, host=bind_host, port=bind_port, log_level="warning")


if __name__ == "__main__":
    main()
