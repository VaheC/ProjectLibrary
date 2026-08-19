from fastapi import (
    APIRouter,
    HTTPException,
    Depends,
    UploadFile,
    File,
)
from fastapi.responses import StreamingResponse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from botocore.exceptions import ClientError

import io

from db.db import Document
from db.db_session import get_db

from models.documents import DocumentResponse
from models.auth import TokenData

from dependencies.auth import get_current_user
from dependencies.project_access import get_accessible_project
from dependencies.bucket_client import (
    get_s3_client,
    get_s3_key_from_url,
    get_upload_s3_key,
    get_final_s3_key,
)

from config.config import settings


router = APIRouter(prefix="/document", tags=["Documents"])


@router.get("/{document_id}")
async def download_document(
    document_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Download a document.

    Access:
        - owner: allowed,
        - participant: allowed.
    """

    document_query = select(Document).where(Document.document_id == document_id)
    result = await db.execute(document_query)
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        )

    # Check whether the user has access to the related project.
    await get_accessible_project(
        project_id=document.project_id,
        current_user=current_user,
        db=db,
        require_owner=False,
    )

    s3_key = get_s3_key_from_url(document.document_url)

    try:
        async with get_s3_client() as s3_client:
            response = await s3_client.get_object(
                Bucket=settings.AWS_S3_BUCKET,
                Key=s3_key,
            )

            file_content = await response["Body"].read()
            content_type = response.get(
                "ContentType",
                "application/octet-stream",
            )

            filename = s3_key.split("/")[-1]

            return StreamingResponse(
                io.BytesIO(file_content),
                media_type=content_type,
                headers={
                    "Content-Disposition": f"attachment; filename={filename}",
                },
            )

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")

        if error_code == "NoSuchKey":
            raise HTTPException(
                status_code=404,
                detail="File not found in S3 storage",
            )

        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving file from S3: {str(e)}",
        )


@router.put("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: int,
    file: UploadFile = File(...),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update an existing document by replacing its file.

    Access:
        - owner: allowed,
        - participant: allowed.

    Participants can modify documents, but cannot delete them.
    """

    document_query = select(Document).where(Document.document_id == document_id)
    result = await db.execute(document_query)
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        )

    # Participant or owner can modify.
    await get_accessible_project(
        project_id=document.project_id,
        current_user=current_user,
        db=db,
        require_owner=False,
    )

    old_s3_key = get_s3_key_from_url(document.document_url)
    old_filename = old_s3_key.split("/")[-1]

    new_filename = file.filename or "unnamed_file"
    file_content = await file.read()

    # Where to physically upload (always 'uploads/' to trigger Lambda)
    new_upload_key = get_upload_s3_key(new_filename, document.project_id)

    # Where the file will ultimately reside (used for the DB URL)
    new_final_key = get_final_s3_key(
        filename=new_filename,
        content_type=file.content_type,
        project_id=document.project_id,
        file_size=len(file_content),
    )

    try:
        async with get_s3_client() as s3_client:
            # 1. Upload the new file to 'uploads/'
            await s3_client.put_object(
                Bucket=settings.AWS_S3_BUCKET,
                Key=new_upload_key,
                Body=file_content,
                ContentType=file.content_type or "application/octet-stream",
            )

            # 2. Clean up the old file(s) intelligently
            if old_filename != new_filename:
                # The filename changed. Delete the old file from BOTH possible folders.
                old_keys_to_delete = [
                    f"uploads/{document.project_id}/{old_filename}",
                    f"resized/{document.project_id}/{old_filename}"
                ]
                for key in old_keys_to_delete:
                    try:
                        await s3_client.delete_object(
                            Bucket=settings.AWS_S3_BUCKET,
                            Key=key,
                        )
                    except ClientError:
                        pass
            else:
                # The filename is the same. The upload above already overwrote 
                # the file in 'uploads/'. However, if the OLD file was in 'resized/', 
                # we must delete it so it doesn't linger as an orphan.
                if old_s3_key.startswith("resized/"):
                    try:
                        await s3_client.delete_object(
                            Bucket=settings.AWS_S3_BUCKET,
                            Key=f"resized/{document.project_id}/{old_filename}",
                        )
                    except ClientError:
                        pass

    except ClientError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update file in S3: {str(e)}",
        )

    # Store the FINAL location in the database
    document.document_url = (
        f"https://{settings.AWS_S3_BUCKET}"
        f".s3.{settings.AWS_REGION}.amazonaws.com/"
        f"{new_final_key}"
    )

    await db.flush()

    return DocumentResponse(
        document_id=document.document_id,
        document_url=document.document_url,
    )


@router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a document.

    Access:
        - owner: allowed,
        - participant: denied.
    """

    document_query = select(Document).where(Document.document_id == document_id)
    result = await db.execute(document_query)
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        )

    # Only owner can delete.
    await get_accessible_project(
        project_id=document.project_id,
        current_user=current_user,
        db=db,
        require_owner=True,
    )

    s3_key = get_s3_key_from_url(document.document_url)
    filename = s3_key.split("/")[-1]
    
    keys_to_delete = [
        f"uploads/{document.project_id}/{filename}",
        f"resized/{document.project_id}/{filename}"
    ]

    try:
        async with get_s3_client() as s3_client:
            for key in keys_to_delete:
                try:
                    await s3_client.delete_object(
                        Bucket=settings.AWS_S3_BUCKET,
                        Key=key,
                    )
                except ClientError as e:
                    error_code = e.response.get("Error", {}).get("Code")
                    # If the file is already missing in one folder, continue to the next.
                    if error_code != "NoSuchKey":
                        raise

    except ClientError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete file from S3: {str(e)}",
        )

    await db.delete(document)

    return {
        "message": f"Document {document_id} deleted successfully",
        "document_id": document_id,
    }