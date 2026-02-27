from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.users import current_active_user
from backend.database import get_async_session
from backend.config import settings
from backend.models import Paper, Review, User
from backend.schemas import ReviewCreate, ReviewRead, ReviewUpdate
from backend.services.discord_notify import COLOR_CREATE, COLOR_DELETE, COLOR_UPDATE, notify

router = APIRouter(prefix="/papers/{bibtex_key}/reviews", tags=["reviews"])


async def _get_paper_or_404(bibtex_key: str, session: AsyncSession) -> Paper:
    result = await session.execute(select(Paper).where(Paper.bibtex_key == bibtex_key))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.get("")
async def list_reviews(bibtex_key: str, session: AsyncSession = Depends(get_async_session)):
    paper = await _get_paper_or_404(bibtex_key, session)
    result = await session.execute(
        select(Review).where(Review.paper_id == paper.id).order_by(Review.created_at.desc())
    )
    reviews = result.scalars().all()
    items = []
    for r in reviews:
        display_name = (await session.execute(select(User.username).where(User.id == r.user_id))).scalar_one_or_none()
        items.append(
            ReviewRead(
                id=r.id,
                external_url=r.external_url,
                comment=r.comment,
                user_id=r.user_id,
                user_display_name=display_name,
                created_at=r.created_at,
            )
        )
    return items


@router.post("", status_code=201)
async def create_review(
    bibtex_key: str,
    data: ReviewCreate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    paper = await _get_paper_or_404(bibtex_key, session)
    review = Review(
        paper_id=paper.id,
        user_id=user.id,
        external_url=data.external_url,
        comment=data.comment,
    )
    session.add(review)
    await session.commit()
    await session.refresh(review)
    notify(
        "Review added",
        f"**{bibtex_key}** — {review.external_url}",
        user_name=user.username,
        url=f"{settings.base_url}/#{bibtex_key}",
        color=COLOR_CREATE,
    )
    return ReviewRead(
        id=review.id,
        external_url=review.external_url,
        comment=review.comment,
        user_id=review.user_id,
        user_display_name=user.username,
        created_at=review.created_at,
    )


@router.patch("/{review_id}")
async def update_review(
    bibtex_key: str,
    review_id: int,
    data: ReviewUpdate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    paper = await _get_paper_or_404(bibtex_key, session)
    result = await session.execute(
        select(Review).where(Review.id == review_id, Review.paper_id == paper.id)
    )
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.user_id != user.id and not user.is_superuser:
        raise HTTPException(status_code=403, detail="Not authorized")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(review, key, value)
    await session.commit()
    await session.refresh(review)

    display_name = (await session.execute(select(User.username).where(User.id == review.user_id))).scalar_one_or_none()
    changed = ", ".join(update_data.keys())
    notify(
        "Review updated",
        f"**{bibtex_key}** — changed: {changed}",
        user_name=user.username,
        url=f"{settings.base_url}/#{bibtex_key}",
        color=COLOR_UPDATE,
    )
    return ReviewRead(
        id=review.id,
        external_url=review.external_url,
        comment=review.comment,
        user_id=review.user_id,
        user_display_name=display_name or 'Anonymous',
        created_at=review.created_at,
    )


@router.delete("/{review_id}", status_code=204)
async def delete_review(
    bibtex_key: str,
    review_id: int,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    paper = await _get_paper_or_404(bibtex_key, session)
    result = await session.execute(
        select(Review).where(Review.id == review_id, Review.paper_id == paper.id)
    )
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.user_id != user.id and not user.is_superuser:
        raise HTTPException(status_code=403, detail="Not authorized")
    external_url = review.external_url
    await session.delete(review)
    await session.commit()
    notify(
        "Review deleted",
        f"**{bibtex_key}** — {external_url}",
        user_name=user.username,
        url=f"{settings.base_url}/#{bibtex_key}",
        color=COLOR_DELETE,
    )
