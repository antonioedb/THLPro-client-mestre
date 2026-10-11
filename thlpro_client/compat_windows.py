from __future__ import annotations


import base64
import os


IS_WINDOWS = os.name == "nt"


try:
    import win32event  # type: ignore
    import win32api  # type: ignore
    import win32con  # type: ignore
    import winerror  # type: ignore
except Exception:  # pragma: no cover - ambiente Linux
    win32event = None
    win32api = None
    win32con = None
    winerror = None


try:
    import win32crypt  # type: ignore
except Exception:  # pragma: no cover - ambiente Linux
    win32crypt = None



def protect_data(raw: str) -> str:
    data = raw.encode("utf-8")
    if IS_WINDOWS and win32crypt:
        encrypted = win32crypt.CryptProtectData(data, "THLPro API Key", None, None, None, 0)
        return "dpapi:" + base64.b64encode(encrypted).decode("ascii")
    return "local:" + base64.b64encode(data).decode("ascii")



def unprotect_data(payload: str) -> str:
    if payload.startswith("dpapi:"):
        if not (IS_WINDOWS and win32crypt):
            raise RuntimeError("Token protegido com DPAPI só pode ser lido no Windows.")
        blob = base64.b64decode(payload.split(":", 1)[1])
        return win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1].decode("utf-8")
    if payload.startswith("local:"):
        blob = base64.b64decode(payload.split(":", 1)[1])
        return blob.decode("utf-8")
    raise RuntimeError("Formato de segredo inválido.")



def create_single_instance_lock(name: str):
    if IS_WINDOWS and win32event and win32api and win32con and winerror:
        handle = win32event.CreateMutex(None, False, name)
        already_running = win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS
        return handle, already_running
    lock_safe = name.replace('\\', '_')
    lock_path = f"/tmp/{lock_safe}.lock"
    if os.path.exists(lock_path):
        return lock_path, True
    with open(lock_path, "w", encoding="utf-8") as fp:
        fp.write(str(os.getpid()))
    return lock_path, False



def release_single_instance_lock(lock_obj) -> None:
    if IS_WINDOWS and win32api and win32event:
        try:
            win32api.CloseHandle(lock_obj)
        except Exception:
            pass
        return
    try:
        if isinstance(lock_obj, str) and os.path.exists(lock_obj):
            os.remove(lock_obj)
    except Exception:
        pass