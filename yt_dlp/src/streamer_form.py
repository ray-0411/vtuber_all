#!/usr/bin/env python3
"""
Small local form for adding or updating streamers.

Usage:
    python src/streamer_form.py
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import threading
import tkinter as tk
from contextlib import closing
from datetime import datetime, timezone
from tkinter import messagebox, ttk

from add_streamer import add_streamer
from streamer_tables import list_streamer_tables, validate_group_name
from sync_streamers import sync_streamers
from twitch_utils import extract_twitch_login
from youtube_utils import fetch_youtube_channel_id


DEFAULT_CONFIG_DATABASE = "streamer_config.db"
DEFAULT_LIVE_DATABASE = "live_data.db"
DEFAULT_AUDIENCE_DATABASE = "streamer_audience.db"
FORM_GROUPS = ("other", "meridian", "squarelive", "envision", "thebox")


def configure_output_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def clean_text(value: str) -> str | None:
    value = value.strip()
    return value or None


def parse_display_order(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    return int(value)


def parse_nonnegative_count(value: str, label: str) -> int | None:
    value = value.strip().replace(",", "")
    if not value:
        return None
    count = int(value)
    if count < 0:
        raise ValueError(f"{label}不能小於 0。")
    return count


def save_audience(
    database: str, vtuber_id: str, name: str, group_name: str,
    youtube_url: str | None, youtube_channel_id: str | None,
    twitch_login: str | None, youtube_subscribers: int | None,
    twitch_followers: int | None, youtube_avatar_url: str | None,
    twitch_avatar_url: str | None,
) -> None:
    """Add optional manual audience values without clearing existing collected values."""
    with closing(sqlite3.connect(database)) as conn, conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(streamer_audience)")}
        required = {"vtuber_id", "name", "group_table", "updated_at"}
        if not required.issubset(columns):
            raise ValueError("audience 資料庫缺少 streamer_audience 表或必要欄位。")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        values = {
            "vtuber_id": vtuber_id, "name": name,
            "group_table": f"streamer_{group_name}", "updated_at": now,
        }
        optional = {
            "youtube_url": youtube_url,
            "youtube_channel_id": youtube_channel_id,
            "twitch_login": twitch_login,
            "youtube_subscribers": youtube_subscribers,
            "twitch_followers": twitch_followers,
            "youtube_avatar_url": youtube_avatar_url,
            "twitch_avatar_url": twitch_avatar_url,
        }
        values.update({key: value for key, value in optional.items() if key in columns and value is not None})
        names = ", ".join(f'"{key}"' for key in values)
        placeholders = ", ".join("?" for _ in values)
        updates = ", ".join(
            f'"{key}"=excluded."{key}"' for key in values if key != "vtuber_id"
        )
        conn.execute(
            f"INSERT INTO streamer_audience ({names}) VALUES ({placeholders}) "
            f"ON CONFLICT(vtuber_id) DO UPDATE SET {updates}",
            tuple(values.values()),
        )


class StreamerForm(ttk.Frame):
    def __init__(self, master: tk.Tk, config_database: str, live_database: str,
                 audience_database: str = DEFAULT_AUDIENCE_DATABASE) -> None:
        super().__init__(master, padding=16)
        self.master = master
        self.config_database = config_database
        self.live_database = live_database
        self.audience_database = audience_database

        self.group_var = tk.StringVar()
        self.vtuber_id_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.youtube_url_var = tk.StringVar()
        self.youtube_channel_id_var = tk.StringVar()
        self.twitch_url_var = tk.StringVar()
        self.twitch_login_var = tk.StringVar()
        self.display_order_var = tk.StringVar()
        self.note_var = tk.StringVar()
        self.youtube_subscribers_var = tk.StringVar()
        self.twitch_followers_var = tk.StringVar()
        self.youtube_avatar_url_var = tk.StringVar()
        self.twitch_avatar_url_var = tk.StringVar()
        self.enabled_var = tk.BooleanVar(value=True)
        self.sync_after_save_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="準備就緒。")

        self.group_combo: ttk.Combobox
        self.fetch_button: ttk.Button
        self.save_button: ttk.Button
        self.duplicate_result_text: tk.Text

        self.grid(sticky="nsew")
        self.build_widgets()
        self.refresh_groups()

    def build_widgets(self) -> None:
        self.master.title("新增／更新 VTuber")
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(self, text="所屬 Group").grid(row=row, column=0, sticky="w", pady=4)
        self.group_combo = ttk.Combobox(self, textvariable=self.group_var, state="readonly")
        self.group_combo.grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        ttk.Label(self, text="VTuber ID").grid(row=row, column=0, sticky="w", pady=4)
        vtuber_id_frame = ttk.Frame(self)
        vtuber_id_frame.grid(row=row, column=1, sticky="ew", pady=4)
        vtuber_id_frame.columnconfigure(0, weight=1)
        ttk.Entry(vtuber_id_frame, textvariable=self.vtuber_id_var).grid(
            row=0,
            column=0,
            sticky="ew",
        )
        ttk.Button(vtuber_id_frame, text="檢查重複 ID", command=self.test_duplicate_ids).grid(
            row=0,
            column=1,
            padx=(8, 0),
        )
        row += 1

        row = self.add_entry(row, "顯示名稱", self.name_var)
        row = self.add_entry(row, "YouTube 網址", self.youtube_url_var)

        ttk.Label(self, text="YouTube 頻道 ID").grid(row=row, column=0, sticky="w", pady=4)
        channel_frame = ttk.Frame(self)
        channel_frame.grid(row=row, column=1, sticky="ew", pady=4)
        channel_frame.columnconfigure(0, weight=1)
        ttk.Entry(channel_frame, textvariable=self.youtube_channel_id_var).grid(
            row=0, column=0, sticky="ew"
        )
        self.fetch_button = ttk.Button(
            channel_frame,
            text="自動取得",
            command=self.fetch_channel_id,
        )
        self.fetch_button.grid(row=0, column=1, padx=(8, 0))
        row += 1

        ttk.Label(self, text="Twitch 網址").grid(row=row, column=0, sticky="w", pady=4)
        twitch_url_frame = ttk.Frame(self)
        twitch_url_frame.grid(row=row, column=1, sticky="ew", pady=4)
        twitch_url_frame.columnconfigure(0, weight=1)
        ttk.Entry(twitch_url_frame, textvariable=self.twitch_url_var).grid(
            row=0,
            column=0,
            sticky="ew",
        )
        ttk.Button(twitch_url_frame, text="帶入帳號", command=self.fill_twitch_login).grid(
            row=0,
            column=1,
            padx=(8, 0),
        )
        self.twitch_url_var.trace_add("write", self.on_twitch_url_changed)
        row += 1

        row = self.add_entry(row, "Twitch 帳號", self.twitch_login_var)
        row = self.add_entry(row, "成員顯示順序", self.display_order_var)
        row = self.add_entry(row, "備註", self.note_var)
        row = self.add_entry(row, "YouTube 訂閱數（選填）", self.youtube_subscribers_var)
        row = self.add_entry(row, "Twitch 追隨數（選填）", self.twitch_followers_var)
        row = self.add_entry(row, "YouTube 頭像網址（選填）", self.youtube_avatar_url_var)
        row = self.add_entry(row, "Twitch 頭像網址（選填）", self.twitch_avatar_url_var)

        options = ttk.Frame(self)
        options.grid(row=row, column=1, sticky="w", pady=(8, 4))
        ttk.Checkbutton(options, text="啟用收集", variable=self.enabled_var).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Checkbutton(
            options,
            text="儲存後立即同步到 live_data.db（會寫入主資料庫）",
            variable=self.sync_after_save_var,
        ).grid(row=1, column=0, sticky="w")
        row += 1

        buttons = ttk.Frame(self)
        buttons.grid(row=row, column=1, sticky="e", pady=(12, 4))
        ttk.Button(buttons, text="清空", command=self.clear_form).grid(row=0, column=0, padx=(0, 8))
        self.save_button = ttk.Button(buttons, text="儲存", command=self.save_streamer)
        self.save_button.grid(row=0, column=1)
        row += 1

        ttk.Label(self, textvariable=self.status_var).grid(
            row=row,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(12, 0),
        )
        row += 1

        self.duplicate_result_text = tk.Text(self, height=5, wrap="word")
        self.duplicate_result_text.grid(
            row=row,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(8, 0),
        )
        self.duplicate_result_text.configure(state="disabled")
        self.rowconfigure(row, weight=1)

    def add_entry(self, row: int, label: str, variable: tk.StringVar) -> int:
        ttk.Label(self, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(self, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=4)
        return row + 1

    def refresh_groups(self) -> None:
        with sqlite3.connect(self.config_database) as conn:
            available = {table.removeprefix("streamer_") for table in list_streamer_tables(conn)}
        groups = [group for group in FORM_GROUPS if group in available]
        self.group_combo["values"] = groups
        if groups and self.group_var.get() not in groups:
            self.group_var.set(groups[0])

    def find_duplicate_vtuber_ids(self) -> dict[str, list[str]]:
        locations_by_id: dict[str, list[str]] = {}
        with sqlite3.connect(self.config_database) as conn:
            for table_name in list_streamer_tables(conn):
                rows = conn.execute(
                    f"""
                    SELECT vtuber_id, name
                    FROM {table_name}
                    ORDER BY vtuber_id
                    """
                ).fetchall()
                for vtuber_id, name in rows:
                    locations_by_id.setdefault(vtuber_id, []).append(f"{table_name} / {name}")

        return {
            vtuber_id: locations
            for vtuber_id, locations in locations_by_id.items()
            if len(locations) > 1
        }

    def find_vtuber_id_locations(self, vtuber_id: str) -> list[str]:
        locations: list[str] = []
        with sqlite3.connect(self.config_database) as conn:
            for table_name in list_streamer_tables(conn):
                rows = conn.execute(
                    f"""
                    SELECT name
                    FROM {table_name}
                    WHERE vtuber_id = ?
                    ORDER BY name
                    """,
                    (vtuber_id,),
                ).fetchall()
                locations.extend(f"{table_name} / {name}" for (name,) in rows)
        return locations

    def set_duplicate_result(self, text: str) -> None:
        self.duplicate_result_text.configure(state="normal")
        self.duplicate_result_text.delete("1.0", "end")
        self.duplicate_result_text.insert("1.0", text)
        self.duplicate_result_text.configure(state="disabled")

    def test_duplicate_ids(self) -> None:
        try:
            current_vtuber_id = self.vtuber_id_var.get().strip()
            current_locations = (
                self.find_vtuber_id_locations(current_vtuber_id)
                if current_vtuber_id
                else []
            )
            duplicates = self.find_duplicate_vtuber_ids()
        except Exception as exc:
            messagebox.showerror("檢查失敗", f"{type(exc).__name__}: {exc}")
            return

        if not current_locations and not duplicates:
            self.status_var.set("沒有發現重複的 VTuber ID。")
            if current_vtuber_id:
                self.set_duplicate_result(f"{current_vtuber_id} 尚未使用。")
            else:
                self.set_duplicate_result("沒有發現重複的 VTuber ID。")
            return

        lines: list[str] = []
        if current_vtuber_id:
            if current_locations:
                lines.append(f"這個 ID 已被使用：{current_vtuber_id}")
                lines.extend(f"- {location}" for location in current_locations)
            else:
                lines.append(f"這個 ID 尚未使用：{current_vtuber_id}")

        if duplicates:
            if lines:
                lines.append("")
            lines.append("以下 ID 在不同 Group 中重複：")
            for vtuber_id, locations in sorted(duplicates.items()):
                lines.append(f"- {vtuber_id}")
                lines.extend(f"  - {location}" for location in locations)
        result = "\n".join(lines)
        if current_locations:
            self.status_var.set(f"{current_vtuber_id} 已被使用。")
        else:
            self.status_var.set(f"發現 {len(duplicates)} 個重複的 VTuber ID。")
        self.set_duplicate_result(result)

    def fetch_channel_id(self) -> None:
        youtube_url = self.youtube_url_var.get().strip()
        if not youtube_url:
            messagebox.showerror("缺少 YouTube 網址", "請先輸入 YouTube 網址。")
            return

        self.fetch_button.configure(state="disabled")
        self.status_var.set("正在取得 YouTube 頻道 ID…")

        def worker() -> None:
            try:
                channel_id = fetch_youtube_channel_id(youtube_url)
            except Exception as exc:
                self.after(0, self.finish_fetch_channel_id, None, exc)
                return
            self.after(0, self.finish_fetch_channel_id, channel_id, None)

        threading.Thread(target=worker, daemon=True).start()

    def finish_fetch_channel_id(self, channel_id: str | None, exc: Exception | None) -> None:
        self.fetch_button.configure(state="normal")
        if exc is not None:
            self.status_var.set("無法取得 YouTube 頻道 ID。")
            messagebox.showerror("取得失敗", f"{type(exc).__name__}: {exc}")
            return
        if not channel_id:
            self.status_var.set("找不到 YouTube 頻道 ID。")
            messagebox.showwarning("找不到資料", "找不到 YouTube 頻道 ID。")
            return

        self.youtube_channel_id_var.set(channel_id)
        self.status_var.set(f"已取得 YouTube 頻道 ID：{channel_id}")

    def on_twitch_url_changed(self, *_args: object) -> None:
        if self.twitch_login_var.get().strip():
            return
        login = extract_twitch_login(self.twitch_url_var.get())
        if login:
            self.twitch_login_var.set(login)

    def fill_twitch_login(self) -> None:
        login = extract_twitch_login(self.twitch_url_var.get())
        if not login:
            messagebox.showwarning("找不到資料", "無法從網址取得 Twitch 帳號。")
            return
        self.twitch_login_var.set(login)
        self.status_var.set(f"已帶入 Twitch 帳號：{login}")

    def save_streamer(self) -> None:
        try:
            group_name = validate_group_name(self.group_var.get())
            if group_name not in FORM_GROUPS:
                raise ValueError("請選擇畫面上提供的 Group。")
            vtuber_id = self.vtuber_id_var.get().strip()
            name = self.name_var.get().strip()
            if not vtuber_id:
                raise ValueError("請輸入 VTuber ID。")
            if not name:
                raise ValueError("請輸入顯示名稱。")

            youtube_subscribers = parse_nonnegative_count(
                self.youtube_subscribers_var.get(), "YouTube 訂閱數"
            )
            twitch_followers = parse_nonnegative_count(
                self.twitch_followers_var.get(), "Twitch 追隨數"
            )
            youtube_avatar_url = clean_text(self.youtube_avatar_url_var.get())
            twitch_avatar_url = clean_text(self.twitch_avatar_url_var.get())
            audience_requested = any(
                value is not None for value in (
                    youtube_subscribers, twitch_followers,
                    youtube_avatar_url, twitch_avatar_url,
                )
            )

            table_name = add_streamer(
                database=self.config_database,
                group_name=group_name,
                vtuber_id=vtuber_id,
                name=name,
                youtube_url=clean_text(self.youtube_url_var.get()),
                youtube_channel_id=clean_text(self.youtube_channel_id_var.get()),
                twitch_url=clean_text(self.twitch_url_var.get()),
                twitch_login=clean_text(self.twitch_login_var.get()),
                enabled=1 if self.enabled_var.get() else 0,
                display_order=parse_display_order(self.display_order_var.get()),
                note=clean_text(self.note_var.get()),
            )
            audience_text = ""
            if audience_requested:
                save_audience(
                    self.audience_database, vtuber_id, name, group_name,
                    clean_text(self.youtube_url_var.get()),
                    clean_text(self.youtube_channel_id_var.get()),
                    clean_text(self.twitch_login_var.get()),
                    youtube_subscribers, twitch_followers,
                    youtube_avatar_url, twitch_avatar_url,
                )
                audience_text = " 已儲存補充資料。"
            synced_text = ""
            if self.sync_after_save_var.get():
                synced_count = sync_streamers(self.config_database, self.live_database)
                synced_text = f" 已同步 {synced_count} 位 VTuber 到 live_data.db。"
        except Exception as exc:
            messagebox.showerror("儲存失敗", f"{type(exc).__name__}: {exc}")
            return

        success_message = f"已儲存 {vtuber_id} 到 {table_name}。{audience_text}{synced_text}"
        self.clear_form()
        self.status_var.set(success_message)
        messagebox.showinfo("儲存完成", success_message)

    def clear_form(self) -> None:
        self.vtuber_id_var.set("")
        self.name_var.set("")
        self.youtube_url_var.set("")
        self.youtube_channel_id_var.set("")
        self.twitch_url_var.set("")
        self.twitch_login_var.set("")
        self.display_order_var.set("")
        self.note_var.set("")
        self.youtube_subscribers_var.set("")
        self.twitch_followers_var.set("")
        self.youtube_avatar_url_var.set("")
        self.twitch_avatar_url_var.set("")
        self.enabled_var.set(True)
        self.status_var.set("準備就緒。")


def main() -> int:
    configure_output_encoding()

    parser = argparse.ArgumentParser(description="開啟 VTuber 新增／更新視窗。")
    parser.add_argument("--config-database", default=DEFAULT_CONFIG_DATABASE)
    parser.add_argument("--live-database", default=DEFAULT_LIVE_DATABASE)
    parser.add_argument("--audience-database", default=DEFAULT_AUDIENCE_DATABASE)
    args = parser.parse_args()

    root = tk.Tk()
    root.minsize(760, 690)
    StreamerForm(root, args.config_database, args.live_database, args.audience_database)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
