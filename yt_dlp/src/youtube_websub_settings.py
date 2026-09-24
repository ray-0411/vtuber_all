from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path


APP_ENTROPY = b"vtuber-live-status/youtube-websub/v1"
DEFAULT_SETTINGS_PATH = (
    Path(__file__).resolve().parents[1] / ".local" / "youtube_websub_control.json"
)


class DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


@dataclass
class YouTubeWebSubSettings:
    api_key: str = ""
    webhook_token: str = ""
    callback_url: str = ""
    mode: str = "quick_tunnel"
    api_database: str = "youtube_api_data.db"
    live_database: str = "live_data.db"
    config_database: str = "streamer_config.db"
    interval_seconds: int = 300
    candidate_limit: int = 1500


def _blob(data: bytes) -> tuple[DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data)
    blob = DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    return blob, buffer


def _crypt_protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Secure settings storage currently requires Windows DPAPI")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    input_blob, input_buffer = _blob(data)
    entropy_blob, entropy_buffer = _blob(APP_ENTROPY)
    output_blob = DataBlob()
    if not crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "VTuber YouTube WebSub settings",
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(output_blob),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _crypt_unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Secure settings storage currently requires Windows DPAPI")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    input_blob, input_buffer = _blob(data)
    entropy_blob, entropy_buffer = _blob(APP_ENTROPY)
    output_blob = DataBlob()
    description = wintypes.LPWSTR()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        ctypes.byref(description),
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(output_blob),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        if description:
            kernel32.LocalFree(description)
        kernel32.LocalFree(output_blob.pbData)


def save_settings(
    settings: YouTubeWebSubSettings,
    path: Path = DEFAULT_SETTINGS_PATH,
) -> None:
    secret_payload = json.dumps(
        {
            "api_key": settings.api_key,
            "webhook_token": settings.webhook_token,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    encrypted = base64.b64encode(_crypt_protect(secret_payload)).decode("ascii")
    public = asdict(settings)
    public.pop("api_key")
    public.pop("webhook_token")
    payload = {
        "version": 2,
        "windows_dpapi": encrypted,
        "settings": public,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(path)


def load_settings(
    path: Path = DEFAULT_SETTINGS_PATH,
) -> YouTubeWebSubSettings:
    if not path.exists():
        return YouTubeWebSubSettings()
    payload = json.loads(path.read_text(encoding="utf-8"))
    public = payload.get("settings") or {}
    encrypted = base64.b64decode(payload["windows_dpapi"])
    secret = json.loads(_crypt_unprotect(encrypted).decode("utf-8"))
    allowed = {
        field_name
        for field_name in YouTubeWebSubSettings.__dataclass_fields__
    }
    values = {
        key: value
        for key, value in {**public, **secret}.items()
        if key in allowed
    }
    return YouTubeWebSubSettings(**values)
