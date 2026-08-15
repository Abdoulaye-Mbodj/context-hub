from datetime import UTC, datetime
from typing import Any, Literal
import xmlrpc.client

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.connectors import _get_connector, _google_access_token, _odoo_clients
from app.crypto import decrypt_mapping
from app.database import get_db
from app.schemas import ResourceCreate

router = APIRouter(prefix="/api/v1/resources", tags=["resources"])
Source = Literal["gmail", "chat", "drive", "calendar", "odoo"]


def _google_client(db: Session) -> httpx.Client:
    connector = _get_connector(db, "google")
    if not connector or not connector.credentials_secret:
        raise HTTPException(status_code=400, detail="Connectez Google Workspace dans Paramètres")
    try:
        token = _google_access_token(connector)
        db.commit()  # Persist a refreshed access token when necessary.
        return httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=25)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Accès Google impossible : {exc}") from exc


def _header(message: dict[str, Any], name: str) -> str:
    headers = message.get("payload", {}).get("headers", [])
    return next((item.get("value", "") for item in headers if item.get("name", "").lower() == name.lower()), "")


def _timestamp(value: str | int | None) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, int) or str(value).isdigit():
            return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
        normalized = str(value)
        if len(normalized) == 10:
            normalized = f"{normalized}T00:00:00+00:00"
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except (TypeError, ValueError, OSError):
        return None


def _search_gmail(client: httpx.Client, query: str, limit: int) -> list[dict[str, Any]]:
    response = client.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/threads",
        params={"q": query or "newer_than:1y", "maxResults": min(limit, 20)},
    )
    response.raise_for_status()
    results = []
    for item in response.json().get("threads", []):
        detail = client.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{item['id']}",
            params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
        )
        detail.raise_for_status()
        thread = detail.json()
        messages = thread.get("messages", [])
        message = messages[-1] if messages else {}
        results.append(
            {
                "source": "gmail",
                "external_id": item["id"],
                "title": _header(message, "Subject") or "Conversation sans objet",
                "url": f"https://mail.google.com/mail/u/0/#all/{item['id']}",
                "resource_type": "thread",
                "excerpt": thread.get("snippet", ""),
                "author_name": _header(message, "From"),
                "occurred_at": _timestamp(message.get("internalDate")),
                "extra": {"message_count": len(messages)},
            }
        )
    return results


def _drive_query(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("'", "\\'")
    return "trashed = false" + (f" and name contains '{escaped}'" if escaped else "")


def _search_drive(client: httpx.Client, query: str, limit: int) -> list[dict[str, Any]]:
    response = client.get(
        "https://www.googleapis.com/drive/v3/files",
        params={
            "q": _drive_query(query),
            "pageSize": limit,
            "orderBy": "modifiedTime desc",
            "fields": "files(id,name,mimeType,webViewLink,modifiedTime,owners(displayName))",
        },
    )
    response.raise_for_status()
    return [
        {
            "source": "drive",
            "external_id": item["id"],
            "title": item.get("name") or "Fichier Drive",
            "url": item.get("webViewLink") or f"https://drive.google.com/open?id={item['id']}",
            "resource_type": item.get("mimeType", "file"),
            "excerpt": item.get("mimeType", ""),
            "author_name": ", ".join(owner.get("displayName", "") for owner in item.get("owners", [])),
            "occurred_at": _timestamp(item.get("modifiedTime")),
            "extra": {},
        }
        for item in response.json().get("files", [])
    ]


def _search_calendar(client: httpx.Client, query: str, limit: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"maxResults": limit, "singleEvents": "true", "orderBy": "updated"}
    if query:
        params["q"] = query
    response = client.get("https://www.googleapis.com/calendar/v3/calendars/primary/events", params=params)
    response.raise_for_status()
    results = []
    for item in response.json().get("items", []):
        start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
        organizer = item.get("organizer", {})
        results.append(
            {
                "source": "calendar",
                "external_id": item["id"],
                "title": item.get("summary") or "Événement sans titre",
                "url": item.get("htmlLink") or f"https://calendar.google.com/calendar/event?eid={item['id']}",
                "resource_type": "event",
                "excerpt": item.get("description", ""),
                "author_name": organizer.get("displayName") or organizer.get("email", ""),
                "occurred_at": _timestamp(start or item.get("updated")),
                "extra": {},
            }
        )
    return results


def _search_chat(client: httpx.Client, query: str, limit: int) -> list[dict[str, Any]]:
    response = client.get("https://chat.googleapis.com/v1/spaces", params={"pageSize": 100})
    response.raise_for_status()
    needle = query.casefold()
    spaces = [
        item for item in response.json().get("spaces", [])
        if not needle or needle in (item.get("displayName") or item.get("name", "")).casefold()
    ][:limit]
    return [
        {
            "source": "chat",
            "external_id": item["name"],
            "title": item.get("displayName") or item["name"].split("/")[-1],
            "url": f"https://chat.google.com/room/{item['name'].split('/')[-1]}",
            "resource_type": "space",
            "excerpt": "Espace Google Chat",
            "author_name": "",
            "occurred_at": None,
            "extra": {"space_type": item.get("spaceType", "")},
        }
        for item in spaces
    ]


def _search_odoo(db: Session, query: str, limit: int) -> list[dict[str, Any]]:
    connector = _get_connector(db, "odoo")
    if not connector or not connector.credentials_secret:
        raise HTTPException(status_code=400, detail="Connectez Odoo dans Paramètres")
    config = decrypt_mapping(connector.configuration_secret)
    uid = decrypt_mapping(connector.credentials_secret).get("uid")
    models_to_search = (
        ("crm.lead", "CRM"),
        ("project.project", "Projet Odoo"),
        ("project.task", "Tâche Odoo"),
        ("res.partner", "Contact Odoo"),
    )
    try:
        _, models = _odoo_clients(config)
        results = []
        per_model = max(3, min(10, limit))
        for model, label in models_to_search:
            domain = [["display_name", "ilike", query]] if query else []
            try:
                records = models.execute_kw(
                    config["database"], uid, config["api_key"], model, "search_read", [domain],
                    {"fields": ["display_name", "write_date"], "limit": per_model, "order": "write_date desc"},
                )
            except xmlrpc.client.Fault:
                continue
            results.extend(
                {
                    "source": "odoo",
                    "external_id": f"{model}:{record['id']}",
                    "title": record.get("display_name") or f"{label} #{record['id']}",
                    "url": f"{config['url'].rstrip('/')}/web#id={record['id']}&model={model}&view_type=form",
                    "resource_type": model,
                    "excerpt": label,
                    "author_name": "",
                    "occurred_at": _timestamp(record.get("write_date", "").replace(" ", "T") + "+00:00" if record.get("write_date") else None),
                    "extra": {"model": model},
                }
                for record in records
            )
        return results[:limit]
    except (OSError, xmlrpc.client.Error, KeyError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Recherche Odoo impossible : {exc}") from exc


@router.get("/search", response_model=list[ResourceCreate])
def search_resources(
    source: Source,
    q: str = Query(default="", max_length=300),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    query = q.strip()
    if source == "odoo":
        return _search_odoo(db, query, limit)
    try:
        with _google_client(db) as client:
            searchers = {
                "gmail": _search_gmail,
                "drive": _search_drive,
                "calendar": _search_calendar,
                "chat": _search_chat,
            }
            return searchers[source](client, query, limit)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        api_labels = {
            "gmail": "Gmail API",
            "drive": "Google Drive API",
            "calendar": "Google Calendar API",
            "chat": "Google Chat API",
        }
        if status == 403:
            detail = f"Accès refusé par {api_labels[source]}. Activez cette API dans le projet Google Cloud du client OAuth"
        elif status == 401:
            detail = "Session OAuth Google expirée. Reconnectez Google Workspace dans Paramètres"
        else:
            detail = "Recherche Google indisponible"
        raise HTTPException(status_code=502, detail=f"{detail} ({status})") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Recherche Google impossible : {exc}") from exc
