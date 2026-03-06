from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.auth.users import current_active_user, current_superuser
from backend.database import get_async_session
from backend.models import ExclusionSuggestion, Formalisation, FormalisationStatus, KeyRedirect, Paper, Review, User
from backend.schemas import (
    ExclusionSuggestionCreate,
    PaperBibtexCreate,
    PaperCreate,
    PaperRead,
    PaperUpdate,
)
from backend.config import settings
from backend.services.bibtex_generator import generate_bibtex
from backend.services.bibtex_parser import parse_single_bibtex
from backend.services.discord_notify import COLOR_CREATE, COLOR_DELETE, COLOR_STATUS, COLOR_UPDATE, notify

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

    create_data = data.model_dump()
    if not user.is_superuser:
        create_data.pop("exclusion_reason", None)
    paper = Paper(**create_data, added_by_id=user.id)
    session.add(paper)
    await session.commit()
    # Re-fetch with formalisations eagerly loaded to avoid lazy-load in async
    result = await session.execute(
        select(Paper).where(Paper.id == paper.id).options(selectinload(Paper.formalisations))
    )
    paper = result.scalar_one()
    notify(
        "Paper added",
        f"**{paper.bibtex_key}** — {paper.title}",
        user_name=user.username,
        url=f"{settings.base_url}/#{paper.bibtex_key}",
        color=COLOR_CREATE,
    )
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
    result = await session.execute(
        select(Paper).where(Paper.id == paper.id).options(selectinload(Paper.formalisations))
    )
    paper = result.scalar_one()
    notify(
        "Paper added (BibTeX)",
        f"**{paper.bibtex_key}** — {paper.title}",
        user_name=user.username,
        url=f"{settings.base_url}/#{paper.bibtex_key}",
        color=COLOR_CREATE,
    )
    return _paper_to_read(paper)


@router.post("/parse-bibtex")
async def parse_bibtex(
    data: PaperBibtexCreate,
    user: User = Depends(current_active_user),
):
    try:
        parsed = parse_single_bibtex(data.raw_bibtex)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return parsed


@router.get("/redirect/{old_key}")
async def get_redirect(old_key: str, session: AsyncSession = Depends(get_async_session)):
    result = await session.execute(select(KeyRedirect).where(KeyRedirect.old_key == old_key))
    redirect = result.scalar_one_or_none()
    if not redirect:
        raise HTTPException(status_code=404, detail="No redirect found")
    return {"new_key": redirect.new_key}


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
    old_exclusion = paper.exclusion_reason
    update_data = data.model_dump(exclude_unset=True)
    if "exclusion_reason" in update_data and not user.is_superuser:
        update_data.pop("exclusion_reason")
    # Only admins can rename bibtex_key
    if "bibtex_key" in update_data:
        if not user.is_superuser:
            update_data.pop("bibtex_key")
        elif update_data["bibtex_key"] != bibtex_key:
            existing = await session.execute(select(Paper).where(Paper.bibtex_key == update_data["bibtex_key"]))
            if existing.scalar_one_or_none():
                raise HTTPException(status_code=409, detail=f"Paper with key '{update_data['bibtex_key']}' already exists")
    # Capture old values for diff
    old_values = {key: getattr(paper, key) for key in update_data}
    old_bibtex_key = paper.bibtex_key
    for key, value in update_data.items():
        setattr(paper, key, value)
    # Create redirect if bibtex_key changed
    if paper.bibtex_key != old_bibtex_key:
        new_key = paper.bibtex_key
        # Upsert redirect for the old key
        existing_redirect = (await session.execute(
            select(KeyRedirect).where(KeyRedirect.old_key == old_bibtex_key)
        )).scalar_one_or_none()
        if existing_redirect:
            existing_redirect.new_key = new_key
        else:
            session.add(KeyRedirect(old_key=old_bibtex_key, new_key=new_key))
        # Update any existing redirects that pointed to the old key (chain resolution)
        await session.execute(
            KeyRedirect.__table__.update()
            .where(KeyRedirect.new_key == old_bibtex_key)
            .values(new_key=new_key)
        )
    await session.commit()
    await session.refresh(paper)

    paper_url = f"{settings.base_url}/#{paper.bibtex_key}"
    new_exclusion = paper.exclusion_reason
    if not old_exclusion and new_exclusion:
        notify("Paper excluded from goal", f"**{paper.bibtex_key}** — {new_exclusion}", user_name=user.username, url=paper_url, color=COLOR_STATUS)
    elif old_exclusion and not new_exclusion:
        notify("Paper re-included in goal", f"**{paper.bibtex_key}**", user_name=user.username, url=paper_url, color=COLOR_STATUS)
    else:
        # Build detailed diff of actually changed fields
        diff_lines = []
        for key in update_data:
            old_val = old_values[key]
            new_val = getattr(paper, key)
            # Normalize for comparison (treat None and "" as equivalent)
            old_norm = old_val if old_val else ""
            new_norm = new_val if new_val else ""
            if str(old_norm) != str(new_norm):
                # Truncate long values for readability
                old_disp = str(old_val or "—")
                new_disp = str(new_val or "—")
                if len(old_disp) > 60:
                    old_disp = old_disp[:57] + "..."
                if len(new_disp) > 60:
                    new_disp = new_disp[:57] + "..."
                diff_lines.append(f"**{key}**: {old_disp} → {new_disp}")
        if diff_lines:
            desc = f"**{paper.bibtex_key}**\n" + "\n".join(diff_lines)
        else:
            desc = f"**{paper.bibtex_key}** — no effective changes"
        notify("Paper updated", desc, user_name=user.username, url=paper_url, color=COLOR_UPDATE)

    return _paper_to_read(paper)


@router.delete("/{bibtex_key}", status_code=204)
async def delete_paper(
    bibtex_key: str,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_superuser),
):
    paper = await _get_paper_or_404(bibtex_key, session)
    title = paper.title
    await session.delete(paper)
    await session.commit()
    notify("Paper deleted", f"**{bibtex_key}** — {title}", user_name=user.username, color=COLOR_DELETE)


@router.post("/{bibtex_key}/suggest-exclusion", status_code=201)
async def suggest_exclusion(
    bibtex_key: str,
    data: ExclusionSuggestionCreate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    paper = await _get_paper_or_404(bibtex_key, session)
    suggestion = ExclusionSuggestion(
        paper_id=paper.id,
        user_id=user.id,
        reason=data.reason,
    )
    session.add(suggestion)
    await session.commit()
    paper_url = f"{settings.base_url}/#{paper.bibtex_key}"
    notify(
        "Exclusion suggested",
        f"**{paper.bibtex_key}** — {data.reason}",
        user_name=user.username,
        url=paper_url,
        color=COLOR_STATUS,
    )
    return {"ok": True}


@router.post("/{bibtex_key}/suggestions/{suggestion_id}/accept")
async def accept_exclusion_suggestion(
    bibtex_key: str,
    suggestion_id: int,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_superuser),
):
    paper = await _get_paper_or_404(bibtex_key, session)
    result = await session.execute(
        select(ExclusionSuggestion).where(ExclusionSuggestion.id == suggestion_id)
    )
    suggestion = result.scalar_one_or_none()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    paper.exclusion_reason = suggestion.reason
    suggestion.resolved = True
    # Resolve all other pending suggestions for this paper
    await session.execute(
        ExclusionSuggestion.__table__.update()
        .where(ExclusionSuggestion.paper_id == paper.id, ExclusionSuggestion.resolved == False)
        .values(resolved=True)
    )
    await session.commit()
    paper_url = f"{settings.base_url}/#{paper.bibtex_key}"
    notify(
        "Paper excluded from goal",
        f"**{paper.bibtex_key}** — {suggestion.reason}",
        user_name=user.username,
        url=paper_url,
        color=COLOR_STATUS,
    )
    return {"ok": True}


@router.post("/{bibtex_key}/suggestions/{suggestion_id}/reject")
async def reject_exclusion_suggestion(
    bibtex_key: str,
    suggestion_id: int,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_superuser),
):
    result = await session.execute(
        select(ExclusionSuggestion).where(ExclusionSuggestion.id == suggestion_id)
    )
    suggestion = result.scalar_one_or_none()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    suggestion.resolved = True
    await session.commit()
    paper_url = f"{settings.base_url}/#{bibtex_key}"
    notify(
        "Exclusion suggestion rejected",
        f"**{bibtex_key}** — {suggestion.reason}",
        user_name=user.username,
        url=paper_url,
        color=COLOR_DELETE,
    )
    return {"ok": True}


@router.get("/{bibtex_key}/bibtex")
async def get_paper_bibtex(bibtex_key: str, session: AsyncSession = Depends(get_async_session)):
    paper = await _get_paper_or_404(bibtex_key, session)
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(generate_bibtex(paper), media_type="text/plain")


