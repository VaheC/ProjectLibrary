from fastapi import APIRouter, HTTPException, Depends, status, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import select
import os
import uuid
import io
import aioboto3
from botocore.exceptions import ClientError

from db.db import Document, Project, SharedProject
from db.db_session import AsyncSessionLocal
from models.documents import DocumentResponse, DocumentUploadResponse
from dependencies.auth import get_current_user, TokenData

router = APIRouter(prefix="/document", tags=["Documents"])

# Environment variables (should be loaded in main.py or config)
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET")

@router.get("/{document_id}")
async def download_document(
    document_id: int,
    current_user: TokenData = Depends(get_current_user)
):
    """Download a specific document from S3."""
    async with AsyncSessionLocal() as db:
        try:
            doc_stmt = select(Document).where(Document.document_id == document_id)
            doc_result = await db.execute(doc_stmt)
            document = doc_result.scalar_one_or_none()
            
            if not document:
                raise HTTPException(status_code=404, detail="Document not found")
            
            project_stmt = select(Project).where(Project.project_id == document.project_id)
            project_result = await db.execute(project_stmt)
            project = project_result.scalar_one_or_none()
            
            if not project:
                raise HTTPException(status_code=404, detail="Associated project not found")
            
            has_access = project.user_id == current_user.user_id
            
            if not has_access:
                share_stmt = (
                    select(SharedProject)
                    .where(
                        SharedProject.project_id == document.project_id,
                        SharedProject.shared_with_user_id == current_user.user_id
                    )
                )
                share_result = await db.execute(share_stmt)
                shared_project = share_result.scalar_one_or_none()
                has_access = shared_project is not None
            
            if not has_access:
                raise HTTPException(
                    status_code=403,
                    detail="You do not have access to this document"
                )
            
            s3_key = document.document_url.split(f"{AWS_S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/")[-1]
            
            try:
                session = aioboto3.Session()
                async with session.client(
                    's3',
                    aws_access_key_id=AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                    region_name=AWS_REGION
                ) as s3_client:
                    response = await s3_client.get_object(
                        Bucket=AWS_S3_BUCKET,
                        Key=s3_key
                    )
                    
                    file_content = await response['Body'].read()
                    content_type = response.get('ContentType', 'application/octet-stream')
                    filename = s3_key.split('/')[-1]
                    
                    return StreamingResponse(
                        io.BytesIO(file_content),
                        media_type=content_type,
                        headers={
                            "Content-Disposition": f"attachment; filename={filename}"
                        }
                    )
                
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchKey':
                    raise HTTPException(status_code=404, detail="File not found in S3 storage")
                else:
                    raise HTTPException(status_code=500, detail=f"Error retrieving file from S3: {str(e)}")
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while downloading the document: {str(e)}"
            )

@router.put("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: int,
    file: UploadFile = File(...),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Update an existing document by replacing it with a new file in S3.
    Access is granted if user owns the project containing this document.
    """
    async with AsyncSessionLocal() as db:
        try:
            # Get the document with project info
            doc_stmt = (
                select(Document)
                .where(Document.document_id == document_id)
            )
            doc_result = await db.execute(doc_stmt)
            document = doc_result.scalar_one_or_none()
            
            if not document:
                raise HTTPException(
                    status_code=404,
                    detail="Document not found"
                )
            
            # Get the associated project
            project_stmt = select(Project).where(Project.project_id == document.project_id)
            project_result = await db.execute(project_stmt)
            project = project_result.scalar_one_or_none()
            
            if not project:
                raise HTTPException(
                    status_code=404,
                    detail="Associated project not found"
                )
            
            # Check if user is the owner
            if project.user_id != current_user.user_id:
                raise HTTPException(
                    status_code=403,
                    detail="Only the project owner can update documents"
                )
            
            # Extract old S3 key from URL
            old_s3_key = document.document_url.split(f"{AWS_S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/")[-1]
            
            # Generate new unique filename
            file_extension = os.path.splitext(file.filename)[1]
            new_s3_key = f"projects/{document.project_id}/{uuid.uuid4()}{file_extension}"
            
            # Read file content
            file_content = await file.read()
            
            try:
                # Create async S3 session and client
                session = aioboto3.Session()
                async with session.client(
                    's3',
                    aws_access_key_id=AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                    region_name=AWS_REGION
                ) as s3_client:
                    # Upload new file to S3 asynchronously
                    await s3_client.put_object(
                        Bucket=AWS_S3_BUCKET,
                        Key=new_s3_key,
                        Body=file_content,
                        ContentType=file.content_type or 'application/octet-stream'
                    )
                    
                    # Delete old file from S3 asynchronously
                    await s3_client.delete_object(
                        Bucket=AWS_S3_BUCKET,
                        Key=old_s3_key
                    )
                
                # Generate new S3 URL
                new_document_url = f"https://{AWS_S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{new_s3_key}"
                
                # Update document in database
                document.document_url = new_document_url
                
                await db.commit()
                await db.refresh(document)
                
                return DocumentResponse(
                    document_id=document.document_id,
                    document_url=document.document_url
                )
                
            except ClientError as e:
                await db.rollback()
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to update file in S3: {str(e)}"
                )
            finally:
                await file.seek(0)
            
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while updating the document: {str(e)}"
            )

@router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Delete a specific document from both S3 and the database.
    Only the project owner can delete documents.
    """
    async with AsyncSessionLocal() as db:
        try:
            # Get the document with project info
            doc_stmt = (
                select(Document)
                .where(Document.document_id == document_id)
            )
            doc_result = await db.execute(doc_stmt)
            document = doc_result.scalar_one_or_none()
            
            if not document:
                raise HTTPException(
                    status_code=404,
                    detail="Document not found"
                )
            
            # Get the associated project
            project_stmt = select(Project).where(Project.project_id == document.project_id)
            project_result = await db.execute(project_stmt)
            project = project_result.scalar_one_or_none()
            
            if not project:
                raise HTTPException(
                    status_code=404,
                    detail="Associated project not found"
                )
            
            # Check if user is the owner (only owner can delete documents)
            if project.user_id != current_user.user_id:
                raise HTTPException(
                    status_code=403,
                    detail="Only the project owner can delete documents"
                )
            
            # Extract S3 key from URL
            s3_key = document.document_url.split(f"{AWS_S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/")[-1]
            
            try:
                # Create async S3 session and client
                session = aioboto3.Session()
                async with session.client(
                    's3',
                    aws_access_key_id=AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                    region_name=AWS_REGION
                ) as s3_client:
                    # Delete file from S3 asynchronously
                    await s3_client.delete_object(
                        Bucket=AWS_S3_BUCKET,
                        Key=s3_key
                    )
            except ClientError as e:
                # Log error but continue with database deletion
                print(f"Warning: Failed to delete file from S3: {str(e)}")
            
            # Delete document from database
            await db.delete(document)
            await db.commit()
            
            return {
                "message": f"Document {document_id} deleted successfully",
                "document_id": document_id
            }
            
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while deleting the document: {str(e)}"
            )