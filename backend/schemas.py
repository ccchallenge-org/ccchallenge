import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from backend.models import FormalisationStatus, ProofAssistant


# ── Papers ──────────────────────────────────────────────────────────────────


class PaperCreate(BaseModel):
    bibtex_key: str
    entry_type: str = "article"
    title: str
    authors: str
    year: Optional[str] = None
    journal: Optional[str] = None
    booktitle: Optional[str] = None
    publisher: Optional[str] = None
    volume: Optional[str] = None
    number: Optional[str] = None
    pages: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    abstract: Optional[str] = None
    note: Optional[str] = None
    extra_fields: Optional[dict] = None
    exclusion_reason: Optional[str] = None


class PaperUpdate(BaseModel):
    entry_type: Optional[str] = None
    title: Optional[str] = None
    authors: Optional[str] = None
    year: Optional[str] = None
    journal: Optional[str] = None
    booktitle: Optional[str] = None
    publisher: Optional[str] = None
    volume: Optional[str] = None
    number: Optional[str] = None
    pages: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    abstract: Optional[str] = None
    note: Optional[str] = None
    extra_fields: Optional[dict] = None
    exclusion_reason: Optional[str] = None


class PaperRead(BaseModel):
    id: int
    bibtex_key: str
    entry_type: str
    title: str
    authors: str
    year: Optional[str]
    journal: Optional[str]
    booktitle: Optional[str]
    publisher: Optional[str]
    volume: Optional[str]
    number: Optional[str]
    pages: Optional[str]
    doi: Optional[str]
    url: Optional[str]
    abstract: Optional[str]
    note: Optional[str]
    formalisation_status: FormalisationStatus
    venue: str
    formalisations_count: int = 0
    reviews_count: int = 0
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PaperBibtexCreate(BaseModel):
    raw_bibtex: str


class StatusChangeRequest(BaseModel):
    status: FormalisationStatus
    reason: Optional[str] = None


# ── Formalisations ──────────────────────────────────────────────────────────


class FormalisationCreate(BaseModel):
    proof_assistant: ProofAssistant
    repository_url: str


class FormalisationUpdate(BaseModel):
    proof_assistant: Optional[ProofAssistant] = None
    repository_url: Optional[str] = None


class FormalisationRead(BaseModel):
    id: int
    proof_assistant: ProofAssistant
    repository_url: str
    status: FormalisationStatus
    user_id: uuid.UUID
    user_display_name: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── Audit Reports ──────────────────────────────────────────────────────────


class AuditReportCreate(BaseModel):
    external_url: str


class AuditReportUpdate(BaseModel):
    external_url: Optional[str] = None


class AuditReportRead(BaseModel):
    id: int
    external_url: str
    user_id: uuid.UUID
    user_display_name: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── Reviews ─────────────────────────────────────────────────────────────────


class ReviewCreate(BaseModel):
    external_url: str
    comment: Optional[str] = None


class ReviewUpdate(BaseModel):
    external_url: Optional[str] = None
    comment: Optional[str] = None


class ReviewRead(BaseModel):
    id: int
    external_url: str
    comment: Optional[str] = None
    user_id: uuid.UUID
    user_display_name: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}



# ── Stats ───────────────────────────────────────────────────────────────────


class StatsRead(BaseModel):
    total: int
    not_started: int
    formalising: int
    auditing: int
    audited: int
    reviews: int
