from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint
)
from sqlalchemy.orm import (
    DeclarativeBase, 
    Mapped, 
    mapped_column, 
    relationship
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass

class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    username: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
    )

    # Store password hashes, not plaintext passwords.
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    projects: Mapped[list[Project]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    shared_projects: Mapped[list[SharedProject]] = relationship(
        back_populates="shared_with_user",
        cascade="all, delete-orphan",
    )

class Project(Base):
    __tablename__ = "projects"

    project_id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda:datetime.now(timezone.utc),
        nullable=False,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.user_id"),
        nullable=False,
    )

    user: Mapped[User] = relationship(
        back_populates="projects",
    )

    documents: Mapped[list[Document]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )

    shared_projects: Mapped[list[SharedProject]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )

class SharedProject(Base):
    __tablename__ = "shared_projects"

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "shared_with_user_id",
            name="uq_shared_project",
        ),
    )

    shared_project_id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.project_id"),
        nullable=False,
    )

    shared_with_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.user_id"),
        nullable=False,
    )

    project: Mapped[Project] = relationship(
        back_populates="shared_projects",
    )

    shared_with_user: Mapped[User] = relationship(
        back_populates="shared_projects",
    )

class Document(Base):
    __tablename__ = "documents"

    document_id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.project_id"),
        nullable=False,
    )

    document_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    project: Mapped[Project] = relationship(
        back_populates="documents",
    )