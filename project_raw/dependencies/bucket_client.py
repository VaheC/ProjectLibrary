import aioboto3
from config.config import settings

def get_s3_client():
    session = aioboto3.Session()
    return session.client(
        's3',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
        # aws_session_token=AWS_SESSION_TOKEN
    )