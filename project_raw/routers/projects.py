from fastapi import APIRouter, HTTPException, Depends, status, UploadFile, File
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone

from db.db import Project, SharedProject, User, Document
from db.db_session import AsyncSessionLocal
from models.projects import (
    ProjectCreateRequest, 
    ProjectResponse, 
    ProjectDetailResponse, 
    ProjectsListResponse,
    ProjectUpdateRequest
)
from models.documents import DocumentResponse, DocumentUploadResponse
from dependencies.auth import get_current_user, TokenData
from typing import List
import os
import uuid
from config.config import settings
from dependencies.bucket_client import get_s3_client
from botocore.exceptions import ClientError

router = APIRouter(prefix="/project", tags=["Projects"])

@router.post("", response_model=ProjectResponse)
async def create_project(
    project_data: ProjectCreateRequest,
    current_user: TokenData = Depends(get_current_user)
):
    # Validate project name (minimum 3 characters)
    if len(project_data.name.strip()) < 3:
        raise HTTPException(
            status_code=400,
            detail="Project name must be at least 3 characters long"
        )
    
    # Validate description (minimum 10 characters)
    if len(project_data.description.strip()) < 10:
        raise HTTPException(
            status_code=400,
            detail="Project description must be at least 10 characters long"
        )
    
    # Create an async database session
    async with AsyncSessionLocal() as db:
        try:
            # Check if project name already exists (case-insensitive) - ASYNC
            stmt = select(Project).where(Project.name.ilike(project_data.name.strip()))
            result = await db.execute(stmt)
            existing_project = result.scalar_one_or_none()
            
            if existing_project:
                raise HTTPException(
                    status_code=400,
                    detail="A project with this name already exists"
                )
            
            # Create the project
            new_project = Project(
                name=project_data.name.strip(),
                description=project_data.description.strip(),
                user_id=current_user.user_id,  # Set the creator as the owner
                created_at=datetime.now(timezone.utc)
            )
            
            db.add(new_project)
            await db.flush()  # Flush to get the project_id before creating SharedProject
            
            # Automatically give the creator access as owner/admin
            shared_project = SharedProject(
                project_id=new_project.project_id,
                shared_with_user_id=current_user.user_id
            )
            
            db.add(shared_project)
            await db.commit()
            await db.refresh(new_project)
            
            return ProjectResponse(
                message="Project created successfully",
                project_id=new_project.project_id,
                name=new_project.name,
                description=new_project.description,
                created_at=new_project.created_at,
                owner_id=current_user.user_id,
                owner_username=current_user.username
            )
            
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while creating the project: {str(e)}"
            )

@router.get("", response_model=ProjectsListResponse)
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

@router.get("/{project_id}/info", response_model=ProjectDetailResponse)
async def get_project_info(
    project_id: int,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Get detailed information about a specific project.
    Returns full project details including its documents.
    Access is granted if user owns the project or the project is shared with them.
    """
    async with AsyncSessionLocal() as db:
        try:
            # Query project with eager loading of documents and owner
            stmt = (
                select(Project)
                .options(
                    selectinload(Project.documents),
                    selectinload(Project.user)
                )
                .where(Project.project_id == project_id)
            )
            
            result = await db.execute(stmt)
            project = result.scalar_one_or_none()
            
            if not project:
                raise HTTPException(
                    status_code=404,
                    detail="Project not found"
                )
            
            # Check if user has access (owns the project or project is shared with them)
            # First check if user is the owner
            has_access = project.user_id == current_user.user_id
            
            # If not owner, check if project is shared with the user
            if not has_access:
                share_stmt = (
                    select(SharedProject)
                    .where(
                        SharedProject.project_id == project_id,
                        SharedProject.shared_with_user_id == current_user.user_id
                    )
                )
                share_result = await db.execute(share_stmt)
                shared_project = share_result.scalar_one_or_none()
                has_access = shared_project is not None
            
            if not has_access:
                raise HTTPException(
                    status_code=403,
                    detail="You do not have access to this project"
                )
            
            # Build response
            owner_username = project.user.username if project.user else "Unknown"
            
            documents = [
                DocumentResponse(
                    document_id=doc.document_id,
                    document_url=doc.document_url
                )
                for doc in project.documents
            ]
            
            return ProjectDetailResponse(
                project_id=project.project_id,
                name=project.name,
                description=project.description,
                created_at=project.created_at,
                owner_id=project.user_id,
                owner_username=owner_username,
                documents=documents
            )
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while retrieving the project: {str(e)}"
            )

@router.put("/{project_id}/info", response_model=ProjectDetailResponse)
async def update_project_info(
    project_id: int,
    update_data: ProjectUpdateRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Update project details (name and description).
    Only the project owner can update the project.
    Returns the updated project information.
    """
    # Validate project name (minimum 3 characters)
    if len(update_data.name.strip()) < 3:
        raise HTTPException(
            status_code=400,
            detail="Project name must be at least 3 characters long"
        )
    
    # Validate description (minimum 10 characters)
    if len(update_data.description.strip()) < 10:
        raise HTTPException(
            status_code=400,
            detail="Project description must be at least 10 characters long"
        )
    
    async with AsyncSessionLocal() as db:
        try:
            # Get the project with eager loading
            stmt = (
                select(Project)
                .options(
                    selectinload(Project.documents),
                    selectinload(Project.user)
                )
                .where(Project.project_id == project_id)
            )
            
            result = await db.execute(stmt)
            project = result.scalar_one_or_none()
            
            if not project:
                raise HTTPException(
                    status_code=404,
                    detail="Project not found"
                )
            
            # Check if current user is the owner
            if project.user_id != current_user.user_id:
                raise HTTPException(
                    status_code=403,
                    detail="Only the project owner can update this project"
                )
            
            # Check if new name conflicts with existing project (excluding current project)
            name_check_stmt = (
                select(Project)
                .where(
                    Project.name.ilike(update_data.name.strip()),
                    Project.project_id != project_id
                )
            )
            name_check_result = await db.execute(name_check_stmt)
            existing_project = name_check_result.scalar_one_or_none()
            
            if existing_project:
                raise HTTPException(
                    status_code=400,
                    detail="A project with this name already exists"
                )
            
            # Update project details
            project.name = update_data.name.strip()
            project.description = update_data.description.strip()
            
            await db.commit()
            await db.refresh(project)
            
            # Build response
            owner_username = project.user.username if project.user else "Unknown"
            
            documents = [
                DocumentResponse(
                    document_id=doc.document_id,
                    document_url=doc.document_url
                )
                for doc in project.documents
            ]
            
            return ProjectDetailResponse(
                project_id=project.project_id,
                name=project.name,
                description=project.description,
                created_at=project.created_at,
                owner_id=project.user_id,
                owner_username=owner_username,
                documents=documents
            )
            
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while updating the project: {str(e)}"
            )

@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Delete a project and all associated documents.
    Only the project owner can delete the project.
    """
    async with AsyncSessionLocal() as db:
        try:
            # Get the project
            stmt = select(Project).where(Project.project_id == project_id)
            result = await db.execute(stmt)
            project = result.scalar_one_or_none()
            
            if not project:
                raise HTTPException(
                    status_code=404,
                    detail="Project not found"
                )
            
            # Check if current user is the owner
            if project.user_id != current_user.user_id:
                raise HTTPException(
                    status_code=403,
                    detail="Only the project owner can delete this project"
                )
            
            # Delete the project (cascade will handle documents and shared_projects)
            await db.delete(project)
            await db.commit()
            
            return {
                "message": f"Project '{project.name}' deleted successfully",
                "project_id": project_id
            }
            
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while deleting the project: {str(e)}"
            )

@router.get("{project_id}/documents", response_model=List[DocumentResponse])
async def get_project_documents(
    project_id: int,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Get all documents associated with a specific project.
    Access is granted if user owns the project or the project is shared with them.
    """
    async with AsyncSessionLocal() as db:
        try:
            # First, check if the project exists and user has access
            project_stmt = select(Project).where(Project.project_id == project_id)
            project_result = await db.execute(project_stmt)
            project = project_result.scalar_one_or_none()
            
            if not project:
                raise HTTPException(
                    status_code=404,
                    detail="Project not found"
                )
            
            # Check if user has access (owns the project or project is shared with them)
            has_access = project.user_id == current_user.user_id
            
            if not has_access:
                share_stmt = (
                    select(SharedProject)
                    .where(
                        SharedProject.project_id == project_id,
                        SharedProject.shared_with_user_id == current_user.user_id
                    )
                )
                share_result = await db.execute(share_stmt)
                shared_project = share_result.scalar_one_or_none()
                has_access = shared_project is not None
            
            if not has_access:
                raise HTTPException(
                    status_code=403,
                    detail="You do not have access to this project"
                )
            
            # Get all documents for the project
            doc_stmt = (
                select(Document)
                .where(Document.project_id == project_id)
                .order_by(Document.document_id)
            )
            doc_result = await db.execute(doc_stmt)
            documents = doc_result.scalars().all()
            
            return [
                DocumentResponse(
                    document_id=doc.document_id,
                    document_url=doc.document_url
                )
                for doc in documents
            ]
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while retrieving documents: {str(e)}"
            )

@router.post("/{project_id}/documents", response_model=DocumentUploadResponse)
async def upload_document(
    project_id: int,
    file: UploadFile = File(...),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Upload one or more documents for a specific project to AWS S3 using aioboto3.
    Access is granted if user owns the project or the project is shared with them.
    """
    async with AsyncSessionLocal() as db:
        try:
            # Check if project exists and user has access
            project_stmt = select(Project).where(Project.project_id == project_id)
            project_result = await db.execute(project_stmt)
            project = project_result.scalar_one_or_none()
            
            if not project:
                raise HTTPException(
                    status_code=404,
                    detail="Project not found"
                )
            
            # Check if user has access
            has_access = project.user_id == current_user.user_id
            
            if not has_access:
                share_stmt = (
                    select(SharedProject)
                    .where(
                        SharedProject.project_id == project_id,
                        SharedProject.shared_with_user_id == current_user.user_id
                    )
                )
                share_result = await db.execute(share_stmt)
                shared_project = share_result.scalar_one_or_none()
                has_access = shared_project is not None
            
            if not has_access:
                raise HTTPException(
                    status_code=403,
                    detail="You do not have access to this project"
                )
            
            uploaded_documents = []
            
            # Get async S3 client
            # async with await get_s3_client() as s3_client:
            async with get_s3_client() as s3_client:

                # Generate unique filename
                file_extension = os.path.splitext(file.filename)[1]
                unique_filename = f"projects/{project_id}/{uuid.uuid4()}{file_extension}"
                
                # Read file content
                file_content = await file.read()
                
                try:
                    # Upload to S3 asynchronously
                    await s3_client.put_object(
                        Bucket=settings.AWS_S3_BUCKET,
                        Key=unique_filename,
                        Body=file_content,
                        ContentType=file.content_type or 'application/octet-stream'
                    )
                    
                    # Generate S3 URL
                    document_url = f"https://{settings.AWS_S3_BUCKET}.s3.{settings.AWS_REGION}.amazonaws.com/{unique_filename}"
                    
                    # Create document record in database
                    new_document = Document(
                        project_id=project_id,
                        document_url=document_url
                    )
                    
                    db.add(new_document)
                    await db.flush()
                    await db.refresh(new_document)
                    
                    uploaded_documents.append(
                        DocumentResponse(
                            document_id=new_document.document_id,
                            document_url=new_document.document_url
                        )
                    )
                    
                except ClientError as e:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to upload file '{file.filename}' to S3: {str(e)}"
                    )
                finally:
                    # Reset file position for potential reuse
                    await file.seek(0)
            
            await db.commit()
            
            return DocumentUploadResponse(
                message=f"Successfully uploaded {len(uploaded_documents)} document(s) to S3",
                uploaded_count=len(uploaded_documents),
                documents=uploaded_documents
            )
            
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while uploading documents: {str(e)}"
            )


@router.post("/{project_id}/invite")
async def invite_user_to_project(
    project_id: int,
    login: str,
    current_user: TokenData = Depends(get_current_user)
):
    """Grant access to a project for a specific user."""
    async with AsyncSessionLocal() as db:
        try:
            project_stmt = select(Project).where(Project.project_id == project_id)
            project_result = await db.execute(project_stmt)
            project = project_result.scalar_one_or_none()
            
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
            
            if project.user_id != current_user.user_id:
                raise HTTPException(
                    status_code=403,
                    detail="Only the project owner can invite users"
                )
            
            user_stmt = select(User).where(User.username == login)
            user_result = await db.execute(user_stmt)
            invited_user = user_result.scalar_one_or_none()
            
            if not invited_user:
                raise HTTPException(status_code=404, detail="User not found")
            
            if invited_user.user_id == current_user.user_id:
                raise HTTPException(
                    status_code=400,
                    detail="You cannot invite yourself to your own project"
                )
            
            existing_share_stmt = (
                select(SharedProject)
                .where(
                    SharedProject.project_id == project_id,
                    SharedProject.shared_with_user_id == invited_user.user_id
                )
            )
            existing_share_result = await db.execute(existing_share_stmt)
            existing_share = existing_share_result.scalar_one_or_none()
            
            if existing_share:
                raise HTTPException(
                    status_code=400,
                    detail="User already has access to this project"
                )
            
            shared_project = SharedProject(
                project_id=project_id,
                shared_with_user_id=invited_user.user_id
            )
            
            db.add(shared_project)
            await db.commit()
            
            return {
                "message": f"User '{login}' has been granted access to project '{project.name}'",
                "project_id": project_id,
                "project_name": project.name,
                "user_id": invited_user.user_id,
                "username": invited_user.username
            }
            
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while inviting user: {str(e)}"
            )

# Add other project routes here (create, get, update, delete, get documents)