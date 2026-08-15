from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import Activity, Context, Resource
from app.schemas import ContextCreate, ContextDetail, ContextListItem, ContextUpdate, ResourceCreate


def _context_query():
    return select(Context).options(selectinload(Context.resources), selectinload(Context.activities))


def get_context_or_404(db: Session, context_id: str) -> Context:
    item = db.scalar(_context_query().where(Context.id == context_id))
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contexte introuvable")
    return item


def serialize_context(item: Context, detailed: bool = False) -> ContextListItem | ContextDetail:
    resources = list(item.resources)
    base = {
        "id": item.id,
        "title": item.title,
        "summary": item.summary,
        "context_type": item.context_type,
        "status": item.status,
        "priority": item.priority,
        "owner_name": item.owner_name,
        "owner_email": item.owner_email,
        "color": item.color,
        "tags": item.tags or [],
        "due_at": item.due_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "resource_count": len(resources),
        "sources": sorted({resource.source for resource in resources}),
        "latest_resource_at": max((resource.occurred_at for resource in resources), default=None),
    }
    if detailed:
        return ContextDetail(**base, resources=resources, activities=item.activities)
    return ContextListItem(**base)


def list_contexts(
    db: Session,
    query: str | None = None,
    context_type: str | None = None,
    context_status: str | None = None,
    source: str | None = None,
    limit: int = 100,
) -> list[ContextListItem]:
    statement = _context_query()
    if query:
        term = f"%{query.strip()}%"
        statement = statement.where(
            or_(
                Context.title.ilike(term),
                Context.summary.ilike(term),
                Context.owner_name.ilike(term),
                Context.resources.any(Resource.title.ilike(term)),
                Context.resources.any(Resource.excerpt.ilike(term)),
            )
        )
    if context_type:
        statement = statement.where(Context.context_type == context_type)
    if context_status:
        statement = statement.where(Context.status == context_status)
    if source:
        statement = statement.where(Context.resources.any(Resource.source == source))
    statement = statement.order_by(Context.updated_at.desc()).limit(limit)
    return [serialize_context(item) for item in db.scalars(statement).unique().all()]


def create_context(db: Session, payload: ContextCreate, actor: str = "Utilisateur") -> Context:
    item = Context(**payload.model_dump())
    db.add(item)
    db.flush()
    db.add(Activity(context_id=item.id, action="context_created", detail=item.title, actor=actor))
    db.commit()
    return get_context_or_404(db, item.id)


def update_context(db: Session, context_id: str, payload: ContextUpdate, actor: str = "Utilisateur") -> Context:
    item = get_context_or_404(db, context_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(item, field, value)
    item.updated_at = datetime.now(UTC)
    db.add(Activity(context_id=item.id, action="context_updated", detail="Informations mises à jour", actor=actor))
    db.commit()
    return get_context_or_404(db, context_id)


def add_resource(db: Session, context_id: str, payload: ResourceCreate, actor: str = "Utilisateur") -> Resource:
    context = get_context_or_404(db, context_id)
    values = payload.model_dump()
    values["url"] = str(values["url"])
    if values["occurred_at"] is None:
        values.pop("occurred_at")
    resource = Resource(context_id=context.id, **values)
    db.add(resource)
    db.add(Activity(context_id=context.id, action="resource_added", detail=payload.title, actor=actor))
    context.updated_at = datetime.now(UTC)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette ressource est déjà liée à ce contexte",
        ) from exc
    db.refresh(resource)
    return resource


def remove_resource(db: Session, context_id: str, resource_id: str, actor: str = "Utilisateur") -> None:
    resource = db.scalar(
        select(Resource).where(Resource.id == resource_id, Resource.context_id == context_id)
    )
    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ressource introuvable")
    title = resource.title
    db.delete(resource)
    db.add(Activity(context_id=context_id, action="resource_removed", detail=title, actor=actor))
    db.commit()
