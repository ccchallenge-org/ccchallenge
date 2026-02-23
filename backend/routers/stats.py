from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_async_session
from backend.models import Formalisation, FormalisationStatus, Paper, Review
from backend.schemas import StatsRead

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("")
async def get_stats(session: AsyncSession = Depends(get_async_session)) -> StatsRead:
    total = (await session.execute(select(func.count(Paper.id)))).scalar() or 0

    # Compute max status priority per paper: audited(3) > auditing(2) > formalising(1)
    status_priority = case(
        (Formalisation.status == FormalisationStatus.audited, 3),
        (Formalisation.status == FormalisationStatus.auditing, 2),
        else_=1,
    )
    max_status_subq = (
        select(
            Formalisation.paper_id,
            func.max(status_priority).label("max_priority"),
        )
        .group_by(Formalisation.paper_id)
        .subquery()
    )

    rows = (await session.execute(
        select(max_status_subq.c.max_priority, func.count()).group_by(max_status_subq.c.max_priority)
    )).all()
    bucket = {row[0]: row[1] for row in rows}

    papers_with_formalisations = sum(bucket.values())
    reviews = (await session.execute(select(func.count(Review.id)))).scalar() or 0

    return StatsRead(
        total=total,
        not_started=total - papers_with_formalisations,
        formalising=bucket.get(1, 0),
        auditing=bucket.get(2, 0),
        audited=bucket.get(3, 0),
        reviews=reviews,
    )
