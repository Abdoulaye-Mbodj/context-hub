import xmlrpc.client

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ResourceCreate, SourceName
from app.source_apps import (
    _calendar_list,
    _chat_detail,
    _chat_spaces,
    _drive_list,
    _gmail_list,
    _google_client,
    _odoo_list,
    _raise_google,
)

router = APIRouter(prefix="/api/v1/resources", tags=["resources"])


@router.get("/search", response_model=list[ResourceCreate])
def search_resources(
    source: SourceName,
    q: str = Query(default="", max_length=300),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    query = q.strip()
    if source == "odoo":
        try:
            return [item["resource"] for item in _odoo_list(db, query, limit)]
        except (OSError, xmlrpc.client.Error, KeyError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"Recherche Odoo impossible : {exc}") from exc
    try:
        with _google_client(db) as client:
            if source == "gmail":
                items = _gmail_list(client, query, limit)
            elif source == "drive":
                items = _drive_list(client, query, limit, "all")
            elif source == "calendar":
                items = _calendar_list(client, query, limit)
            else:
                # Chat full-text search is still Developer Preview. Search
                # visible messages space by space and never return a space as
                # an attachable resource.
                items = []
                needle = query.casefold()
                for space in _chat_spaces(client, "", 20):
                    detail = _chat_detail(client, space["id"], "space")
                    for message in detail.get("children", []):
                        if not needle or needle in message.get("body", "").casefold():
                            items.append(message)
                            if len(items) >= limit:
                                break
                    if len(items) >= limit:
                        break
            return [item["resource"] for item in items if item.get("resource")][:limit]
    except httpx.HTTPStatusError as exc:
        _raise_google(exc, source)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Recherche {source} impossible : {exc}") from exc
