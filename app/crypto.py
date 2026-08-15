import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _cipher() -> Fernet:
    digest = hashlib.sha256(get_settings().app_secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_mapping(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _cipher().encrypt(payload).decode("ascii")


def decrypt_mapping(value: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        return json.loads(_cipher().decrypt(value.encode("ascii")))
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Impossible de déchiffrer la configuration. Vérifiez APP_SECRET_KEY.") from exc
