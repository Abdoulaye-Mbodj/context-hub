import json
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.database import get_db
from app.models import Context, Resource
from app.schemas import ResourceCreate
from app.security import verify_integration_key, verify_odoo_signature
from app.services import add_resource, list_contexts, serialize_context

router = APIRouter(prefix="/integrations", tags=["integrations"])

SOURCE_LABELS = {
    "gmail": "Gmail",
    "chat": "Google Chat",
    "drive": "Google Drive",
    "calendar": "Google Calendar",
    "odoo": "Odoo",
}


def _open_link_button(text: str, url: str) -> dict[str, Any]:
    return {"text": text, "onClick": {"openLink": {"url": url}}}


def _workspace_response(card: dict[str, Any]) -> dict[str, Any]:
    return {"action": {"navigations": [{"pushCard": card}]}}


def _context_card(item, compact: bool = False) -> dict[str, Any]:
    settings = get_settings()
    sources = " · ".join(SOURCE_LABELS.get(source, source) for source in item.sources) or "Aucune source"
    widgets: list[dict[str, Any]] = [
        {
            "decoratedText": {
                "text": item.summary or "Aucun résumé",
                "wrapText": True,
                "bottomLabel": f"{item.resource_count} ressource(s) · {sources}",
            }
        },
        {
            "buttonList": {
                "buttons": [_open_link_button("Ouvrir le contexte", f"{settings.app_public_url}/?context={item.id}")]
            }
        },
    ]
    return {
        "header": {"title": item.title, "subtitle": item.context_type.capitalize()},
        "sections": [{"widgets": widgets}],
        "name": f"context-{item.id}" if not compact else "context-summary",
    }


@router.post("/workspace/home")
def workspace_home(_event: dict[str, Any], db: Session = Depends(get_db)):
    settings = get_settings()
    contexts = list_contexts(db, context_status="active", limit=5)
    widgets: list[dict[str, Any]] = [
        {
            "textParagraph": {
                "text": "Retrouvez les informations d’un même sujet sans quitter Google Workspace."
            }
        }
    ]
    for item in contexts:
        widgets.append(
            {
                "decoratedText": {
                    "text": f"<b>{item.title}</b>",
                    "bottomLabel": f"{item.resource_count} ressources · {item.context_type}",
                    "onClick": {"openLink": {"url": f"{settings.app_public_url}/?context={item.id}"}},
                }
            }
        )
    widgets.append(
        {
            "buttonList": {
                "buttons": [_open_link_button("Ouvrir Context Hub", settings.app_public_url)]
            }
        }
    )
    return _workspace_response(
        {
            "header": {"title": "Context Hub", "subtitle": "Vos contextes actifs"},
            "sections": [{"widgets": widgets}],
        }
    )


def _workspace_item(event: dict[str, Any]) -> dict[str, str]:
    host = str(event.get("commonEventObject", {}).get("hostApp", "")).lower()
    if "gmail" in event or host == "gmail":
        gmail = event.get("gmail", {})
        external_id = gmail.get("threadId") or gmail.get("messageId") or "gmail-current-item"
        return {
            "source": "gmail",
            "external_id": external_id,
            "title": "Conversation Gmail",
            "url": f"https://mail.google.com/mail/u/0/#all/{quote(external_id)}",
            "resource_type": "thread",
        }
    if "drive" in event or host == "drive":
        drive = event.get("drive", {})
        selected = (drive.get("selectedItems") or [{}])[0]
        external_id = selected.get("id", "drive-current-item")
        return {
            "source": "drive",
            "external_id": external_id,
            "title": selected.get("title") or "Élément Google Drive",
            "url": selected.get("url") or f"https://drive.google.com/open?id={quote(external_id)}",
            "resource_type": selected.get("mimeType") or "item",
        }
    calendar = event.get("calendar", {})
    external_id = calendar.get("id") or calendar.get("eventId") or "calendar-current-event"
    return {
        "source": "calendar",
        "external_id": external_id,
        "title": calendar.get("title") or "Événement Google Calendar",
        "url": "https://calendar.google.com/calendar/u/0/r",
        "resource_type": "event",
    }


@router.post("/workspace/contextual")
def workspace_contextual(event: dict[str, Any], db: Session = Depends(get_db)):
    item = _workspace_item(event)
    matches = db.scalars(
        select(Context)
        .join(Resource)
        .where(Resource.source == item["source"], Resource.external_id == item["external_id"])
        .options(selectinload(Context.resources), selectinload(Context.activities))
    ).unique().all()
    if matches:
        return _workspace_response(_context_card(serialize_context(matches[0]), compact=True))

    contexts = list_contexts(db, context_status="active", limit=25)
    selection_items = [
        {"text": context.title, "value": context.id, "selected": index == 0}
        for index, context in enumerate(contexts)
    ]
    widgets: list[dict[str, Any]] = [
        {
            "decoratedText": {
                "text": f"<b>{item['title']}</b>",
                "bottomLabel": SOURCE_LABELS[item["source"]],
                "wrapText": True,
            }
        }
    ]
    if selection_items:
        widgets.extend(
            [
                {
                    "selectionInput": {
                        "name": "context_id",
                        "label": "Rattacher au contexte",
                        "type": "DROPDOWN",
                        "items": selection_items,
                    }
                },
                {
                    "buttonList": {
                        "buttons": [
                            {
                                "text": "Rattacher",
                                "color": {"red": 0.36, "green": 0.36, "blue": 0.89},
                                "onClick": {
                                    "action": {
                                        "function": f"{get_settings().app_public_url}/integrations/workspace/attach",
                                        "parameters": [
                                            {"key": key, "value": value} for key, value in item.items()
                                        ],
                                    }
                                },
                            }
                        ]
                    }
                },
            ]
        )
    else:
        widgets.append(
            {"textParagraph": {"text": "Créez d’abord un contexte dans l’interface web."}}
        )
    return _workspace_response(
        {
            "header": {"title": "Context Hub", "subtitle": "Ressource non rattachée"},
            "sections": [{"widgets": widgets}],
        }
    )


def _form_string(event: dict[str, Any], name: str) -> str | None:
    value = event.get("commonEventObject", {}).get("formInputs", {}).get(name, {})
    values = value.get("stringInputs", {}).get("value", [])
    return values[0] if values else None


@router.post("/workspace/attach")
def workspace_attach(event: dict[str, Any], db: Session = Depends(get_db)):
    context_id = _form_string(event, "context_id")
    raw_parameters = event.get("commonEventObject", {}).get("parameters", {})
    params = (
        {parameter.get("key"): parameter.get("value") for parameter in raw_parameters}
        if isinstance(raw_parameters, list)
        else dict(raw_parameters)
    )
    # HTTP add-ons can expose action parameters either as an array or a map.
    if not context_id or not params.get("source"):
        return {"renderActions": {"action": {"notification": {"text": "Contexte ou ressource manquante"}}}}
    payload = ResourceCreate(
        source=params["source"],
        external_id=params.get("external_id", "workspace-item"),
        title=params.get("title", "Ressource Workspace"),
        url=params.get("url", get_settings().app_public_url),
        resource_type=params.get("resource_type", "item"),
    )
    add_resource(db, context_id, payload, actor="Google Workspace")
    return {
        "renderActions": {
            "action": {
                "notification": {"text": "Ressource rattachée au contexte"},
                "link": {"url": f"{get_settings().app_public_url}/?context={context_id}"},
            }
        },
        "stateChanged": True,
    }


def _chat_context_card(item) -> dict[str, Any]:
    settings = get_settings()
    return {
        "cardId": f"context-{item.id}",
        "card": {
            "header": {"title": item.title, "subtitle": f"{item.resource_count} ressources liées"},
            "sections": [
                {
                    "widgets": [
                        {"textParagraph": {"text": item.summary or "Aucun résumé"}},
                        {
                            "buttonList": {
                                "buttons": [_open_link_button("Ouvrir le contexte", f"{settings.app_public_url}/?context={item.id}")]
                            }
                        },
                    ]
                }
            ],
        },
    }


@router.post("/google-chat/events")
def google_chat_events(event: dict[str, Any], db: Session = Depends(get_db)):
    event_type = event.get("type") or event.get("eventType")
    if event_type == "REMOVED_FROM_SPACE":
        return {}
    if event_type == "ADDED_TO_SPACE":
        return {
            "text": "Bonjour ! Je centralise les ressources de vos sujets métier. Essayez `context Helios` ou `aide`."
        }

    message = event.get("message", {})
    raw_text = message.get("argumentText") or message.get("text") or ""
    text = raw_text.strip()
    for prefix in ("/context", "context", "@Context Hub"):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
            break
    if not text or text.lower() in {"aide", "help"}:
        return {
            "text": "Recherchez un contexte avec `context <mots-clés>`. Exemple : `context Helios`."
        }
    results = list_contexts(db, query=text, limit=5)
    if not results:
        return {
            "text": f"Aucun contexte trouvé pour « {text} ». Créez-en un dans {get_settings().app_public_url}."
        }
    return {
        "text": f"{len(results)} contexte(s) trouvé(s) pour « {text} »",
        "cardsV2": [_chat_context_card(item) for item in results],
    }


@router.post("/odoo/reference", dependencies=[Depends(verify_integration_key)])
async def odoo_reference_create(
    request: Request,
    x_context_hub_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    body = await verify_odoo_signature(request, x_context_hub_signature)
    data = json.loads(body)
    context_id = data.pop("context_id")
    data["source"] = "odoo"
    resource = add_resource(db, context_id, ResourceCreate(**data), actor="Odoo")
    return {"id": resource.id, "context_id": resource.context_id, "status": "linked"}


@router.get("/odoo/references", dependencies=[Depends(verify_integration_key)])
def odoo_reference_list(model: str, record_id: str, db: Session = Depends(get_db)):
    external_id = f"{model}:{record_id}"
    rows = db.scalars(
        select(Context)
        .join(Resource)
        .where(Resource.source == "odoo", Resource.external_id == external_id)
        .options(selectinload(Context.resources), selectinload(Context.activities))
    ).unique().all()
    return [serialize_context(item) for item in rows]


@router.get("/odoo/open")
def odoo_open(
    model: str,
    record_id: str,
    title: str = "",
    source_url: str = "",
    db: Session = Depends(get_db),
):
    """Resolve an Odoo smart button to its Context Hub deep link."""
    external_id = f"{model}:{record_id}"
    context_id = db.scalar(
        select(Resource.context_id)
        .where(Resource.source == "odoo", Resource.external_id == external_id)
        .limit(1)
    )
    settings = get_settings()
    if context_id:
        return RedirectResponse(f"{settings.app_public_url}/?context={context_id}", status_code=302)
    query = urlencode(
        {
            "odoo_model": model,
            "odoo_id": record_id,
            "odoo_title": title,
            "odoo_url": source_url,
        }
    )
    return RedirectResponse(f"{settings.app_public_url}/?{query}", status_code=302)
