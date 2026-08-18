import aioboto3
from config.config import settings
import os

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def get_s3_client():
    """
    Returns an aioboto3 S3 client context manager.

    Usage:
        async with get_s3_client() as s3_client:
            await s3_client.put_object(...)
    """
    session = aioboto3.Session()

    return session.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
    )


def get_s3_key_from_url(document_url: str) -> str:
    """
    Extracts the S3 object key from a stored document URL.

    Example:
        https://my-bucket.s3.eu-central-1.amazonaws.com/projects/1/file.pdf
        -> projects/1/file.pdf
    """
    prefix = (
        f"https://{settings.AWS_S3_BUCKET}"
        f".s3.{settings.AWS_REGION}.amazonaws.com/"
    )

    return document_url.split(prefix)[-1]

def is_image_file(filename: str, content_type: str) -> bool:
    """Checks if a file is an image based on MIME type or extension."""
    if content_type and content_type.startswith("image/"):
        return True

    ext = os.path.splitext(filename or "")[1].lower()
    return ext in IMAGE_EXTENSIONS


def build_s3_key(filename: str, content_type: str, project_id: int) -> str:
    """
    Builds the S3 object key based on file type.

    - Images  -> resized/{project_id}/{filename}
    - Others  -> uploads/{project_id}/{filename}
    """
    folder = "resized" if is_image_file(filename, content_type) else "uploads"
    return f"{folder}/{project_id}/{filename}"