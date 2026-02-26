from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.users import current_active_user
from backend.database import get_async_session
from backend.models import AuditReport, Formalisation, FormalisationStatus, Paper, StatusChange, User
from backend.config import settings
from backend.schemas import (
    AuditReportCreate, AuditReportRead, AuditReportUpdate,
    FormalisationCreate, FormalisationRead, FormalisationUpdate,
    StatusChangeRequest,
)
from backend.services.discord_notify import COLOR_CREATE, COLOR_DELETE, COLOR_STATUS, COLOR_UPDATE, notify

router = APIRouter(prefix="/papers/{bibtex_key}/formalisations", tags=["formalisations"])


async def _get_paper_or_404(bibtex_key: str, session: AsyncSession) -> Paper:
    result = await session.execute(select(Paper).where(Paper.bibtex_key == bibtex_key))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.get("")
async def list_formalisations(bibtex_key: str, session: AsyncSession = Depends(get_async_session)):
    paper = await _get_paper_or_404(bibtex_key, session)
    result = await session.execute(
        select(Formalisation).where(Formalisation.paper_id == paper.id).order_by(Formalisation.created_at.desc())
    )
    formalisations = result.scalars().all()
    items = []
    for f in formalisations:
        display_name = (await session.execute(select(User.username).where(User.id == f.user_id))).scalar_one_or_none()
        items.append(
            FormalisationRead(
                id=f.id,
                proof_assistant=f.proof_assistant,
                repository_url=f.repository_url,
                ai_assisted=f.ai_assisted,
                ai_models=f.ai_models,
                status=f.status,
                user_id=f.user_id,
                user_display_name=display_name or 'Anonymous',
                created_at=f.created_at,
            )
        )
    return items


@router.post("", status_code=201)
async def create_formalisation(
    bibtex_key: str,
    data: FormalisationCreate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    paper = await _get_paper_or_404(bibtex_key, session)
    formalisation = Formalisation(
        paper_id=paper.id,
        user_id=user.id,
        proof_assistant=data.proof_assistant,
        repository_url=data.repository_url,
        ai_assisted=data.ai_assisted,
        ai_models=data.ai_models,
    )
    session.add(formalisation)
    await session.commit()
    await session.refresh(formalisation)
    notify(
        "Formalisation added",
        f"**{bibtex_key}** — {formalisation.proof_assistant}\n{formalisation.repository_url}",
        user_name=user.username,
        url=f"{settings.base_url}/papers/{bibtex_key}",
        color=COLOR_CREATE,
    )
    return FormalisationRead(
        id=formalisation.id,
        proof_assistant=formalisation.proof_assistant,
        repository_url=formalisation.repository_url,
        ai_assisted=formalisation.ai_assisted,
        ai_models=formalisation.ai_models,
        status=formalisation.status,
        user_id=formalisation.user_id,
        user_display_name=user.username,
        created_at=formalisation.created_at,
    )


@router.patch("/{formalisation_id}")
async def update_formalisation(
    bibtex_key: str,
    formalisation_id: int,
    data: FormalisationUpdate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    paper = await _get_paper_or_404(bibtex_key, session)
    result = await session.execute(
        select(Formalisation).where(Formalisation.id == formalisation_id, Formalisation.paper_id == paper.id)
    )
    formalisation = result.scalar_one_or_none()
    if not formalisation:
        raise HTTPException(status_code=404, detail="Formalisation not found")
    if formalisation.user_id != user.id and not user.is_superuser:
        raise HTTPException(status_code=403, detail="Not authorized")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(formalisation, key, value)
    await session.commit()
    await session.refresh(formalisation)

    display_name = (await session.execute(select(User.username).where(User.id == formalisation.user_id))).scalar_one_or_none()
    changed = ", ".join(update_data.keys())
    notify(
        "Formalisation updated",
        f"**{bibtex_key}** — changed: {changed}",
        user_name=user.username,
        url=f"{settings.base_url}/papers/{bibtex_key}",
        color=COLOR_UPDATE,
    )
    return FormalisationRead(
        id=formalisation.id,
        proof_assistant=formalisation.proof_assistant,
        repository_url=formalisation.repository_url,
        ai_assisted=formalisation.ai_assisted,
        ai_models=formalisation.ai_models,
        status=formalisation.status,
        user_id=formalisation.user_id,
        user_display_name=display_name or 'Anonymous',
        created_at=formalisation.created_at,
    )


@router.delete("/{formalisation_id}", status_code=204)
async def delete_formalisation(
    bibtex_key: str,
    formalisation_id: int,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    paper = await _get_paper_or_404(bibtex_key, session)
    result = await session.execute(
        select(Formalisation).where(Formalisation.id == formalisation_id, Formalisation.paper_id == paper.id)
    )
    formalisation = result.scalar_one_or_none()
    if not formalisation:
        raise HTTPException(status_code=404, detail="Formalisation not found")
    if formalisation.user_id != user.id and not user.is_superuser:
        raise HTTPException(status_code=403, detail="Not authorized")
    proof_assistant = formalisation.proof_assistant
    await session.delete(formalisation)
    await session.commit()
    notify(
        "Formalisation deleted",
        f"**{bibtex_key}** — {proof_assistant}",
        user_name=user.username,
        url=f"{settings.base_url}/papers/{bibtex_key}",
        color=COLOR_DELETE,
    )


@router.patch("/{formalisation_id}/status")
async def change_formalisation_status(
    bibtex_key: str,
    formalisation_id: int,
    data: StatusChangeRequest,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    paper = await _get_paper_or_404(bibtex_key, session)
    result = await session.execute(
        select(Formalisation).where(Formalisation.id == formalisation_id, Formalisation.paper_id == paper.id)
    )
    formalisation = result.scalar_one_or_none()
    if not formalisation:
        raise HTTPException(status_code=404, detail="Formalisation not found")

    if not user.is_superuser and not user.is_maintainer:
        raise HTTPException(status_code=403, detail="Only maintainers can change formalisation status")

    old_status = formalisation.status

    change = StatusChange(
        formalisation_id=formalisation.id,
        changed_by_id=user.id,
        old_status=old_status,
        new_status=data.status,
        reason=data.reason,
    )
    session.add(change)
    formalisation.status = data.status
    await session.commit()
    await session.refresh(formalisation)

    reason_text = f"\nReason: {data.reason}" if data.reason else ""
    notify(
        "Formalisation status changed",
        f"**{bibtex_key}** — {old_status.value} → {data.status.value}{reason_text}",
        user_name=user.username,
        url=f"{settings.base_url}/papers/{bibtex_key}",
        color=COLOR_STATUS,
    )

    display_name = (await session.execute(select(User.username).where(User.id == formalisation.user_id))).scalar_one_or_none()
    return FormalisationRead(
        id=formalisation.id,
        proof_assistant=formalisation.proof_assistant,
        repository_url=formalisation.repository_url,
        ai_assisted=formalisation.ai_assisted,
        ai_models=formalisation.ai_models,
        status=formalisation.status,
        user_id=formalisation.user_id,
        user_display_name=display_name or 'Anonymous',
        created_at=formalisation.created_at,
    )


# ── Audit Reports ──────────────────────────────────────────────────────────


async def _get_formalisation_or_404(bibtex_key: str, formalisation_id: int, session: AsyncSession) -> tuple:
    paper = await _get_paper_or_404(bibtex_key, session)
    result = await session.execute(
        select(Formalisation).where(Formalisation.id == formalisation_id, Formalisation.paper_id == paper.id)
    )
    formalisation = result.scalar_one_or_none()
    if not formalisation:
        raise HTTPException(status_code=404, detail="Formalisation not found")
    return paper, formalisation


@router.get("/{formalisation_id}/audit-reports")
async def list_audit_reports(
    bibtex_key: str,
    formalisation_id: int,
    session: AsyncSession = Depends(get_async_session),
):
    _, formalisation = await _get_formalisation_or_404(bibtex_key, formalisation_id, session)
    result = await session.execute(
        select(AuditReport).where(AuditReport.formalisation_id == formalisation.id).order_by(AuditReport.created_at.desc())
    )
    reports = result.scalars().all()
    items = []
    for r in reports:
        display_name = (await session.execute(select(User.username).where(User.id == r.user_id))).scalar_one_or_none()
        items.append(
            AuditReportRead(
                id=r.id,
                external_url=r.external_url,
                user_id=r.user_id,
                user_display_name=display_name,
                created_at=r.created_at,
            )
        )
    return items


@router.post("/{formalisation_id}/audit-reports", status_code=201)
async def create_audit_report(
    bibtex_key: str,
    formalisation_id: int,
    data: AuditReportCreate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    _, formalisation = await _get_formalisation_or_404(bibtex_key, formalisation_id, session)
    if formalisation.status == FormalisationStatus.audited:
        raise HTTPException(status_code=400, detail="Cannot add audit reports to audited formalisations")

    report = AuditReport(
        formalisation_id=formalisation.id,
        user_id=user.id,
        external_url=data.external_url,
    )
    session.add(report)

    # Auto-transition from formalising to auditing
    if formalisation.status == FormalisationStatus.formalising:
        change = StatusChange(
            formalisation_id=formalisation.id,
            changed_by_id=user.id,
            old_status=formalisation.status,
            new_status=FormalisationStatus.auditing,
        )
        session.add(change)
        formalisation.status = FormalisationStatus.auditing

    await session.commit()
    await session.refresh(report)
    notify(
        "Audit report added",
        f"**{bibtex_key}** — {report.external_url}",
        user_name=user.username,
        url=f"{settings.base_url}/papers/{bibtex_key}",
        color=COLOR_CREATE,
    )
    return AuditReportRead(
        id=report.id,
        external_url=report.external_url,
        user_id=report.user_id,
        user_display_name=user.username,
        created_at=report.created_at,
    )


@router.patch("/{formalisation_id}/audit-reports/{report_id}")
async def update_audit_report(
    bibtex_key: str,
    formalisation_id: int,
    report_id: int,
    data: AuditReportUpdate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    _, formalisation = await _get_formalisation_or_404(bibtex_key, formalisation_id, session)
    result = await session.execute(
        select(AuditReport).where(AuditReport.id == report_id, AuditReport.formalisation_id == formalisation.id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Audit report not found")
    if report.user_id != user.id and not user.is_superuser:
        raise HTTPException(status_code=403, detail="Not authorized")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(report, key, value)
    await session.commit()
    await session.refresh(report)

    display_name = (await session.execute(select(User.username).where(User.id == report.user_id))).scalar_one_or_none()
    notify(
        "Audit report updated",
        f"**{bibtex_key}** — {report.external_url}",
        user_name=user.username,
        url=f"{settings.base_url}/papers/{bibtex_key}",
        color=COLOR_UPDATE,
    )
    return AuditReportRead(
        id=report.id,
        external_url=report.external_url,
        user_id=report.user_id,
        user_display_name=display_name or 'Anonymous',
        created_at=report.created_at,
    )


@router.delete("/{formalisation_id}/audit-reports/{report_id}", status_code=204)
async def delete_audit_report(
    bibtex_key: str,
    formalisation_id: int,
    report_id: int,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    _, formalisation = await _get_formalisation_or_404(bibtex_key, formalisation_id, session)
    result = await session.execute(
        select(AuditReport).where(AuditReport.id == report_id, AuditReport.formalisation_id == formalisation.id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Audit report not found")
    if report.user_id != user.id and not user.is_superuser:
        raise HTTPException(status_code=403, detail="Not authorized")
    external_url = report.external_url
    await session.delete(report)
    await session.commit()
    notify(
        "Audit report deleted",
        f"**{bibtex_key}** — {external_url}",
        user_name=user.username,
        url=f"{settings.base_url}/papers/{bibtex_key}",
        color=COLOR_DELETE,
    )
