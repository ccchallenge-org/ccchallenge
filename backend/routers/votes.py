from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.users import current_active_user
from backend.database import get_async_session
from backend.models import Paper, User, Vote
from backend.schemas import VoteCreate, VoteRead

router = APIRouter(prefix="/papers/{bibtex_key}/votes", tags=["votes"])


async def _get_paper_or_404(bibtex_key: str, session: AsyncSession) -> Paper:
    result = await session.execute(select(Paper).where(Paper.bibtex_key == bibtex_key))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.get("")
async def list_votes(bibtex_key: str, session: AsyncSession = Depends(get_async_session)):
    paper = await _get_paper_or_404(bibtex_key, session)
    result = await session.execute(
        select(Vote).where(Vote.paper_id == paper.id).order_by(Vote.created_at.desc())
    )
    votes = result.scalars().all()
    items = []
    for v in votes:
        display_name = (
            await session.execute(select(User.username).where(User.id == v.user_id))
        ).scalar_one_or_none()
        items.append(
            VoteRead(
                id=v.id,
                vote=v.vote,
                reason=v.reason,
                user_id=v.user_id,
                user_display_name=display_name,
                created_at=v.created_at,
            )
        )
    return items


@router.post("", status_code=201)
async def create_or_update_vote(
    bibtex_key: str,
    data: VoteCreate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    paper = await _get_paper_or_404(bibtex_key, session)

    # Check for existing vote (upsert)
    result = await session.execute(
        select(Vote).where(Vote.paper_id == paper.id, Vote.user_id == user.id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.vote = data.vote
        existing.reason = data.reason
        await session.commit()
        await session.refresh(existing)
        return VoteRead(
            id=existing.id,
            vote=existing.vote,
            reason=existing.reason,
            user_id=existing.user_id,
            user_display_name=user.username,
            created_at=existing.created_at,
        )

    vote = Vote(
        paper_id=paper.id,
        user_id=user.id,
        vote=data.vote,
        reason=data.reason,
    )
    session.add(vote)
    await session.commit()
    await session.refresh(vote)
    return VoteRead(
        id=vote.id,
        vote=vote.vote,
        reason=vote.reason,
        user_id=vote.user_id,
        user_display_name=user.username,
        created_at=vote.created_at,
    )


@router.delete("/{vote_id}", status_code=204)
async def delete_vote(
    bibtex_key: str,
    vote_id: int,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    paper = await _get_paper_or_404(bibtex_key, session)
    result = await session.execute(
        select(Vote).where(Vote.id == vote_id, Vote.paper_id == paper.id)
    )
    vote = result.scalar_one_or_none()
    if not vote:
        raise HTTPException(status_code=404, detail="Vote not found")
    if vote.user_id != user.id and not user.is_superuser:
        raise HTTPException(status_code=403, detail="Not authorized")
    await session.delete(vote)
    await session.commit()
