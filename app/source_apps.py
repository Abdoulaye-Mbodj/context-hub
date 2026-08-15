import base64
import re
import xmlrpc.client
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from html import unescape
from typing import Any, Literal
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connectors import _get_connector, _google_access_token, _odoo_clients
from app.crypto import decrypt_mapping
from app.database import get_db
from app.schemas import ResourceCreate

router = APIRouter(prefix="/api/v1/apps", tags=["source-applications"])
Source = Literal["gmail", "chat", "drive", "calendar", "odoo"]

ODOO_MODELS = {
    "crm.lead": ("CRM", ["name", "partner_name", "email_from", "phone", "description", "stage_id", "user_id", "expected_revenue", "probability", "write_date"]),
    "res.partner": ("Contact", ["name", "email", "phone", "mobile", "website", "function", "city", "country_id", "comment", "write_date"]),
    "project.project": ("Projet Odoo", ["name", "partner_id", "user_id", "description", "date_start", "date", "write_date"]),
    "project.task": ("Tâche Odoo", ["name", "project_id", "partner_id", "user_ids", "stage_id", "date_deadline", "description", "write_date"]),
}


def _google_client(db: Session) -> httpx.Client:
    connector = _get_connector(db, "google")
    if not connector or not connector.credentials_secret:
        raise HTTPException(status_code=400, detail="Connectez Google Workspace dans Paramètres")
    try:
        token = _google_access_token(connector)
        db.commit()
        return httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=30)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Accès Google impossible : {exc}") from exc


def _raise_google(exc: httpx.HTTPStatusError, source: str) -> None:
    status_code = exc.response.status_code
    try:
        message = exc.response.json().get("error", {}).get("message", "")
    except ValueError:
        message = ""
    if status_code == 403:
        detail = f"Accès {source} refusé. Activez l’API et reconnectez Google dans Paramètres"
    elif status_code == 401:
        detail = "Autorisation Google expirée. Reconnectez Google dans Paramètres"
    else:
        detail = message or f"L’API {source} ne répond pas"
    raise HTTPException(status_code=502, detail=detail) from exc


def _internal_url(source: str, item_id: str, kind: str) -> str:
    root = get_settings().app_public_url.rstrip("/")
    return f"{root}/?app={source}&kind={quote(kind)}&item={quote(item_id)}"


def _resource(
    source: Source,
    item_id: str,
    title: str,
    kind: str,
    excerpt: str = "",
    author: str = "",
    occurred_at: datetime | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return ResourceCreate(
        source=source,
        external_id=item_id,
        title=title[:300] or "Élément sans titre",
        url=_internal_url(source, item_id, kind),
        resource_type=kind,
        excerpt=excerpt[:2000],
        author_name=author[:160],
        occurred_at=occurred_at,
        extra=extra or {},
    ).model_dump(mode="json")


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


def _gmail_header(message: dict[str, Any], name: str) -> str:
    headers = message.get("payload", {}).get("headers", [])
    return next((item.get("value", "") for item in headers if item.get("name", "").lower() == name.lower()), "")


def _decode_body(data: str) -> str:
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
    except (ValueError, UnicodeError):
        return ""


def _strip_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", value)
    value = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", value)
    value = re.sub(r"(?s)<[^>]+>", "", value)
    return re.sub(r"\n{3,}", "\n\n", unescape(value)).strip()


def _gmail_body(payload: dict[str, Any]) -> str:
    plain: list[str] = []
    html: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data", "")
        if data and mime == "text/plain":
            plain.append(_decode_body(data))
        elif data and mime == "text/html":
            html.append(_strip_html(_decode_body(data)))
        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    return "\n\n".join(item.strip() for item in (plain or html) if item.strip())


def _gmail_message(message: dict[str, Any]) -> dict[str, Any]:
    title = _gmail_header(message, "Subject") or "Message sans objet"
    sender = _gmail_header(message, "From")
    occurred_at = _timestamp(message.get("internalDate"))
    item_id = message["id"]
    return {
        "id": item_id,
        "thread_id": message.get("threadId", ""),
        "kind": "message",
        "title": title,
        "subtitle": sender,
        "sender": sender,
        "to": _gmail_header(message, "To"),
        "cc": _gmail_header(message, "Cc"),
        "date": _gmail_header(message, "Date"),
        "timestamp": occurred_at.isoformat() if occurred_at else None,
        "snippet": message.get("snippet", ""),
        "body": _gmail_body(message.get("payload", {})),
        "labels": message.get("labelIds", []),
        "resource": _resource("gmail", item_id, title, "message", message.get("snippet", ""), sender, occurred_at),
    }


def _gmail_list(client: httpx.Client, query: str, limit: int) -> list[dict[str, Any]]:
    response = client.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/threads",
        params={"q": query or "in:anywhere", "maxResults": min(limit, 30)},
    )
    response.raise_for_status()
    items = []
    for row in response.json().get("threads", []):
        detail = client.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{row['id']}",
            params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
        )
        detail.raise_for_status()
        thread = detail.json()
        messages = thread.get("messages", [])
        message = messages[-1] if messages else {}
        title = _gmail_header(message, "Subject") or "Conversation sans objet"
        sender = _gmail_header(message, "From")
        occurred_at = _timestamp(message.get("internalDate"))
        items.append(
            {
                "id": row["id"],
                "kind": "thread",
                "title": title,
                "subtitle": sender,
                "snippet": thread.get("snippet", ""),
                "timestamp": occurred_at.isoformat() if occurred_at else None,
                "count": len(messages),
                "labels": message.get("labelIds", []),
                "resource": _resource("gmail", row["id"], title, "thread", thread.get("snippet", ""), sender, occurred_at, {"message_count": len(messages)}),
            }
        )
    return items


def _gmail_detail(client: httpx.Client, item_id: str, kind: str) -> dict[str, Any]:
    if kind == "message":
        response = client.get(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{item_id}", params={"format": "full"})
        response.raise_for_status()
        return _gmail_message(response.json())
    response = client.get(f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{item_id}", params={"format": "full"})
    response.raise_for_status()
    thread = response.json()
    messages = [_gmail_message(message) for message in thread.get("messages", [])]
    latest = messages[-1] if messages else {"title": "Conversation sans objet", "snippet": "", "sender": "", "timestamp": None}
    return {
        "id": item_id,
        "kind": "thread",
        "title": latest["title"],
        "subtitle": f"{len(messages)} message(s)",
        "snippet": latest.get("snippet", ""),
        "timestamp": latest.get("timestamp"),
        "children": messages,
        "resource": _resource(
            "gmail", item_id, latest["title"], "thread", latest.get("snippet", ""), latest.get("sender", ""),
            _timestamp(latest.get("timestamp")), {"message_count": len(messages)},
        ),
    }


def _chat_spaces(client: httpx.Client, query: str, limit: int) -> list[dict[str, Any]]:
    response = client.get("https://chat.googleapis.com/v1/spaces", params={"pageSize": min(limit, 100)})
    response.raise_for_status()
    needle = query.casefold()
    return [
        {
            "id": item["name"],
            "kind": "space",
            "title": item.get("displayName") or item["name"].split("/")[-1],
            "subtitle": item.get("spaceType", "Espace Chat"),
            "snippet": "Ouvrez cet espace pour consulter ses messages.",
            "timestamp": None,
        }
        for item in response.json().get("spaces", [])
        if not needle or needle in (item.get("displayName") or item.get("name", "")).casefold()
    ][:limit]


def _chat_message(item: dict[str, Any], space_title: str = "Google Chat") -> dict[str, Any]:
    title = (item.get("text") or "Message Google Chat").strip()
    sender = item.get("sender", {}).get("displayName", "")
    occurred_at = _timestamp(item.get("createTime"))
    return {
        "id": item["name"],
        "kind": "message",
        "title": title[:140],
        "subtitle": sender or space_title,
        "snippet": title,
        "body": title,
        "sender": sender,
        "timestamp": occurred_at.isoformat() if occurred_at else None,
        "thread": item.get("thread", {}).get("name", ""),
        "resource": _resource("chat", item["name"], title[:300], "message", title, sender, occurred_at, {"space": space_title}),
    }


def _chat_detail(client: httpx.Client, item_id: str, kind: str) -> dict[str, Any]:
    if kind == "message":
        response = client.get(f"https://chat.googleapis.com/v1/{item_id}")
        response.raise_for_status()
        return _chat_message(response.json())
    space_response = client.get(f"https://chat.googleapis.com/v1/{item_id}")
    space_response.raise_for_status()
    space = space_response.json()
    title = space.get("displayName") or item_id.split("/")[-1]
    response = client.get(
        f"https://chat.googleapis.com/v1/{item_id}/messages",
        params={"pageSize": 100, "orderBy": "DESC", "showDeleted": "false"},
    )
    response.raise_for_status()
    messages = [_chat_message(message, title) for message in response.json().get("messages", [])]
    return {
        "id": item_id,
        "kind": "space",
        "title": title,
        "subtitle": f"{len(messages)} message(s)",
        "snippet": "Sélectionnez un message pour l’ouvrir ou le rattacher.",
        "children": messages,
    }


def _drive_query(query: str, view: str) -> str:
    parts = ["trashed = false"]
    if view == "shared":
        parts.append("sharedWithMe")
    if query:
        escaped = query.replace("\\", "\\\\").replace("'", "\\'")
        parts.append(f"name contains '{escaped}'")
    return " and ".join(parts)


DRIVE_FIELDS = "id,name,mimeType,modifiedTime,createdTime,shared,sharedWithMeTime,driveId,parents,owners(displayName,emailAddress),capabilities(canEdit,canDelete,canTrash,canRename,canMoveItemWithinDrive),size,description,starred,trashed"


def _drive_item(item: dict[str, Any]) -> dict[str, Any]:
    occurred_at = _timestamp(item.get("modifiedTime"))
    is_folder = item.get("mimeType") == "application/vnd.google-apps.folder"
    owner = ", ".join(owner.get("displayName", "") for owner in item.get("owners", []))
    location = "Drive partagé" if item.get("driveId") else ("Partagé avec moi" if item.get("sharedWithMeTime") else "Mon Drive")
    return {
        "id": item["id"],
        "kind": "folder" if is_folder else "file",
        "title": item.get("name") or "Élément Drive",
        "subtitle": f"{location} · {owner}".strip(" ·"),
        "snippet": item.get("description", "") or item.get("mimeType", ""),
        "timestamp": occurred_at.isoformat() if occurred_at else None,
        "mime_type": item.get("mimeType", ""),
        "shared": bool(item.get("shared")),
        "shared_with_me": bool(item.get("sharedWithMeTime")),
        "drive_id": item.get("driveId", ""),
        "capabilities": item.get("capabilities", {}),
        "starred": bool(item.get("starred")),
        "resource": _resource("drive", item["id"], item.get("name", "Élément Drive"), "folder" if is_folder else "file", item.get("description", "") or location, owner, occurred_at, {"mime_type": item.get("mimeType", ""), "drive_id": item.get("driveId", "")}),
    }


def _drive_list(client: httpx.Client, query: str, limit: int, view: str) -> list[dict[str, Any]]:
    response = client.get(
        "https://www.googleapis.com/drive/v3/files",
        params={
            "q": _drive_query(query, view),
            "pageSize": min(limit, 100),
            "orderBy": "modifiedTime desc",
            "corpora": "user",
            "includeItemsFromAllDrives": "true",
            "supportsAllDrives": "true",
            "fields": f"files({DRIVE_FIELDS}),incompleteSearch",
        },
    )
    response.raise_for_status()
    return [_drive_item(item) for item in response.json().get("files", [])]


def _drive_detail(client: httpx.Client, item_id: str) -> dict[str, Any]:
    response = client.get(
        f"https://www.googleapis.com/drive/v3/files/{item_id}",
        params={"supportsAllDrives": "true", "fields": DRIVE_FIELDS},
    )
    response.raise_for_status()
    item = _drive_item(response.json())
    item["body"] = item["snippet"]
    return item


def _calendar_item(item: dict[str, Any]) -> dict[str, Any]:
    start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
    occurred_at = _timestamp(start)
    organizer = item.get("organizer", {})
    title = item.get("summary") or "Événement sans titre"
    return {
        "id": item["id"],
        "kind": "event",
        "title": title,
        "subtitle": start or "Date non définie",
        "snippet": item.get("description", "") or item.get("location", ""),
        "body": item.get("description", ""),
        "location": item.get("location", ""),
        "start": item.get("start", {}),
        "end": item.get("end", {}),
        "attendees": item.get("attendees", []),
        "organizer": organizer,
        "timestamp": occurred_at.isoformat() if occurred_at else None,
        "status": item.get("status", ""),
        "resource": _resource("calendar", item["id"], title, "event", item.get("description", "") or item.get("location", ""), organizer.get("displayName") or organizer.get("email", ""), occurred_at),
    }


def _calendar_list(client: httpx.Client, query: str, limit: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "maxResults": min(limit, 100),
        "singleEvents": "true",
        "orderBy": "startTime",
        "timeMin": (datetime.now(UTC) - timedelta(days=90)).isoformat(),
    }
    if query:
        params["q"] = query
    response = client.get("https://www.googleapis.com/calendar/v3/calendars/primary/events", params=params)
    response.raise_for_status()
    return [_calendar_item(item) for item in response.json().get("items", [])]


def _calendar_detail(client: httpx.Client, item_id: str) -> dict[str, Any]:
    response = client.get(f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{item_id}")
    response.raise_for_status()
    return _calendar_item(response.json())


def _odoo_connection(db: Session) -> tuple[dict[str, Any], Any, int]:
    connector = _get_connector(db, "odoo")
    if not connector or not connector.credentials_secret:
        raise HTTPException(status_code=400, detail="Connectez Odoo dans Paramètres")
    config = decrypt_mapping(connector.configuration_secret)
    uid = decrypt_mapping(connector.credentials_secret).get("uid")
    _, models = _odoo_clients(config)
    return config, models, uid


def _odoo_value(value: Any) -> Any:
    if isinstance(value, tuple | list) and len(value) == 2 and isinstance(value[0], int):
        return value[1]
    return value


def _odoo_item(model: str, label: str, record: dict[str, Any]) -> dict[str, Any]:
    title = record.get("display_name") or record.get("name") or f"{label} #{record['id']}"
    occurred_at = _timestamp(str(record.get("write_date", "")).replace(" ", "T") + "+00:00" if record.get("write_date") else None)
    return {
        "id": f"{model}:{record['id']}",
        "record_id": record["id"],
        "model": model,
        "kind": model,
        "title": title,
        "subtitle": label,
        "snippet": " · ".join(str(_odoo_value(value)) for key, value in record.items() if key not in {"id", "display_name", "name", "write_date"} and value not in (False, None, ""))[:300],
        "timestamp": occurred_at.isoformat() if occurred_at else None,
        "fields": {key: _odoo_value(value) for key, value in record.items() if key != "id"},
        "resource": _resource("odoo", f"{model}:{record['id']}", title, model, label, "", occurred_at, {"model": model, "record_id": record["id"]}),
    }


def _odoo_list(db: Session, query: str, limit: int) -> list[dict[str, Any]]:
    config, models, uid = _odoo_connection(db)
    results = []
    per_model = max(3, min(15, limit))
    for model, (label, _fields) in ODOO_MODELS.items():
        domain = [["display_name", "ilike", query]] if query else []
        try:
            records = models.execute_kw(
                config["database"], uid, config["api_key"], model, "search_read", [domain],
                {"fields": ["display_name", "write_date"], "limit": per_model, "order": "write_date desc"},
            )
        except xmlrpc.client.Fault:
            continue
        results.extend(_odoo_item(model, label, record) for record in records)
    return sorted(results, key=lambda item: item.get("timestamp") or "", reverse=True)[:limit]


def _odoo_detail(db: Session, item_id: str) -> dict[str, Any]:
    model, raw_id = item_id.rsplit(":", 1)
    if model not in ODOO_MODELS:
        raise HTTPException(status_code=400, detail="Modèle Odoo non pris en charge")
    label, fields = ODOO_MODELS[model]
    config, models, uid = _odoo_connection(db)
    try:
        records = models.execute_kw(config["database"], uid, config["api_key"], model, "read", [[int(raw_id)]], {"fields": fields})
    except xmlrpc.client.Fault:
        records = models.execute_kw(config["database"], uid, config["api_key"], model, "read", [[int(raw_id)]], {"fields": ["display_name", "write_date"]})
    if not records:
        raise HTTPException(status_code=404, detail="Enregistrement Odoo introuvable")
    return _odoo_item(model, label, records[0])


@router.get("/{source}/items")
def source_items(
    source: Source,
    q: str = Query(default="", max_length=300),
    limit: int = Query(default=30, ge=1, le=100),
    view: str = Query(default="all", pattern="^(all|shared)$"),
    db: Session = Depends(get_db),
):
    query = q.strip()
    if source == "odoo":
        try:
            return {"items": _odoo_list(db, query, limit)}
        except (OSError, xmlrpc.client.Error, KeyError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"Odoo ne répond pas : {exc}") from exc
    try:
        with _google_client(db) as client:
            if source == "gmail":
                items = _gmail_list(client, query, limit)
            elif source == "chat":
                items = _chat_spaces(client, query, limit)
            elif source == "drive":
                items = _drive_list(client, query, limit, view)
            else:
                items = _calendar_list(client, query, limit)
            return {"items": items}
    except httpx.HTTPStatusError as exc:
        _raise_google(exc, source)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"{source} ne répond pas : {exc}") from exc


@router.get("/{source}/item")
def source_item_detail(
    source: Source,
    item_id: str = Query(min_length=1, max_length=700),
    kind: str = Query(default="item", max_length=80),
    db: Session = Depends(get_db),
):
    if source == "odoo":
        try:
            return _odoo_detail(db, item_id)
        except (OSError, xmlrpc.client.Error, KeyError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"Odoo ne répond pas : {exc}") from exc
    try:
        with _google_client(db) as client:
            if source == "gmail":
                return _gmail_detail(client, item_id, kind)
            if source == "chat":
                return _chat_detail(client, item_id, kind)
            if source == "drive":
                return _drive_detail(client, item_id)
            return _calendar_detail(client, item_id)
    except httpx.HTTPStatusError as exc:
        _raise_google(exc, source)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"{source} ne répond pas : {exc}") from exc


@router.post("/{source}/items", status_code=status.HTTP_201_CREATED)
def source_item_create(source: Source, data: dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    if source == "odoo":
        model = data.pop("model", "crm.lead")
        if model not in ODOO_MODELS:
            raise HTTPException(status_code=400, detail="Modèle Odoo non pris en charge")
        if model == "res.partner" and "description" in data:
            data["comment"] = data.pop("description")
        config, models, uid = _odoo_connection(db)
        try:
            record_id = models.execute_kw(config["database"], uid, config["api_key"], model, "create", [data])
            return _odoo_detail(db, f"{model}:{record_id}")
        except (OSError, xmlrpc.client.Error, KeyError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"Création Odoo impossible : {exc}") from exc
    try:
        with _google_client(db) as client:
            if source == "gmail":
                message = EmailMessage()
                message["To"] = data.get("to", "")
                if data.get("cc"):
                    message["Cc"] = data["cc"]
                if data.get("bcc"):
                    message["Bcc"] = data["bcc"]
                message["Subject"] = data.get("subject", "")
                message.set_content(data.get("body", ""))
                raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
                response = client.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", json={"raw": raw})
                response.raise_for_status()
                return _gmail_detail(client, response.json()["id"], "message")
            if source == "chat":
                parent = data.get("parent", "")
                response = client.post(f"https://chat.googleapis.com/v1/{parent}/messages", json={"text": data.get("text", "")})
                response.raise_for_status()
                return _chat_message(response.json())
            if source == "drive":
                kinds = {
                    "folder": "application/vnd.google-apps.folder",
                    "doc": "application/vnd.google-apps.document",
                    "sheet": "application/vnd.google-apps.spreadsheet",
                    "slide": "application/vnd.google-apps.presentation",
                }
                metadata: dict[str, Any] = {"name": data.get("name", "Sans titre"), "mimeType": kinds.get(data.get("kind"), kinds["folder"])}
                if data.get("parent"):
                    metadata["parents"] = [data["parent"]]
                response = client.post(
                    "https://www.googleapis.com/drive/v3/files",
                    params={"supportsAllDrives": "true", "fields": DRIVE_FIELDS},
                    json=metadata,
                )
                response.raise_for_status()
                return _drive_item(response.json())
            payload = {
                "summary": data.get("title", "Nouvel événement"),
                "description": data.get("description", ""),
                "location": data.get("location", ""),
                "start": {"dateTime": data["start"]},
                "end": {"dateTime": data["end"]},
            }
            response = client.post("https://www.googleapis.com/calendar/v3/calendars/primary/events", json=payload)
            response.raise_for_status()
            return _calendar_item(response.json())
    except httpx.HTTPStatusError as exc:
        _raise_google(exc, source)


@router.patch("/{source}/item")
def source_item_update(
    source: Source,
    data: dict[str, Any] = Body(...),
    item_id: str = Query(min_length=1, max_length=700),
    kind: str = Query(default="item", max_length=80),
    db: Session = Depends(get_db),
):
    if source == "odoo":
        model, raw_id = item_id.rsplit(":", 1)
        if model not in ODOO_MODELS:
            raise HTTPException(status_code=400, detail="Modèle Odoo non pris en charge")
        if model == "res.partner" and "description" in data:
            data["comment"] = data.pop("description")
        config, models, uid = _odoo_connection(db)
        try:
            models.execute_kw(config["database"], uid, config["api_key"], model, "write", [[int(raw_id)], data])
            return _odoo_detail(db, item_id)
        except (OSError, xmlrpc.client.Error, KeyError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"Mise à jour Odoo impossible : {exc}") from exc
    try:
        with _google_client(db) as client:
            if source == "gmail":
                endpoint = "threads" if kind == "thread" else "messages"
                action = data.get("action", "read")
                mutations = {
                    "read": {"removeLabelIds": ["UNREAD"]},
                    "unread": {"addLabelIds": ["UNREAD"]},
                    "star": {"addLabelIds": ["STARRED"]},
                    "unstar": {"removeLabelIds": ["STARRED"]},
                    "archive": {"removeLabelIds": ["INBOX"]},
                }
                if action not in mutations:
                    raise HTTPException(status_code=400, detail="Action Gmail inconnue")
                response = client.post(f"https://gmail.googleapis.com/gmail/v1/users/me/{endpoint}/{item_id}/modify", json=mutations[action])
                response.raise_for_status()
                return _gmail_detail(client, item_id, kind)
            if source == "chat":
                response = client.patch(f"https://chat.googleapis.com/v1/{item_id}", params={"updateMask": "text"}, json={"text": data.get("text", "")})
                response.raise_for_status()
                return _chat_message(response.json())
            if source == "drive":
                allowed = {key: data[key] for key in ("name", "description", "starred", "trashed") if key in data}
                response = client.patch(
                    f"https://www.googleapis.com/drive/v3/files/{item_id}",
                    params={"supportsAllDrives": "true", "fields": DRIVE_FIELDS},
                    json=allowed,
                )
                response.raise_for_status()
                return _drive_item(response.json())
            current = client.get(f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{item_id}")
            current.raise_for_status()
            event = current.json()
            if "title" in data:
                event["summary"] = data["title"]
            for field in ("description", "location"):
                if field in data:
                    event[field] = data[field]
            if data.get("start"):
                event["start"] = {"dateTime": data["start"]}
            if data.get("end"):
                event["end"] = {"dateTime": data["end"]}
            response = client.put(f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{item_id}", json=event)
            response.raise_for_status()
            return _calendar_item(response.json())
    except httpx.HTTPStatusError as exc:
        _raise_google(exc, source)


@router.delete("/{source}/item", status_code=status.HTTP_204_NO_CONTENT)
def source_item_delete(
    source: Source,
    item_id: str = Query(min_length=1, max_length=700),
    kind: str = Query(default="item", max_length=80),
    db: Session = Depends(get_db),
):
    if source == "odoo":
        model, raw_id = item_id.rsplit(":", 1)
        if model not in ODOO_MODELS:
            raise HTTPException(status_code=400, detail="Modèle Odoo non pris en charge")
        config, models, uid = _odoo_connection(db)
        try:
            models.execute_kw(config["database"], uid, config["api_key"], model, "unlink", [[int(raw_id)]])
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except (OSError, xmlrpc.client.Error, KeyError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"Suppression Odoo impossible : {exc}") from exc
    try:
        with _google_client(db) as client:
            if source == "gmail":
                endpoint = "threads" if kind == "thread" else "messages"
                response = client.post(f"https://gmail.googleapis.com/gmail/v1/users/me/{endpoint}/{item_id}/trash")
            elif source == "chat":
                response = client.delete(f"https://chat.googleapis.com/v1/{item_id}")
            elif source == "drive":
                response = client.patch(
                    f"https://www.googleapis.com/drive/v3/files/{item_id}",
                    params={"supportsAllDrives": "true"},
                    json={"trashed": True},
                )
            else:
                response = client.delete(f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{item_id}")
            response.raise_for_status()
            return Response(status_code=status.HTTP_204_NO_CONTENT)
    except httpx.HTTPStatusError as exc:
        _raise_google(exc, source)
