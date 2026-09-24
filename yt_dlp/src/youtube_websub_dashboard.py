#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from youtube_websub_settings import (
    DEFAULT_SETTINGS_PATH,
    YouTubeWebSubSettings,
    load_settings,
    save_settings,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TUNNEL_URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.I)
TOKEN_QUERY_PATTERN = re.compile(r"([?&]token=)[^&\s]+", re.I)
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MAX_FORM_BYTES = 65_536


def listening_pid(port: int) -> int | None:
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    pattern = re.compile(
        rf"^\s*TCP\s+\S*:{port}\s+\S+\s+LISTENING\s+(\d+)\s*$",
        re.I,
    )
    for line in result.stdout.splitlines():
        match = pattern.match(line)
        if match:
            return int(match.group(1))
    return None


def port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def find_cloudflared() -> str | None:
    discovered = shutil.which("cloudflared")
    if discovered:
        return discovered
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "cloudflared" / "cloudflared.exe",
        Path(os.environ.get("ProgramFiles", "")) / "cloudflared" / "cloudflared.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft"
        / "WinGet"
        / "Links"
        / "cloudflared.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


class PipelineRuntime:
    def __init__(self) -> None:
        try:
            self.settings = load_settings()
            load_message = "已載入加密設定"
        except Exception as exc:
            self.settings = YouTubeWebSubSettings()
            load_message = f"無法解密舊設定，請重新輸入：{exc}"
        self.processes: dict[str, subprocess.Popen[str]] = {}
        self.process_lock = threading.Lock()
        self.logs: deque[str] = deque(maxlen=500)
        self.log_lock = threading.Lock()
        self.pending_quick_start = False
        self.last_check = "尚未檢查。"
        self.log("dashboard", load_message)

    def log(self, role: str, message: str) -> None:
        message = TOKEN_QUERY_PATTERN.sub(r"\1[REDACTED]", message)
        if self.settings.webhook_token:
            message = message.replace(self.settings.webhook_token, "[REDACTED]")
        with self.log_lock:
            self.logs.append(
                f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{role}] {message.rstrip()}"
            )

    def log_text(self) -> str:
        with self.log_lock:
            return "\n".join(self.logs)

    def running_roles(self) -> list[str]:
        with self.process_lock:
            return sorted(
                role
                for role, process in self.processes.items()
                if process.poll() is None
            )

    def cloudflared_version(self) -> str | None:
        executable = find_cloudflared()
        if not executable:
            return None
        try:
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                creationflags=CREATE_NO_WINDOW,
                check=False,
            )
            return (result.stdout or result.stderr).strip() or "installed"
        except Exception:
            return "installed"

    def subscription_status(self) -> dict[str, int]:
        counts = {
            "total": 0,
            "verified": 0,
            "pending": 0,
            "error": 0,
            "denied": 0,
            "unsubscribed": 0,
        }
        database_path = Path(self.settings.api_database)
        if not database_path.is_file():
            return counts
        try:
            database_uri = database_path.resolve().as_uri() + "?mode=ro"
            with sqlite3.connect(database_uri, uri=True, timeout=5) as conn:
                rows = conn.execute(
                    """
                    SELECT status, count(*)
                    FROM youtube_websub_subscription
                    GROUP BY status
                    """
                ).fetchall()
        except sqlite3.Error:
            return counts
        for status, count in rows:
            if status in counts:
                counts[str(status)] = int(count)
            counts["total"] += int(count)
        return counts

    def validate(self, require_callback: bool = False) -> None:
        if not self.settings.api_key:
            raise ValueError("請先輸入 YouTube API key")
        if not self.settings.webhook_token:
            self.settings.webhook_token = secrets.token_urlsafe(32)
            self.save()
            self.log("settings", "已自動產生 webhook token")
        if require_callback and not self.settings.callback_url.startswith("https://"):
            raise ValueError("請先填入 HTTPS callback URL")
        if self.settings.interval_seconds <= 0:
            raise ValueError("間隔必須大於 0")
        if not 1 <= self.settings.candidate_limit <= 1700:
            raise ValueError("候選上限必須介於 1 到 1700")

    def apply_form(self, form: dict[str, list[str]]) -> None:
        def value(name: str) -> str:
            return form.get(name, [""])[0].strip()

        api_key = value("api_key")
        webhook_token = value("webhook_token")
        interval = int(
            value("interval_seconds") or str(self.settings.interval_seconds)
        )
        limit = int(value("candidate_limit") or str(self.settings.candidate_limit))
        if interval <= 0:
            raise ValueError("間隔必須大於 0")
        if not 1 <= limit <= 1700:
            raise ValueError("候選上限必須介於 1 到 1700")
        self.settings = YouTubeWebSubSettings(
            api_key=api_key or self.settings.api_key,
            webhook_token=webhook_token or self.settings.webhook_token,
            callback_url=value("callback_url"),
            mode=value("mode") or self.settings.mode,
            api_database=value("api_database") or "youtube_api_data.db",
            live_database=value("live_database") or "live_data.db",
            config_database=value("config_database") or "streamer_config.db",
            interval_seconds=interval,
            candidate_limit=limit,
        )
        self.save()

    def save(self) -> None:
        save_settings(self.settings)
        self.log("settings", "設定已用 Windows DPAPI 加密儲存")

    def generate_token(self) -> None:
        self.settings.webhook_token = secrets.token_urlsafe(32)
        self.save()
        self.log("settings", "已產生新的 webhook token")

    def process_environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env["YOUTUBE_API_KEY"] = self.settings.api_key
        env["YOUTUBE_WEBHOOK_TOKEN"] = self.settings.webhook_token
        env["YOUTUBE_WEBHOOK_CALLBACK_URL"] = self.settings.callback_url
        return env

    def spawn(
        self,
        role: str,
        command: list[str],
        line_callback: Callable[[str], None] | None = None,
    ) -> bool:
        with self.process_lock:
            existing = self.processes.get(role)
            if existing and existing.poll() is None:
                self.log(role, "已經在執行")
                return False
            process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                env=self.process_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
            self.processes[role] = process
        self.log(role, f"started pid={process.pid}")
        threading.Thread(
            target=self._read_process,
            args=(role, process, line_callback),
            daemon=True,
        ).start()
        return True

    def _read_process(
        self,
        role: str,
        process: subprocess.Popen[str],
        line_callback: Callable[[str], None] | None,
    ) -> None:
        if process.stdout is not None:
            for line in process.stdout:
                line = line.rstrip()
                self.log(role, line)
                if line_callback:
                    line_callback(line)
        return_code = process.wait()
        with self.process_lock:
            current = self.processes.get(role)
            if current and current.pid == process.pid:
                self.processes.pop(role, None)
        self.log(role, f"exited code={return_code}")

    def start_all(self) -> None:
        self.validate()
        webhook_pid = listening_pid(8787)
        webhook_managed_here = "webhook" in self.running_roles()
        if not webhook_managed_here and (
            webhook_pid is not None or port_is_open("127.0.0.1", 8787)
        ):
            owner = f" PID {webhook_pid}" if webhook_pid is not None else ""
            raise RuntimeError(
                f"8787 已被其他 Webhook 程序占用{owner}。"
                "請先關閉遺留程序，再啟動新管線。"
            )
        if self.settings.mode == "quick_tunnel":
            executable = find_cloudflared()
            if not executable:
                raise RuntimeError(
                    "找不到 cloudflared；請先執行 "
                    "`winget install --id Cloudflare.cloudflared`"
                )
            self.pending_quick_start = True
            started = self.spawn(
                "cloudflared",
                [executable, "tunnel", "--url", "http://127.0.0.1:8787"],
                self._inspect_tunnel_line,
            )
            if not started and self.settings.callback_url:
                self._start_services(subscribe_all=True)
            return
        self.validate(require_callback=True)
        self._start_services(subscribe_all=False)

    def _inspect_tunnel_line(self, line: str) -> None:
        match = TUNNEL_URL_PATTERN.search(line)
        if not match:
            return
        callback = f"{match.group(0)}/webhooks/youtube"
        if callback == self.settings.callback_url and not self.pending_quick_start:
            return
        self.settings.callback_url = callback
        self.save()
        self.log("cloudflared", f"callback={callback}")
        if self.pending_quick_start:
            self.pending_quick_start = False
            self._start_services(subscribe_all=True)

    def _start_services(self, subscribe_all: bool) -> None:
        self.initialize_database()
        self.start_webhook()
        self.start_scheduler()
        threading.Timer(
            1.2,
            lambda: self.subscribe(force_all=subscribe_all),
        ).start()

    def initialize_database(self) -> None:
        self.spawn(
            "init",
            [
                sys.executable,
                "src/init_youtube_api_db.py",
                "--database",
                self.settings.api_database,
                "--config-database",
                self.settings.config_database,
            ],
        )

    def start_webhook(self) -> None:
        self.validate(require_callback=True)
        self.spawn(
            "webhook",
            [
                sys.executable,
                "src/youtube_webhook_server.py",
                "--database",
                self.settings.api_database,
                "--config-database",
                self.settings.config_database,
            ],
        )

    def subscribe(self, force_all: bool = False) -> None:
        try:
            self.validate(require_callback=True)
            command = [
                sys.executable,
                "src/youtube_websub_subscribe.py",
                "--database",
                self.settings.api_database,
                "--config-database",
                self.settings.config_database,
            ]
            if not force_all:
                command.extend(["--due-within-hours", "24"])
            self.spawn("subscribe", command)
        except Exception as exc:
            self.log("subscribe", f"ERROR: {exc}")

    def run_once(self) -> None:
        self.validate()
        self.spawn(
            "api_once",
            [
                sys.executable,
                "src/youtube_api_collector.py",
                "--database",
                self.settings.api_database,
                "--config-database",
                self.settings.config_database,
                "--limit",
                str(self.settings.candidate_limit),
                "--interval-seconds",
                str(self.settings.interval_seconds),
            ],
        )

    def start_scheduler(self) -> None:
        self.validate()
        self.spawn(
            "scheduler",
            [
                sys.executable,
                "src/run_youtube_api_scheduler.py",
                "--database",
                self.settings.api_database,
                "--config-database",
                self.settings.config_database,
                "--interval-seconds",
                str(self.settings.interval_seconds),
                "--limit",
                str(self.settings.candidate_limit),
                "--run-immediately",
            ],
        )

    def compare(self) -> None:
        self.spawn(
            "compare",
            [
                sys.executable,
                "src/compare_youtube_collectors.py",
                "--live-database",
                self.settings.live_database,
                "--api-database",
                self.settings.api_database,
                "--config-database",
                self.settings.config_database,
            ],
        )

    def check_setup(self) -> None:
        settings = self.settings
        running = set(self.running_roles())
        results: list[tuple[bool, str]] = []

        results.append((bool(settings.api_key), "YouTube API key 已保存"))
        results.append((bool(settings.webhook_token), "Webhook token 已設定"))
        results.append(
            (
                settings.callback_url.startswith("https://"),
                f"HTTPS callback URL：{settings.callback_url or '尚未取得'}",
            )
        )
        if settings.mode == "quick_tunnel":
            results.append((find_cloudflared() is not None, "cloudflared 已安裝"))
            results.append(("cloudflared" in running, "Quick Tunnel 正在執行"))
        results.append(("webhook" in running, "Webhook Server 正在執行"))
        results.append(("scheduler" in running, "API Scheduler 正在執行"))

        database_path = Path(settings.api_database)
        results.append((database_path.is_file(), f"新資料庫：{database_path}"))
        subscription_count = 0
        active_count = 0
        candidate_count = 0
        event_count = 0
        if database_path.is_file():
            try:
                database_uri = database_path.resolve().as_uri() + "?mode=ro"
                with sqlite3.connect(database_uri, uri=True, timeout=5) as conn:
                    table_names = {
                        str(row[0])
                        for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table'"
                        )
                    }
                    required = {
                        "youtube_websub_subscription",
                        "youtube_websub_event",
                        "youtube_api_candidate",
                        "youtube_api_snapshot",
                        "youtube_api_current_status",
                    }
                    results.append(
                        (
                            required.issubset(table_names),
                            "WebSub/API 資料表已建立",
                        )
                    )
                    if "youtube_websub_subscription" in table_names:
                        subscription_count = int(
                            conn.execute(
                                "SELECT count(*) FROM youtube_websub_subscription"
                            ).fetchone()[0]
                        )
                        active_count = int(
                            conn.execute(
                                """
                                SELECT count(*)
                                FROM youtube_websub_subscription
                                WHERE status = 'verified'
                                """
                            ).fetchone()[0]
                        )
                    if "youtube_api_candidate" in table_names:
                        candidate_count = int(
                            conn.execute(
                                "SELECT count(*) FROM youtube_api_candidate"
                            ).fetchone()[0]
                        )
                    if "youtube_websub_event" in table_names:
                        event_count = int(
                            conn.execute(
                                "SELECT count(*) FROM youtube_websub_event"
                            ).fetchone()[0]
                        )
            except sqlite3.Error as exc:
                results.append((False, f"資料庫無法讀取：{exc}"))
        results.append(
            (
                subscription_count > 0 and active_count == subscription_count,
                f"WebSub 訂閱：共 {subscription_count}，已驗證 {active_count}",
            )
        )

        ready = all(ok for ok, _ in results)
        heading = "✅ 已設定完成並正在執行" if ready else "⚠️ 尚有項目需要處理"
        lines = [heading]
        lines.extend(f"{'✅' if ok else '❌'} {message}" for ok, message in results)
        lines.append(f"目前收到事件 {event_count} 筆，候選影片 {candidate_count} 筆")
        self.last_check = "\n".join(lines)
        for line in lines:
            self.log("check", line)

    def stop_all(self) -> None:
        self.pending_quick_start = False
        with self.process_lock:
            running = list(self.processes.items())
        for role, process in running:
            if process.poll() is None:
                self.log(role, f"stopping pid={process.pid}")
                process.terminate()

    def shutdown(self) -> None:
        self.stop_all()
        deadline = time.monotonic() + 2
        with self.process_lock:
            processes = list(self.processes.values())
        for process in processes:
            remaining = max(deadline - time.monotonic(), 0)
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.kill()


class DashboardServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], runtime: PipelineRuntime) -> None:
        super().__init__(address, DashboardHandler)
        self.runtime = runtime
        self.csrf_token = secrets.token_urlsafe(32)


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "YouTubeWebSubDashboard/1.0"

    @property
    def app(self) -> DashboardServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if urllib.parse.urlparse(self.path).path != "/":
            self.send_error(404)
            return
        body = self.render_dashboard().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if urllib.parse.urlparse(self.path).path != "/action":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400)
            return
        if length <= 0 or length > MAX_FORM_BYTES:
            self.send_error(413)
            return
        form = urllib.parse.parse_qs(
            self.rfile.read(length).decode("utf-8", errors="replace"),
            keep_blank_values=True,
        )
        if not secrets.compare_digest(
            form.get("csrf", [""])[0],
            self.app.csrf_token,
        ):
            self.send_error(403)
            return
        action = form.get("action", ["save"])[0]
        try:
            if action != "stop_all":
                self.app.runtime.apply_form(form)
            self.handle_action(action)
        except Exception as exc:
            self.app.runtime.log("dashboard", f"ERROR: {exc}")
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def handle_action(self, action: str) -> None:
        runtime = self.app.runtime
        actions: dict[str, Callable[[], None]] = {
            "save": runtime.save,
            "generate_token": runtime.generate_token,
            "start_all": runtime.start_all,
            "stop_all": runtime.stop_all,
            "init": runtime.initialize_database,
            "subscribe": runtime.subscribe,
            "run_once": runtime.run_once,
            "scheduler": runtime.start_scheduler,
            "compare": runtime.compare,
            "check_setup": runtime.check_setup,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(f"未知操作：{action}")
        handler()

    def render_dashboard(self) -> str:
        runtime = self.app.runtime
        settings = runtime.settings
        roles = runtime.running_roles()
        status = ", ".join(roles) if roles else "尚未啟動"
        cloudflared_version = runtime.cloudflared_version()
        cloudflared = cloudflared_version or "未安裝／不在 PATH"
        subscriptions = runtime.subscription_status()
        logs = html.escape(runtime.log_text())
        check_result = html.escape(runtime.last_check)
        callback = html.escape(settings.callback_url, quote=True)
        api_database = html.escape(settings.api_database, quote=True)
        live_database = html.escape(settings.live_database, quote=True)
        config_database = html.escape(settings.config_database, quote=True)
        api_state = "已保存" if settings.api_key else "尚未輸入"
        token_state = "已保存" if settings.webhook_token else "尚未產生"
        quick_selected = "selected" if settings.mode == "quick_tunnel" else ""
        fixed_selected = "selected" if settings.mode == "fixed" else ""
        cloud_class = "ok" if cloudflared_version else "warn"
        return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>YouTube WebSub + 官方 API 控制台</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 1100px; margin: 24px auto;
padding: 0 16px; background: #f4f6f8; color: #17212b; }}
.card {{ background: white; border-radius: 12px; padding: 18px; margin-bottom: 14px;
box-shadow: 0 2px 10px #00000012; }}
.grid {{ display: grid; grid-template-columns: 180px 1fr; gap: 10px 14px;
align-items: center; }}
input, select {{ box-sizing: border-box; width: 100%; padding: 9px;
border: 1px solid #bbc3cc; border-radius: 7px; }}
.buttons {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 9px; }}
.subscription-grid {{ display: grid; grid-template-columns: repeat(5, 1fr);
gap: 10px; text-align: center; }}
.subscription-grid div {{ padding: 12px; background: #f4f6f8; border-radius: 8px; }}
.subscription-grid strong {{ font-size: 1.6rem; }}
button {{ padding: 10px; border: 0; border-radius: 7px; background: #1769aa;
color: white; cursor: pointer; }}
button.stop {{ background: #b42318; }}
button.secondary {{ background: #52606d; }}
.ok {{ color: #067647; font-weight: 600; }}
.warn {{ color: #b54708; font-weight: 600; }}
pre {{ background: #111827; color: #d1fae5; padding: 14px; border-radius: 8px;
height: 280px; overflow: auto; white-space: pre-wrap; }}
.hint {{ color: #52606d; font-size: 0.92rem; }}
@media (max-width: 760px) {{
.grid {{ grid-template-columns: 1fr; }}
.buttons {{ grid-template-columns: 1fr 1fr; }}
.subscription-grid {{ grid-template-columns: 1fr 1fr; }}
}}
</style>
</head>
<body>
<h1>YouTube WebSub + 官方 API 控制台</h1>
<div class="card">
<div>狀態：<span class="ok">{html.escape(status)}</span></div>
<div>cloudflared：<span class="{cloud_class}">{html.escape(cloudflared)}</span></div>
<div class="hint">此控制台只管理新的官方 API 管線，不會停止或修改原 collector。</div>
</div>
<div class="card">
<h2>WebSub 訂閱狀態</h2>
<div class="subscription-grid">
<div><strong>{subscriptions["total"]}</strong><br>總訂閱數</div>
<div class="ok"><strong>{subscriptions["verified"]}</strong><br>已驗證</div>
<div class="warn"><strong>{subscriptions["pending"]}</strong><br>等待驗證</div>
<div><strong>{subscriptions["error"]}</strong><br>錯誤</div>
<div><strong>{subscriptions["denied"]}</strong><br>被拒絕</div>
</div>
<div class="hint">按下方「重新整理狀態」即可取得最新數量。</div>
</div>
<form method="post" action="/action">
<input type="hidden" name="csrf" value="{self.app.csrf_token}">
<div class="card grid">
<label>YouTube API key</label>
<div><input type="password" name="api_key" placeholder="{api_state}">
<span class="hint">留空會保留已保存的 key</span></div>
<label>Webhook token</label>
<div><input type="password" name="webhook_token" placeholder="{token_state}">
<span class="hint">留空會保留已保存的 token</span></div>
<label>模式</label>
<select name="mode">
<option value="quick_tunnel" {quick_selected}>Local Quick Tunnel</option>
<option value="fixed" {fixed_selected}>固定 HTTPS callback</option>
</select>
<label>公開 callback URL</label>
<input name="callback_url" value="{callback}" placeholder="Quick Tunnel 模式會自動填入">
<label>新管線資料庫</label>
<input name="api_database" value="{api_database}">
<label>舊資料庫（只供比較）</label>
<input name="live_database" value="{live_database}">
<label>VTuber 設定資料庫</label>
<input name="config_database" value="{config_database}">
<label>API 間隔（秒）</label>
<input name="interval_seconds" type="number" min="1"
value="{settings.interval_seconds}">
<label>每輪候選上限</label>
<input name="candidate_limit" type="number" min="1" max="1700"
value="{settings.candidate_limit}">
</div>
<div class="card">
<div class="buttons">
<button name="action" value="check_setup">檢查目前設定</button>
<button name="action" value="save">儲存設定</button>
<button name="action" value="generate_token">產生新 token</button>
<button name="action" value="start_all">一鍵啟動整套</button>
<button class="stop" name="action" value="stop_all">停止新管線</button>
<button class="secondary" name="action" value="init">初始化資料表</button>
<button class="secondary" name="action" value="subscribe">訂閱／續訂頻道</button>
<button class="secondary" name="action" value="run_once">官方 API 跑一輪</button>
<button class="secondary" name="action" value="scheduler">啟動 API Scheduler</button>
<button class="secondary" name="action" value="compare">比較新舊結果</button>
<button class="secondary" type="button" onclick="location.reload()">重新整理畫面</button>
</div>
</div>
</form>
<div class="card">
<h2>設定檢查結果</h2>
<pre>{check_result}</pre>
</div>
<div class="card">
<h2>執行紀錄</h2>
<pre>{logs}</pre>
<div class="hint">設定檔：{html.escape(str(DEFAULT_SETTINGS_PATH))}</div>
</div>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Open the local YouTube WebSub/API browser dashboard."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("the dashboard may only bind to localhost")

    if port_is_open("127.0.0.1", args.port):
        existing_url = f"http://127.0.0.1:{args.port}/"
        print(
            f"Dashboard port {args.port} is already in use; "
            "opening the existing dashboard."
        )
        if not args.no_browser:
            webbrowser.open(existing_url)
        return 0

    runtime = PipelineRuntime()
    server = DashboardServer((args.host, args.port), runtime)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"YouTube WebSub dashboard: {url}")
    print("Close this window or press Ctrl+C to stop dashboard-managed processes.")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping dashboard.")
    finally:
        server.server_close()
        runtime.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
