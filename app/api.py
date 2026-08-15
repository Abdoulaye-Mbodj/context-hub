from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Context, Resource
from app.schemas import (
    ContextCreate,
    ContextBulkDelete,
    ContextDetail,
    ContextListItem,
    ContextUpdate,
    DashboardStats,
    ResourceCreate,
    ResourceRead,
)
from app.services import (
    add_resource,
    create_context,
    get_context_or_404,
    list_contexts,
    remove_resource,
    serialize_context,
    update_context,
)

router = APIRouter(prefix="/api/v1")


@router.get("/contexts", response_model=list[ContextListItem])
def contexts_list(
    q: str | None = Query(default=None, max_length=200),
    context_type: str | None = Query(default=None, alias="type"),
    context_status: str | None = Query(default=None, alias="status"),
    source: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return list_contexts(db, q, context_type, context_status, source, limit)


@router.post("/contexts", response_model=ContextDetail, status_code=status.HTTP_201_CREATED)
def contexts_create(payload: ContextCreate, db: Session = Depends(get_db)):
    return serialize_context(create_context(db, payload), detailed=True)


@router.post("/contexts/bulk-delete")
def contexts_bulk_delete(payload: ContextBulkDelete, db: Session = Depends(get_db)):
    items = db.scalars(select(Context).where(Context.id.in_(payload.ids))).all()
    for item in items:
        db.delete(item)
    db.commit()
    return {"deleted": len(items)}


@router.get("/contexts/{context_id}", response_model=ContextDetail)
def contexts_get(context_id: str, db: Session = Depends(get_db)):
    return serialize_context(get_context_or_404(db, context_id), detailed=True)


@router.patch("/contexts/{context_id}", response_model=ContextDetail)
def contexts_update(context_id: str, payload: ContextUpdate, db: Session = Depends(get_db)):
    return serialize_context(update_context(db, context_id, payload), detailed=True)


@router.delete("/contexts/{context_id}", status_code=status.HTTP_204_NO_CONTENT)
def contexts_delete(context_id: str, db: Session = Depends(get_db)):
    item = get_context_or_404(db, context_id)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/contexts/{context_id}/resources",
    response_model=ResourceRead,
    status_code=status.HTTP_201_CREATED,
)
def resources_create(context_id: str, payload: ResourceCreate, db: Session = Depends(get_db)):
    return add_resource(db, context_id, payload)


@router.delete(
    "/contexts/{context_id}/resources/{resource_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def resources_delete(context_id: str, resource_id: str, db: Session = Depends(get_db)):
    remove_resource(db, context_id, resource_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/dashboard", response_model=DashboardStats)
def dashboard(db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    in_seven_days = now + timedelta(days=7)
    source_rows = db.execute(select(Resource.source, func.count(Resource.id)).group_by(Resource.source)).all()
    return DashboardStats(
        total_contexts=db.scalar(select(func.count(Context.id))) or 0,
        active_contexts=db.scalar(select(func.count(Context.id)).where(Context.status == "active")) or 0,
        linked_resources=db.scalar(select(func.count(Resource.id))) or 0,
        due_soon=db.scalar(
            select(func.count(Context.id)).where(Context.due_at >= now, Context.due_at <= in_seven_days)
        )
        or 0,
        by_source={source: count for source, count in source_rows},
    )
