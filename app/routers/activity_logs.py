from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_admin
from ..erp_models import ActivityLog
from ..erp_schemas import ActivityLogListResponse, ActivityLogBase
from ..services.erp_service import utc_now


router = APIRouter(prefix="/activity-logs", tags=["activity-logs"])


@router.post("", status_code=201)
def create_log(
    payload: ActivityLogBase,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin)
):
    log = ActivityLog(
        **payload.dict(),
        admin_id=current_admin.id,
        created_at=utc_now()
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


@router.get("", response_model=ActivityLogListResponse)
def list_logs(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin)
):
    query = select(ActivityLog).order_by(ActivityLog.created_at.desc())
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    results = db.scalars(query.limit(limit).offset(offset)).all()
    return ActivityLogListResponse(total=total or 0, items=results)

