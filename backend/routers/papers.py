from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.auth.users import current_active_user, current_superuser
from backend.database import get_async_session
from backend.models import Formalisation, FormalisationStatus, Paper, Review, User
from backend.schemas import (
    PaperBibtexCreate,
    PaperCreate,
    PaperRead,
    PaperUpdate,
)
from backend.services.bibtex_generator import generate_bibtex
from backend.services.bibtex_parser import parse_single_bibtex

router = APIRouter(prefix="/papers", tags=["papers"])


def _paper_to_read(paper: Paper, formalisations_count: int = 0, reviews_count: int = 0) -> PaperRead:
    return PaperRead(
        id=paper.id,
        bibtex_key=paper.bibtex_key,
        entry_type=paper.entry_type,
        title=paper.title,
        authors=paper.authors,
        year=paper.year,
        journal=paper.journal,
        booktitle=paper.booktitle,
        publisher=paper.publisher,
        volume=paper.volume,
        number=paper.number,
        pages=paper.pages,
        doi=paper.doi,
        url=paper.url,
        abstract=paper.abstract,
        note=paper.note,
        formalisation_status=paper.computed_status,
        venue=paper.venue,
        formalisations_count=formalisations_count,
        reviews_count=reviews_count,
        created_at=paper.created_at,
    )


async def _get_paper_or_404(bibtex_key: str, session: AsyncSession) -> Paper:
    result = await session.execute(
        select(Paper).where(Paper.bibtex_key == bibtex_key).options(selectinload(Paper.formalisations))
    )
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.get("")
async def list_papers(
    status: FormalisationStatus | None = None,
    q: str | None = None,
    session: AsyncSession = Depends(get_async_session),
):
    query = select(Paper)
    if status:
        if status == FormalisationStatus.not_started:
            query = query.where(~Paper.id.in_(select(Formalisation.paper_id)))
        else:
            query = query.where(
                Paper.id.in_(
                    select(Formalisation.paper_id).where(Formalisation.status == status)
                )
            )
    if q:
        pattern = f"%{q}%"
        query = query.where(
            Paper.title.ilike(pattern) | Paper.authors.ilike(pattern) | Paper.bibtex_key.ilike(pattern)
        )

    query = query.options(selectinload(Paper.formalisations)).order_by(Paper.bibtex_key)
    papers = (await session.execute(query)).scalars().unique().all()

    # Get counts for each paper
    paper_ids = [p.id for p in papers]
    fc_q = (
        select(Formalisation.paper_id, func.count().label("cnt"))
        .where(Formalisation.paper_id.in_(paper_ids))
        .group_by(Formalisation.paper_id)
    )
    fc_map = dict((await session.execute(fc_q)).all()) if paper_ids else {}

    rc_q = (
        select(Review.paper_id, func.count().label("cnt"))
        .where(Review.paper_id.in_(paper_ids))
        .group_by(Review.paper_id)
    )
    rc_map = dict((await session.execute(rc_q)).all()) if paper_ids else {}

    items = [_paper_to_read(p, fc_map.get(p.id, 0), rc_map.get(p.id, 0)) for p in papers]
    return {"items": items, "total": len(items)}


@router.post("", status_code=201)
async def create_paper(
    data: PaperCreate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    existing = await session.execute(select(Paper).where(Paper.bibtex_key == data.bibtex_key))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Paper with this bibtex_key already exists")

    paper = Paper(**data.model_dump(), added_by_id=user.id)
    session.add(paper)
    await session.commit()
    await session.refresh(paper)
    paper.formalisations = []
    return _paper_to_read(paper)


@router.post("/bibtex", status_code=201)
async def create_paper_from_bibtex(
    data: PaperBibtexCreate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    try:
        parsed = parse_single_bibtex(data.raw_bibtex)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    existing = await session.execute(select(Paper).where(Paper.bibtex_key == parsed["bibtex_key"]))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Paper with this bibtex_key already exists")

    paper = Paper(
        bibtex_key=parsed["bibtex_key"],
        entry_type=parsed["entry_type"],
        title=parsed["title"],
        authors=parsed["authors"],
        year=parsed.get("year"),
        journal=parsed.get("journal"),
        booktitle=parsed.get("booktitle"),
        publisher=parsed.get("publisher"),
        volume=parsed.get("volume"),
        number=parsed.get("number"),
        pages=parsed.get("pages"),
        doi=parsed.get("doi"),
        url=parsed.get("url"),
        abstract=parsed.get("abstract"),
        note=parsed.get("note"),
        extra_fields=parsed.get("extra_fields"),
        added_by_id=user.id,
    )
    session.add(paper)
    await session.commit()
    await session.refresh(paper)
    paper.formalisations = []
    return _paper_to_read(paper)


@router.get("/{bibtex_key}")
async def get_paper(bibtex_key: str, session: AsyncSession = Depends(get_async_session)):
    paper = await _get_paper_or_404(bibtex_key, session)
    fc = (await session.execute(select(func.count()).where(Formalisation.paper_id == paper.id))).scalar() or 0
    rc = (await session.execute(select(func.count()).where(Review.paper_id == paper.id))).scalar() or 0
    return _paper_to_read(paper, fc, rc)


@router.put("/{bibtex_key}")
async def update_paper(
    bibtex_key: str,
    data: PaperUpdate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    paper = await _get_paper_or_404(bibtex_key, session)
    update_data = data.model_dump(exclude_unset=True)
    if "exclusion_reason" in update_data and not user.is_superuser:
        update_data.pop("exclusion_reason")
    for key, value in update_data.items():
        setattr(paper, key, value)
    await session.commit()
    await session.refresh(paper)
    return _paper_to_read(paper)


@router.delete("/{bibtex_key}", status_code=204)
async def delete_paper(
    bibtex_key: str,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_superuser),
):
    paper = await _get_paper_or_404(bibtex_key, session)
    await session.delete(paper)
    await session.commit()


@router.get("/{bibtex_key}/bibtex")
async def get_paper_bibtex(bibtex_key: str, session: AsyncSession = Depends(get_async_session)):
    paper = await _get_paper_or_404(bibtex_key, session)
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(generate_bibtex(paper), media_type="text/plain")


