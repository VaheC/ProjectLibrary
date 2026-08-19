import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite+aiosqlite:///:memory:"

    SECRET_KEY = os.getenv("SECRET_KEY") or "default-secret-key-for-dev-only"
    ALGORITHM = os.getenv("ALGORITHM") or "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES") or 60)

    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID") or "test-access-key"
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY") or "test-secret-key"
    AWS_REGION = os.getenv("AWS_REGION") or "us-east-1"
    AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET") or "test-bucket"
    
    MAX_SIZE_BYTES = int(os.getenv("MAX_SIZE_BYTES") or 2 * 1024 * 1024)

settings = Settings()