import json
from copy import deepcopy
from pathlib import Path

RUNTIME_DIR = Path(__file__).resolve().parent.parent / "storage" / "runtime"
ACTIVE_SESSION_FILE = RUNTIME_DIR / "active_stream_session.json"
COMPLETED_SESSIONS_FILE = RUNTIME_DIR / "completed_stream_sessions.json"
COLLECTOR_STATE_VERSION = 2

def load_json(path: Path, default=None):
    if not path.exists():
        return deepcopy(default)

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)

def write_json(path: Path, payload):
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    tmp_path.replace(path)

def load_active_session():
    return load_json(ACTIVE_SESSION_FILE)

def save_active_session(session: dict | None):
    if session is None:
        if ACTIVE_SESSION_FILE.exists():
            ACTIVE_SESSION_FILE.unlink()
        return
    write_json(ACTIVE_SESSION_FILE, session)

def append_completed_session(session: dict, reason: str):
    completed = load_json(COMPLETED_SESSIONS_FILE, default={"version": COLLECTOR_STATE_VERSION, "sessions": []})
    completed.setdefault("version", COLLECTOR_STATE_VERSION)
    completed.setdefault("sessions", [])

    from runtime.utils import now_iso
    session["collector"]["completed_at"] = now_iso()
    session["collector"]["completion_reason"] = reason
    completed["sessions"].append(session)
    write_json(COMPLETED_SESSIONS_FILE, completed)

def prepare_storage_dir():
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
