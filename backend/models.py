import enum
from datetime import datetime

from fastapi_users.db import SQLAlchemyBaseOAuthAccountTableUUID, SQLAlchemyBaseUserTableUUID
from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text, JSON, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    username = Column(String(255), unique=True, nullable=False)
    is_maintainer = Column(Boolean, default=False, nullable=False)
    oauth_accounts = relationship("OAuthAccount", lazy="joined")


class FormalisationStatus(str, enum.Enum):
    not_started = "not_started"
    formalising = "formalising"
    auditing = "auditing"
    audited = "audited"


class Paper(Base):
    __tablename__ = "paper"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bibtex_key = Column(String(255), unique=True, nullable=False, index=True)
    entry_type = Column(String(50), nullable=False, default="article")
    title = Column(Text, nullable=False)
    authors = Column(Text, nullable=False)
    year = Column(String(10), nullable=True)
    journal = Column(Text, nullable=True)
    booktitle = Column(Text, nullable=True)
    publisher = Column(Text, nullable=True)
    volume = Column(String(50), nullable=True)
    number = Column(String(50), nullable=True)
    pages = Column(String(50), nullable=True)
    doi = Column(String(512), nullable=True)
    url = Column(Text, nullable=True)
    abstract = Column(Text, nullable=True)
    note = Column(Text, nullable=True)
    extra_fields = Column(JSON, nullable=True)
    added_by_id = Column(ForeignKey("user.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    formalisations = relationship("Formalisation", back_populates="paper", cascade="all, delete-orphan")
    reviews = relationship("Review", back_populates="paper", cascade="all, delete-orphan")
    votes = relationship("Vote", back_populates="paper", cascade="all, delete-orphan")

    @property
    def computed_status(self):
        if not self.formalisations:
            return FormalisationStatus.not_started
        priority = {
            FormalisationStatus.audited: 3,
            FormalisationStatus.auditing: 2,
            FormalisationStatus.formalising: 1,
        }
        return max(self.formalisations, key=lambda f: priority.get(f.status, 0)).status

    @property
    def venue(self):
        v = self.journal or self.booktitle or self.publisher or ""
        if self.volume:
            v += f", Vol. {self.volume}"
        if self.number:
            v += f"({self.number})"
        if self.pages:
            v += f", pp. {self.pages}"
        return v


class ProofAssistant(str, enum.Enum):
    lean4 = "lean4"
    rocq = "rocq"
    isabelle = "isabelle"
    agda = "agda"
    other = "other"


class Formalisation(Base):
    __tablename__ = "formalisation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(Integer, ForeignKey("paper.id"), nullable=False)
    user_id = Column(ForeignKey("user.id"), nullable=False)
    proof_assistant = Column(Enum(ProofAssistant), nullable=False)
    repository_url = Column(Text, nullable=False)
    status = Column(Enum(FormalisationStatus), default=FormalisationStatus.formalising, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    paper = relationship("Paper", back_populates="formalisations")
    user = relationship("User")
    status_changes = relationship("StatusChange", back_populates="formalisation", cascade="all, delete-orphan")
    audit_reports = relationship("AuditReport", back_populates="formalisation", cascade="all, delete-orphan")


class Review(Base):
    __tablename__ = "review"

    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(Integer, ForeignKey("paper.id"), nullable=False)
    user_id = Column(ForeignKey("user.id"), nullable=False)
    external_url = Column(Text, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    paper = relationship("Paper", back_populates="reviews")
    user = relationship("User")


class AuditReport(Base):
    __tablename__ = "audit_report"

    id = Column(Integer, primary_key=True, autoincrement=True)
    formalisation_id = Column(Integer, ForeignKey("formalisation.id"), nullable=False)
    user_id = Column(ForeignKey("user.id"), nullable=False)
    external_url = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    formalisation = relationship("Formalisation", back_populates="audit_reports")
    user = relationship("User")


class StatusChange(Base):
    __tablename__ = "status_change"

    id = Column(Integer, primary_key=True, autoincrement=True)
    formalisation_id = Column(Integer, ForeignKey("formalisation.id"), nullable=False)
    changed_by_id = Column(ForeignKey("user.id"), nullable=False)
    old_status = Column(Enum(FormalisationStatus), nullable=False)
    new_status = Column(Enum(FormalisationStatus), nullable=False)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    formalisation = relationship("Formalisation", back_populates="status_changes")
    changed_by = relationship("User")


class Vote(Base):
    __tablename__ = "vote"
    __table_args__ = (UniqueConstraint("paper_id", "user_id", name="uq_vote_paper_user"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(Integer, ForeignKey("paper.id"), nullable=False)
    user_id = Column(ForeignKey("user.id"), nullable=False)
    vote = Column(Boolean, nullable=False)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    paper = relationship("Paper", back_populates="votes")
    user = relationship("User")
