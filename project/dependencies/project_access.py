from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.db import Project, SharedProject
from models.auth import TokenData


async def get_accessible_project(
    project_id: int,
    current_user: TokenData,
    db: AsyncSession,
    require_owner: bool = False,
    options: Optional[List] = None,
) -> Project:
    """
    Checks whether the current user has access to a project.

    Rules:
        - Owner always has access.
        - If require_owner=True, only owner has access.
        - If require_owner=False, shared participants also have access.

    Optional:
        - options can contain SQLAlchemy loading options, for example:
          [selectinload(Project.documents), selectinload(Project.user)]
    """

    project_query = select(Project).where(Project.project_id == project_id)

    if options:
        project_query = project_query.options(*options)

    result = await db.execute(project_query)
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    # Owner always has access.
    if project.user_id == current_user.user_id:
        return project

    # If only owner is allowed, participant access is denied here.
    if require_owner:
        raise HTTPException(
            status_code=403,
            detail="Only the project owner can perform this action",
        )

    # Check whether the project is shared with the current user.
    share_stmt = select(SharedProject).where(
        SharedProject.project_id == project_id,
        SharedProject.shared_with_user_id == current_user.user_id,
    )

    share_result = await db.execute(share_stmt)
    shared_project = share_result.scalar_one_or_none()

    if not shared_project:
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this project",
        )

    return project