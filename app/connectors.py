import hmac
import secrets
import xmlrpc.client
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import decrypt_mapping, encrypt_mapping
from app.database import get_db
from app.models import Connector
from app.schemas import ConnectorRead, GoogleConnectorConfigure, OdooConnectorConfigure

router = APIRouter(prefix="/api/v1/connectors", tags=["connectors"])

GOOGLE_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/chat.spaces.readonly",
    "https://www.googleapis.com/auth/chat.messages",
]


def _get_connector(db: Session, provider: str, create: bool = False) -> Connector | None:
    connector = db.get(Connector, provider)
    if not connector and create:
        connector = Connector(provider=provider)
        db.add(connector)
        db.flush()
    return connector


def _safe_configuration(connector: Connector) -> dict[str, Any]:
    try:
        config = decrypt_mapping(connector.configuration_secret)
    except ValueError:
        return {}
    if connector.provider == "google":
        client_id = config.get("client_id", "")
        credentials = decrypt_mapping(connector.credentials_secret) if connector.credentials_secret else {}
        granted_scopes = set(credentials.get("scope", "").split())
        return {
            "client_id": client_id,
            "client_id_hint": f"{client_id[:10]}…{client_id[-12:]}" if len(client_id) > 24 else client_id,
            "redirect_uri": f"{get_settings().app_public_url}/api/v1/connectors/google/callback",
            "scope_upgrade_required": bool(connector.credentials_secret and not set(GOOGLE_SCOPES).issubset(granted_scopes)),
        }
    return {
        "url": config.get("url", ""),
        "database": config.get("database", ""),
        "username": config.get("username", ""),
    }


def _serialize(connector: Connector | None, provider: str) -> ConnectorRead:
    if not connector:
        return ConnectorRead(
            provider=provider,
            status="disconnected",
            configured=False,
            external_account="",
            stats={},
            last_error="",
            last_sync_at=None,
            updated_at=None,
            configuration={},
        )
    return ConnectorRead(
        provider=provider,
        status=connector.status,
        configured=bool(connector.configuration_secret),
        external_account=connector.external_account,
        stats=connector.stats or {},
        last_error=connector.last_error,
        last_sync_at=connector.last_sync_at,
        updated_at=connector.updated_at,
        configuration=_safe_configuration(connector),
    )


@router.get("", response_model=list[ConnectorRead])
def connectors_list(db: Session = Depends(get_db)):
    return [_serialize(_get_connector(db, provider), provider) for provider in ("google", "odoo")]


@router.post("/google/configure", response_model=ConnectorRead)
def google_configure(payload: GoogleConnectorConfigure, db: Session = Depends(get_db)):
    connector = _get_connector(db, "google", create=True)
    assert connector is not None
    connector.configuration_secret = encrypt_mapping(payload.model_dump())
    connector.credentials_secret = ""
    connector.status = "configured"
    connector.external_account = ""
    connector.stats = {}
    connector.last_error = ""
    connector.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(connector)
    return _serialize(connector, "google")


@router.get("/google/authorize")
def google_authorize(db: Session = Depends(get_db)):
    connector = _get_connector(db, "google")
    if not connector or not connector.configuration_secret:
        raise HTTPException(status_code=400, detail="Configurez d’abord le client OAuth Google")
    config = decrypt_mapping(connector.configuration_secret)
    oauth_state = secrets.token_urlsafe(32)
    config["oauth_state"] = oauth_state
    config["oauth_state_created_at"] = datetime.now(UTC).isoformat()
    connector.configuration_secret = encrypt_mapping(config)
    db.commit()
    params = {
        "client_id": config["client_id"],
        "redirect_uri": f"{get_settings().app_public_url}/api/v1/connectors/google/callback",
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": oauth_state,
    }
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}")


def _oauth_result_page(success: bool, message: str) -> HTMLResponse:
    safe_message = message.replace("<", "&lt;").replace(">", "&gt;")
    status_text = "Connexion réussie" if success else "Connexion impossible"
    script_value = "true" if success else "false"
    return HTMLResponse(
        f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>{status_text}</title>
        <style>body{{font-family:system-ui;display:grid;place-items:center;min-height:100vh;margin:0;background:#f6f7fb;color:#182038}}main{{max-width:420px;padding:32px;text-align:center;background:white;border-radius:18px;box-shadow:0 20px 60px #18203822}}h1{{font-size:22px}}p{{color:#6f7890;line-height:1.6}}</style></head>
        <body><main><h1>{status_text}</h1><p>{safe_message}</p><p>Cette fenêtre va se fermer.</p></main>
        <script>window.opener?.postMessage({{type:'context-hub-oauth',success:{script_value}}}, window.location.origin); setTimeout(() => window.close(), 900);</script></body></html>"""
    )


@router.get("/google/callback", response_class=HTMLResponse)
def google_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    connector = _get_connector(db, "google")
    if not connector:
        return _oauth_result_page(False, "Configuration Google introuvable.")
    config = decrypt_mapping(connector.configuration_secret)
    created_at = config.get("oauth_state_created_at")
    state_valid = bool(state and config.get("oauth_state") and hmac.compare_digest(state, config["oauth_state"]))
    if created_at:
        state_valid = state_valid and datetime.fromisoformat(created_at) > datetime.now(UTC) - timedelta(minutes=15)
    if error or not code or not state_valid:
        connector.status = "error"
        connector.last_error = error or "Réponse OAuth invalide ou expirée"
        db.commit()
        return _oauth_result_page(False, connector.last_error)
    try:
        response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "redirect_uri": f"{get_settings().app_public_url}/api/v1/connectors/google/callback",
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
        response.raise_for_status()
        tokens = response.json()
        previous = decrypt_mapping(connector.credentials_secret) if connector.credentials_secret else {}
        if "refresh_token" not in tokens and previous.get("refresh_token"):
            tokens["refresh_token"] = previous["refresh_token"]
        tokens["expires_at"] = (datetime.now(UTC) + timedelta(seconds=tokens.get("expires_in", 3600))).isoformat()
        user = httpx.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            timeout=15,
        )
        user.raise_for_status()
        connector.credentials_secret = encrypt_mapping(tokens)
        connector.external_account = user.json().get("email", "Compte Google")
        connector.status = "connected"
        connector.last_error = ""
        connector.updated_at = datetime.now(UTC)
        db.commit()
        return _oauth_result_page(True, f"{connector.external_account} est maintenant connecté.")
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        connector.status = "error"
        connector.last_error = f"Échec de l’échange OAuth : {exc}"
        db.commit()
        return _oauth_result_page(False, connector.last_error)


def _google_access_token(connector: Connector) -> str:
    config = decrypt_mapping(connector.configuration_secret)
    credentials = decrypt_mapping(connector.credentials_secret)
    expires_at = datetime.fromisoformat(credentials.get("expires_at", "1970-01-01T00:00:00+00:00"))
    if expires_at > datetime.now(UTC) + timedelta(minutes=2):
        return credentials["access_token"]
    refresh_token = credentials.get("refresh_token")
    if not refresh_token:
        raise ValueError("Aucun refresh token Google disponible")
    response = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    response.raise_for_status()
    refreshed = response.json()
    credentials.update(refreshed)
    credentials["expires_at"] = (datetime.now(UTC) + timedelta(seconds=refreshed.get("expires_in", 3600))).isoformat()
    connector.credentials_secret = encrypt_mapping(credentials)
    return credentials["access_token"]


@router.post("/google/sync", response_model=ConnectorRead)
def google_sync(db: Session = Depends(get_db)):
    connector = _get_connector(db, "google")
    if not connector or not connector.credentials_secret:
        raise HTTPException(status_code=400, detail="Connectez d’abord le compte Google")
    try:
        token = _google_access_token(connector)
        headers = {"Authorization": f"Bearer {token}"}
        with httpx.Client(headers=headers, timeout=20) as client:
            gmail = client.get("https://gmail.googleapis.com/gmail/v1/users/me/threads", params={"maxResults": 1})
            gmail.raise_for_status()
            drive = client.get(
                "https://www.googleapis.com/drive/v3/files",
                params={"pageSize": 100, "fields": "files(id)"},
            )
            drive.raise_for_status()
            calendar = client.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                params={
                    "maxResults": 50,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "timeMin": datetime.now(UTC).isoformat(),
                },
            )
            calendar.raise_for_status()
            chat = client.get("https://chat.googleapis.com/v1/spaces", params={"pageSize": 100})
            chat.raise_for_status()
        connector.stats = {
            "gmail_threads": gmail.json().get("resultSizeEstimate", 0),
            "drive_files_sample": len(drive.json().get("files", [])),
            "upcoming_events": len(calendar.json().get("items", [])),
            "chat_spaces": len(chat.json().get("spaces", [])),
        }
        connector.status = "connected"
        connector.last_sync_at = datetime.now(UTC)
        connector.last_error = ""
        db.commit()
        db.refresh(connector)
        return _serialize(connector, "google")
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        connector.status = "error"
        connector.last_error = f"Synchronisation Google impossible : {exc}"
        db.commit()
        raise HTTPException(status_code=502, detail=connector.last_error) from exc


def _odoo_clients(config: dict[str, Any]):
    url = config["url"].rstrip("/")
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", allow_none=True)
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", allow_none=True)
    return common, models


@router.post("/odoo/configure", response_model=ConnectorRead)
def odoo_configure(payload: OdooConnectorConfigure, db: Session = Depends(get_db)):
    connector = _get_connector(db, "odoo", create=True)
    assert connector is not None
    config = payload.model_dump()
    config["url"] = str(config["url"])
    try:
        common, models = _odoo_clients(config)
        version = common.version()
        uid = common.authenticate(config["database"], config["username"], config["api_key"], {})
        if not uid:
            raise ValueError("Identifiants Odoo refusés")
        user = models.execute_kw(
            config["database"], uid, config["api_key"], "res.users", "read", [[uid]], {"fields": ["name", "login"]}
        )[0]
        connector.configuration_secret = encrypt_mapping(config)
        connector.credentials_secret = encrypt_mapping({"uid": uid})
        connector.external_account = user.get("login") or user.get("name", "Compte Odoo")
        connector.stats = {"server_version": version.get("server_version", ""), "user_name": user.get("name", "")}
        connector.status = "connected"
        connector.last_error = ""
        connector.last_sync_at = datetime.now(UTC)
        connector.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(connector)
        return _serialize(connector, "odoo")
    except (OSError, xmlrpc.client.Error, ValueError) as exc:
        connector.status = "error"
        connector.last_error = f"Connexion Odoo impossible : {exc}"
        db.commit()
        raise HTTPException(status_code=502, detail=connector.last_error) from exc


@router.post("/odoo/sync", response_model=ConnectorRead)
def odoo_sync(db: Session = Depends(get_db)):
    connector = _get_connector(db, "odoo")
    if not connector or not connector.credentials_secret:
        raise HTTPException(status_code=400, detail="Configurez d’abord Odoo")
    config = decrypt_mapping(connector.configuration_secret)
    uid = decrypt_mapping(connector.credentials_secret)["uid"]
    try:
        _, models = _odoo_clients(config)
        counts = {}
        for key, model in (("contacts", "res.partner"), ("opportunities", "crm.lead"), ("projects", "project.project")):
            counts[key] = models.execute_kw(
                config["database"], uid, config["api_key"], model, "search_count", [[]]
            )
        connector.stats = {**(connector.stats or {}), **counts}
        connector.status = "connected"
        connector.last_sync_at = datetime.now(UTC)
        connector.last_error = ""
        db.commit()
        db.refresh(connector)
        return _serialize(connector, "odoo")
    except (OSError, xmlrpc.client.Error, ValueError) as exc:
        connector.status = "error"
        connector.last_error = f"Synchronisation Odoo impossible : {exc}"
        db.commit()
        raise HTTPException(status_code=502, detail=connector.last_error) from exc


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
def connector_disconnect(provider: str, db: Session = Depends(get_db)):
    if provider not in {"google", "odoo"}:
        raise HTTPException(status_code=404, detail="Connecteur inconnu")
    connector = _get_connector(db, provider)
    if connector:
        db.delete(connector)
        db.commit()
