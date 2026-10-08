import json
import re
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class BrowserStateStore:
    def __init__(self, directory: Path, key: str):
        self.directory = Path(directory)
        self.enabled = bool(key)
        self._fernet = Fernet(key.encode()) if key else None

    def _path(self, session_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session_id):
            raise ValueError("Invalid browser session id")
        return self.directory / f"{session_id}.state"

    def load(self, session_id: str) -> dict | None:
        if not self.enabled:
            return None
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            decrypted = self._fernet.decrypt(path.read_bytes())
            state = json.loads(decrypted.decode("utf-8"))
            return state if isinstance(state, dict) else None
        except (InvalidToken, OSError, UnicodeDecodeError, json.JSONDecodeError):
            path.unlink(missing_ok=True)
            return None

    def save(self, session_id: str, state: dict) -> None:
        if not self.enabled:
            return
        path = self._path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        plaintext = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(self._fernet.encrypt(plaintext))
        temporary.replace(path)

    def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        existed = path.exists()
        path.unlink(missing_ok=True)
        return existed

    def metadata(self, session_id: str) -> dict:
        if not self.enabled:
            return {"enabled": False, "exists": False, "updated_at": None}
        path = self._path(session_id)
        exists = path.exists()
        updated_at = (
            datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
            if exists
            else None
        )
        return {"enabled": True, "exists": exists, "updated_at": updated_at}
