"""Store the video API key in the current user's OS credential store."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

_KEYCHAIN_SERVICE = "AI-pet.video-api"
_KEYCHAIN_ACCOUNT = "video-api"


def _mac_keyring():
    try:
        from keyring.backends.macOS import Keyring
    except ImportError as error:
        raise RuntimeError("macOS 钥匙串依赖缺失；请先运行 bash setup-macos.command。") from error
    return Keyring()


def storage_description() -> str:
    if sys.platform == "darwin":
        return "已保存在 macOS 钥匙串（仅当前用户可访问）"
    return "已安全保存 API Key（仅当前 Windows 用户可解密）"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _protect(data: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("当前密钥保存方式仅支持 Windows。")
    source_buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    name = "CryptUnprotectData" if decrypt else "CryptProtectData"
    operation = getattr(crypt32, name)
    operation.argtypes = [ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_DataBlob)]
    operation.restype = ctypes.c_int
    # CRYPTPROTECT_UI_FORBIDDEN; do not request interactive OS prompts.
    description = None if decrypt else ctypes.c_wchar_p("AI-pet video API key")
    if not operation(ctypes.byref(source), ctypes.cast(description, ctypes.c_void_p) if description else None,
                     None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


def key_path(app_root: Path) -> Path:
    return app_root / "data" / "api_key.dpapi"


def save_key(app_root: Path, key: str) -> None:
    key = key.strip()
    if not key or len(key) > 2048:
        raise ValueError("请输入有效的 API Key。")
    if sys.platform == "darwin":
        _mac_keyring().set_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ACCOUNT, key)
        return
    if os.name != "nt":
        raise RuntimeError("当前仅支持 Windows DPAPI 或 macOS 钥匙串。")
    path = key_path(app_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_bytes(_protect(key.encode("utf-8")))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_key(app_root: Path) -> str | None:
    if sys.platform == "darwin":
        return _mac_keyring().get_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ACCOUNT)
    if os.name != "nt":
        raise RuntimeError("当前仅支持 Windows DPAPI 或 macOS 钥匙串。")
    path = key_path(app_root)
    if not path.exists():
        return None
    return _protect(path.read_bytes(), decrypt=True).decode("utf-8")


def delete_key(app_root: Path) -> None:
    if sys.platform == "darwin":
        keyring = _mac_keyring()
        if keyring.get_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ACCOUNT) is not None:
            keyring.delete_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ACCOUNT)
        return
    if os.name != "nt":
        raise RuntimeError("当前仅支持 Windows DPAPI 或 macOS 钥匙串。")
    key_path(app_root).unlink(missing_ok=True)
