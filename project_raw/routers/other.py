from dependencies.auth import get_current_user, TokenData
from models.projects import ProjectsListResponse, ProjectDetailResponse
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from db.db import Project, User, SharedProject
from db.db_session import AsyncSessionLocal
from models.documents import DocumentResponse

router = APIRouter(prefix="", tags=["Projects"])

@router.get("/projects", response_model=ProjectsListResponse)
async def get_user_projects(current_user: TokenData = Depends(get_current_user)):
    """
    Get all projects accessible to the current user.
    Returns full project details including their documents.
    """
    async with AsyncSessionLocal() as db:
        try:
            # Query projects where user is either the owner OR project is shared with them
            stmt = (
                select(Project)
                .options(
                    selectinload(Project.documents),  # Eager load documents
                    selectinload(Project.user)       # Eager load user (owner)
                )
                .join(User, Project.user)  # Join with User to get owner info
                .outerjoin(SharedProject, SharedProject.project_id == Project.project_id)
                .where(
                    or_(
                        Project.user_id == current_user.user_id,  # User owns the project
                        SharedProject.shared_with_user_id == current_user.user_id  # Project is shared with user
                    )
                )
                .distinct()  # Remove duplicates if a user both owns and is shared
                .order_by(Project.created_at.desc())  # Most recent first
            )
            
            result = await db.execute(stmt)
            projects = result.scalars().all()
            
            # Build response with owner usernames
            projects_response = []
            for project in projects:
                # Now project.user is already loaded, no lazy load needed
                owner_username = project.user.username if project.user else None
                
                # Convert documents to response model
                documents = [
                    DocumentResponse(
                        document_id=doc.document_id,
                        document_url=doc.document_url
                    )
                    for doc in project.documents
                ]
                
                projects_response.append(
                    ProjectDetailResponse(
                        project_id=project.project_id,
                        name=project.name,
                        description=project.description,
                        created_at=project.created_at,
                        owner_id=project.user_id,
                        owner_username=owner_username or "Unknown",
                        documents=documents
                    )
                )
            
            return ProjectsListResponse(
                message=f"Found {len(projects_response)} projects accessible to user",
                count=len(projects_response),
                projects=projects_response
            )
            
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while retrieving projects: {str(e)}"
            )