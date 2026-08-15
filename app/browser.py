import re
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import decrypt_mapping
from app.database import get_db
from app.models import Connector
from app.schemas import BrowserNavigate

router = APIRouter(prefix="/api/v1/browser", tags=["embedded-browser"])

GOOGLE_APP_HOSTS = {
    "mail.google.com",
    "chat.google.com",
    "drive.google.com",
    "docs.google.com",
    "sheets.google.com",
    "slides.google.com",
    "calendar.google.com",
}
_managed_target_id: str | None = None


def _cdp_request(method: str, path: str, timeout: float = 4.0) -> Any:
    settings = get_settings()
    response = httpx.request(
        method,
        f"{settings.embedded_browser_cdp_url.rstrip('/')}{path}",
        headers={"Host": "localhost"},
        timeout=timeout,
    )
    response.raise_for_status()
    if not response.content:
        return None
    if "application/json" in response.headers.get("content-type", ""):
        try:
            return response.json()
        except ValueError:
            # Chromium labels the plain-text activate/close responses as JSON.
            pass
    return response.text


def _targets() -> list[dict[str, Any]]:
    targets = _cdp_request("GET", "/json/list")
    return [target for target in targets if target.get("type") == "page" and target.get("url")]


def _configured_odoo_origin(db: Session) -> str:
    connector = db.get(Connector, "odoo")
    if not connector or not connector.configuration_secret:
        return ""
    try:
        return urlparse(decrypt_mapping(connector.configuration_secret).get("url", "")).netloc
    except ValueError:
        return ""


def _allowed_url(value: str, db: Session) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.scheme == "https" and parsed.hostname in GOOGLE_APP_HOSTS:
        return True
    return bool(parsed.netloc and parsed.netloc == _configured_odoo_origin(db))


def _source(value: str, odoo_origin: str = "") -> str | None:
    hostname = urlparse(value).hostname
    if hostname == "mail.google.com":
        return "gmail"
    if hostname == "chat.google.com":
        return "chat"
    if hostname in {"drive.google.com", "docs.google.com", "sheets.google.com", "slides.google.com"}:
        return "drive"
    if hostname == "calendar.google.com":
        return "calendar"
    if hostname and hostname == odoo_origin:
        return "odoo"
    return None


def _external_id(source: str, value: str) -> str:
    parsed = urlparse(value)
    fragment = unquote(parsed.fragment)
    if source == "gmail":
        return next((part for part in reversed(fragment.split("/")) if part), f"gmail:{parsed.path}")
    if source == "chat":
        parts = [part for part in parsed.path.split("/") if part]
        return ":".join(parts[-2:]) or "chat:home"
    if source == "drive":
        match = re.search(r"/(?:d|folders)/([^/]+)", parsed.path)
        return match.group(1) if match else parse_qs(parsed.query).get("id", [f"drive:{parsed.path}"])[0]
    if source == "calendar":
        return fragment or f"{parsed.path}?{parsed.query}".rstrip("?")
    params = parse_qs(parsed.query)
    fragment_params = parse_qs(fragment)
    model = (params.get("model") or fragment_params.get("model") or ["odoo.record"])[0]
    record_id = (params.get("id") or fragment_params.get("id") or [parsed.path])[0]
    return f"{model}:{record_id}"


def _resource(target: dict[str, Any], odoo_origin: str = "") -> dict[str, Any] | None:
    url = target.get("url", "")
    source = _source(url, odoo_origin)
    if not source or url.startswith(("chrome://", "chrome-extension://", "devtools://")):
        return None
    title = target.get("title") or f"{source} · élément courant"
    return {
        "source": source,
        "external_id": _external_id(source, url),
        "title": title[:300],
        "url": url,
        "resource_type": {
            "gmail": "thread",
            "chat": "space-or-message",
            "drive": "drive-item",
            "calendar": "event",
            "odoo": "record",
        }[source],
        "excerpt": f"Rattaché depuis le navigateur intégré · {title}"[:2000],
        "extra": {"capture_mode": "embedded-browser"},
    }


def _current_target() -> dict[str, Any] | None:
    targets = _targets()
    if _managed_target_id:
        managed = next((target for target in targets if target.get("id") == _managed_target_id), None)
        if managed:
            return managed
    usable = [
        target
        for target in targets
        if not target.get("url", "").startswith(("chrome://", "chrome-extension://", "devtools://"))
    ]
    return usable[0] if usable else (targets[0] if targets else None)


@router.get("/status")
def browser_status(db: Session = Depends(get_db)):
    settings = get_settings()
    if not settings.embedded_browser_enabled:
        return {"enabled": False, "ready": False, "public_url": "", "current": None}
    try:
        target = _current_target()
        return {
            "enabled": True,
            "ready": True,
            "public_url": settings.embedded_browser_public_url,
            "current": _resource(target, _configured_odoo_origin(db)) if target else None,
        }
    except (httpx.HTTPError, ValueError):
        return {
            "enabled": True,
            "ready": False,
            "public_url": settings.embedded_browser_public_url,
            "current": None,
        }


@router.get("/current")
def browser_current(db: Session = Depends(get_db)):
    try:
        target = _current_target()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Le navigateur intégré démarre encore") from exc
    if not target:
        return {"resource": None}
    return {
        "resource": _resource(target, _configured_odoo_origin(db)),
        "title": target.get("title", ""),
        "url": target.get("url", ""),
    }


@router.post("/navigate")
def browser_navigate(payload: BrowserNavigate, db: Session = Depends(get_db)):
    global _managed_target_id
    url = str(payload.url)
    if not _allowed_url(url, db):
        raise HTTPException(status_code=400, detail="Cette destination n’est pas autorisée dans le navigateur intégré")
    previous_id = _managed_target_id
    try:
        target = _cdp_request("PUT", f"/json/new?{quote(url, safe=':/?=&%')}", timeout=8)
        _managed_target_id = target["id"]
        _cdp_request("GET", f"/json/activate/{_managed_target_id}")
        if previous_id and previous_id != _managed_target_id:
            try:
                _cdp_request("GET", f"/json/close/{previous_id}")
            except httpx.HTTPError:
                pass
        return {"ok": True, "current": _resource(target, _configured_odoo_origin(db))}
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"Navigation intégrée indisponible : {exc}") from exc
