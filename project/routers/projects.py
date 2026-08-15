from fastapi import (
    APIRouter,
    HTTPException,
    Depends,
    UploadFile,
    File,
    Query,
)
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
from typing import List, Annotated
from botocore.exceptions import ClientError

import os
import uuid

from db.db import Project, SharedProject, User, Document
from db.db_session import get_db

from models.projects import (
    ProjectCreateRequest,
    ProjectResponse,
    ProjectDetailResponse,
    ProjectsListResponse,
    ProjectUpdateRequest,
)

from models.documents import (
    DocumentResponse,
    DocumentUploadResponse,
)

from models.auth import TokenData

from dependencies.auth import get_current_user
from dependencies.project_access import get_accessible_project
from dependencies.bucket_client import (
    get_s3_client,
    get_s3_key_from_url,
)

from config.config import settings


router = APIRouter(tags=["Projects"])


@router.post("/project", response_model=ProjectResponse)
async def create_project(
    project_data: ProjectCreateRequest,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a project.

    The creator automatically becomes the owner.
    A SharedProject row is also created for the owner so that
    project-access queries can use the shared table consistently.
    """

    name = project_data.name.strip()
    description = project_data.description.strip()

    if len(name) < 3:
        raise HTTPException(
            status_code=400,
            detail="Project name must be at least 3 characters long",
        )

    if len(description) < 10:
        raise HTTPException(
            status_code=400,
            detail="Project description must be at least 10 characters long",
        )

    # Check whether a project with the same name already exists.
    project_query = select(Project).where(Project.name.ilike(name))
    result = await db.execute(project_query)
    existing_project = result.scalar_one_or_none()

    if existing_project:
        raise HTTPException(
            status_code=400,
            detail="A project with this name already exists",
        )

    new_project = Project(
        name=name,
        description=description,
        user_id=current_user.user_id,
        created_at=datetime.now(timezone.utc),
    )

    db.add(new_project)

    await db.flush()

    owner_share = SharedProject(
        project_id=new_project.project_id,
        shared_with_user_id=current_user.user_id,
    )

    db.add(owner_share)
    await db.flush()

    return ProjectResponse(
        message="Project created successfully",
        project_id=new_project.project_id,
        name=new_project.name,
        description=new_project.description,
        created_at=new_project.created_at,
        owner_id=current_user.user_id,
        owner_username=current_user.username,
    )


@router.get("/projects", response_model=ProjectsListResponse)
async def get_user_projects(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all projects accessible to the current user.

    Returns:
        - owned projects,
        - projects shared with the user.

    Each project includes documents and owner information.
    """

    projects_query = (
        select(Project)
        .options(
            selectinload(Project.documents),
            selectinload(Project.user),
        )
        .join(User, Project.user)
        .outerjoin(
            SharedProject,
            SharedProject.project_id == Project.project_id,
        )
        .where(
            or_(
                Project.user_id == current_user.user_id,
                SharedProject.shared_with_user_id == current_user.user_id,
            )
        )
        .distinct()
        .order_by(Project.created_at.desc())
    )

    result = await db.execute(projects_query)
    projects = result.scalars().all()

    projects_response = []

    for project in projects:
        owner_username = project.user.username if project.user else "Unknown"

        documents = [
            DocumentResponse(
                document_id=document.document_id,
                document_url=document.document_url,
            )
            for document in project.documents
        ]

        projects_response.append(
            ProjectDetailResponse(
                project_id=project.project_id,
                name=project.name,
                description=project.description,
                created_at=project.created_at,
                owner_id=project.user_id,
                owner_username=owner_username,
                documents=documents,
            )
        )

    return ProjectsListResponse(
        message=f"Found {len(projects_response)} projects accessible to user",
        count=len(projects_response),
        projects=projects_response,
    )


@router.get(
    "/project/{project_id}/info",
    response_model=ProjectDetailResponse,
)
async def get_project_info(
    project_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get detailed information about a project.

    Access:
        - owner: allowed,
        - participant: allowed.
    """

    project = await get_accessible_project(
        project_id=project_id,
        current_user=current_user,
        db=db,
        require_owner=False,
        options=[
            selectinload(Project.documents),
            selectinload(Project.user),
        ],
    )

    owner_username = project.user.username if project.user else "Unknown"

    documents = [
        DocumentResponse(
            document_id=document.document_id,
            document_url=document.document_url,
        )
        for document in project.documents
    ]

    return ProjectDetailResponse(
        project_id=project.project_id,
        name=project.name,
        description=project.description,
        created_at=project.created_at,
        owner_id=project.user_id,
        owner_username=owner_username,
        documents=documents,
    )


@router.put(
    "/project/{project_id}/info",
    response_model=ProjectDetailResponse,
)
async def update_project_info(
    project_id: int,
    update_data: ProjectUpdateRequest,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update project details: name and description.

    Access:
        - owner: allowed,
        - participant: allowed.

    If you want only owners to update project details,
    change require_owner=False to require_owner=True.
    """

    name = update_data.name.strip()
    description = update_data.description.strip()

    if len(name) < 3:
        raise HTTPException(
            status_code=400,
            detail="Project name must be at least 3 characters long",
        )

    if len(description) < 10:
        raise HTTPException(
            status_code=400,
            detail="Project description must be at least 10 characters long",
        )

    project = await get_accessible_project(
        project_id=project_id,
        current_user=current_user,
        db=db,
        require_owner=False,
        options=[
            selectinload(Project.documents),
            selectinload(Project.user),
        ],
    )

    # Check whether another project already has this name.
    name_check_query = select(Project).where(
        Project.name.ilike(name),
        Project.project_id != project_id,
    )

    name_check_result = await db.execute(name_check_query)
    existing_project = name_check_result.scalar_one_or_none()

    if existing_project:
        raise HTTPException(
            status_code=400,
            detail="A project with this name already exists",
        )

    project.name = name
    project.description = description

    await db.flush()

    owner_username = project.user.username if project.user else "Unknown"

    documents = [
        DocumentResponse(
            document_id=document.document_id,
            document_url=document.document_url,
        )
        for document in project.documents
    ]

    return ProjectDetailResponse(
        project_id=project.project_id,
        name=project.name,
        description=project.description,
        created_at=project.created_at,
        owner_id=project.user_id,
        owner_username=owner_username,
        documents=documents,
    )


@router.delete("/project/{project_id}")
async def delete_project(
    project_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a project.

    Access:
        - owner: allowed,
        - participant: denied.

    This deletes:
        - project row,
        - shared-project rows,
        - document rows,
        - document files in S3.
    """

    project = await get_accessible_project(
        project_id=project_id,
        current_user=current_user,
        db=db,
        require_owner=True,
    )

    # Get all documents belonging to this project so we can delete S3 files.
    documents_query = select(Document).where(
        Document.project_id == project_id
    )

    documents_result = await db.execute(documents_query)
    documents = documents_result.scalars().all()

    if documents:
        try:
            async with get_s3_client() as s3_client:
                for document in documents:
                    s3_key = get_s3_key_from_url(document.document_url)

                    try:
                        await s3_client.delete_object(
                            Bucket=settings.AWS_S3_BUCKET,
                            Key=s3_key,
                        )
                    except ClientError as e:
                        error_code = e.response.get("Error", {}).get("Code")

                        # If the file is already absent, continue deletion.
                        if error_code != "NoSuchKey":
                            raise

        except ClientError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete project files from S3: {str(e)}",
            )

    # Cascade will delete related Document and SharedProject rows.
    await db.delete(project)

    return {
        "message": f"Project '{project.name}' deleted successfully",
        "project_id": project_id,
    }


@router.get(
    "/project/{project_id}/documents",
    response_model=List[DocumentResponse],
)
async def get_project_documents(
    project_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all documents for a project.

    Access:
        - owner: allowed,
        - participant: allowed.
    """

    await get_accessible_project(
        project_id=project_id,
        current_user=current_user,
        db=db,
        require_owner=False,
    )

    project_by_docid_query = (
        select(Document)
        .where(Document.project_id == project_id)
        .order_by(Document.document_id)
    )

    result = await db.execute(project_by_docid_query)
    documents = result.scalars().all()

    return [
        DocumentResponse(
            document_id=document.document_id,
            document_url=document.document_url,
        )
        for document in documents
    ]


# @router.post(
#     "/project/{project_id}/documents",
#     response_model=DocumentUploadResponse,
# )
# async def upload_project_documents(
#     project_id: int,
#     files: List[UploadFile] = File(
#         ...,
#         description="One or more files to upload",
#     ),
#     current_user: TokenData = Depends(get_current_user),
#     db: AsyncSession = Depends(get_db),
# ):
#     """
#     Upload one or multiple documents to a project.

#     Access:
#         - owner: allowed,
#         - participant: allowed.

#     Participants can modify project content by uploading documents,
#     but they cannot delete project documents.
#     """

#     await get_accessible_project(
#         project_id=project_id,
#         current_user=current_user,
#         db=db,
#         require_owner=False,
#     )

#     if not files:
#         raise HTTPException(
#             status_code=400,
#             detail="No files provided",
#         )

#     uploaded_documents = []
#     uploaded_s3_keys = []

#     try:
#         async with get_s3_client() as s3_client:
#             for file in files:
#                 file_extension = os.path.splitext(file.filename or "")[1]

#                 s3_key = (
#                     f"projects/{project_id}/"
#                     f"{uuid.uuid4()}"
#                     f"{file_extension}"
#                 )

#                 file_content = await file.read()

#                 await s3_client.put_object(
#                     Bucket=settings.AWS_S3_BUCKET,
#                     Key=s3_key,
#                     Body=file_content,
#                     ContentType=file.content_type or "application/octet-stream",
#                 )

#                 uploaded_s3_keys.append(s3_key)

#                 document_url = (
#                     f"https://{settings.AWS_S3_BUCKET}"
#                     f".s3.{settings.AWS_REGION}.amazonaws.com/"
#                     f"{s3_key}"
#                 )

#                 new_document = Document(
#                     project_id=project_id,
#                     document_url=document_url,
#                 )

#                 db.add(new_document)
#                 await db.flush()

#                 uploaded_documents.append(
#                     DocumentResponse(
#                         document_id=new_document.document_id,
#                         document_url=new_document.document_url,
#                     )
#                 )

#     except Exception as e:
#         # If something fails during upload, remove already uploaded S3 files.
#         if uploaded_s3_keys:
#             try:
#                 async with get_s3_client() as cleanup_client:
#                     for s3_key in uploaded_s3_keys:
#                         try:
#                             await cleanup_client.delete_object(
#                                 Bucket=settings.AWS_S3_BUCKET,
#                                 Key=s3_key,
#                             )
#                         except Exception:
#                             # In production, log this cleanup failure.
#                             pass
#             except Exception:
#                 # In production, log cleanup client failure.
#                 pass

#         if isinstance(e, HTTPException):
#             raise

#         if isinstance(e, ClientError):
#             raise HTTPException(
#                 status_code=500,
#                 detail=f"Failed to upload file to S3: {str(e)}",
#             )

#         raise HTTPException(
#             status_code=500,
#             detail=f"An error occurred while uploading documents: {str(e)}",
#         )

#     return DocumentUploadResponse(
#         message=f"Successfully uploaded {len(uploaded_documents)} document(s)",
#         uploaded_count=len(uploaded_documents),
#         documents=uploaded_documents,
#     )

@router.post(
    "/project/{project_id}/documents",
    response_model=DocumentUploadResponse,
)
async def upload_project_documents(
    project_id: int,
    # files: Annotated[
    #     List[UploadFile],
    #     File(description="One or more files to upload"),
    # ],
    files: List[UploadFile] = File(...),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload one or multiple documents to a project.

    Access:
        - owner: allowed,
        - participant: allowed.
    """

    await get_accessible_project(
        project_id=project_id,
        current_user=current_user,
        db=db,
        require_owner=False,
    )

    if not files:
        raise HTTPException(
            status_code=400,
            detail="No files provided",
        )

    uploaded_documents = []
    uploaded_s3_keys = []

    try:
        async with get_s3_client() as s3_client:
            for file in files:
                file_extension = os.path.splitext(file.filename or "")[1]

                s3_key = (
                    f"projects/{project_id}/"
                    f"{uuid.uuid4()}"
                    f"{file_extension}"
                )

                file_content = await file.read()

                await s3_client.put_object(
                    Bucket=settings.AWS_S3_BUCKET,
                    Key=s3_key,
                    Body=file_content,
                    ContentType=file.content_type or "application/octet-stream",
                )

                uploaded_s3_keys.append(s3_key)

                document_url = (
                    f"https://{settings.AWS_S3_BUCKET}"
                    f".s3.{settings.AWS_REGION}.amazonaws.com/"
                    f"{s3_key}"
                )

                new_document = Document(
                    project_id=project_id,
                    document_url=document_url,
                )

                db.add(new_document)
                await db.flush()

                uploaded_documents.append(
                    DocumentResponse(
                        document_id=new_document.document_id,
                        document_url=new_document.document_url,
                    )
                )

    except Exception as e:
        # If something fails during upload, remove already uploaded S3 files.
        if uploaded_s3_keys:
            try:
                async with get_s3_client() as cleanup_client:
                    for s3_key in uploaded_s3_keys:
                        try:
                            await cleanup_client.delete_object(
                                Bucket=settings.AWS_S3_BUCKET,
                                Key=s3_key,
                            )
                        except Exception:
                            # In production, log this cleanup failure.
                            pass
            except Exception:
                # In production, log cleanup client failure.
                pass

        if isinstance(e, HTTPException):
            raise

        if isinstance(e, ClientError):
            raise HTTPException(
                status_code=500,
                detail=f"Failed to upload file to S3: {str(e)}",
            )

        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while uploading documents: {str(e)}",
        )

    return DocumentUploadResponse(
        message=f"Successfully uploaded {len(uploaded_documents)} document(s)",
        uploaded_count=len(uploaded_documents),
        documents=uploaded_documents,
    )

@router.post("/project/{project_id}/invite")
async def invite_user_to_project(
    project_id: int,
    username: str = Query(
        ...,
        alias="user",
        description="Username of the user to invite",
    ),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Grant access to a project for a specific user.

    Query parameter:
        user=<login>

    Access:
        - owner: allowed,
        - participant: denied.
    """

    project = await get_accessible_project(
        project_id=project_id,
        current_user=current_user,
        db=db,
        require_owner=True,
    )

    username = username.strip()

    if not username:
        raise HTTPException(
            status_code=400,
            detail="Username must not be empty",
        )

    user_query = select(User).where(User.username == username)
    user_result = await db.execute(user_query)
    invited_user = user_result.scalar_one_or_none()

    if not invited_user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    if invited_user.user_id == current_user.user_id:
        raise HTTPException(
            status_code=400,
            detail="You cannot invite yourself to your own project",
        )

    existing_share_query = select(SharedProject).where(
        SharedProject.project_id == project_id,
        SharedProject.shared_with_user_id == invited_user.user_id,
    )

    existing_share_result = await db.execute(existing_share_query)
    existing_share = existing_share_result.scalar_one_or_none()

    if existing_share:
        raise HTTPException(
            status_code=400,
            detail="User already has access to this project",
        )

    shared_project = SharedProject(
        project_id=project_id,
        shared_with_user_id=invited_user.user_id,
    )

    db.add(shared_project)
    await db.flush()

    return {
        "message": f"User '{invited_user.username}' has been granted access to project '{project.name}'",
        "project_id": project_id,
        "project_name": project.name,
        "user_id": invited_user.user_id,
        "username": invited_user.username,
    }