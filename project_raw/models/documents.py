from pydantic import BaseModel
from typing import List

class DocumentResponse(BaseModel):
    document_id: int
    document_url: str

class DocumentUploadResponse(BaseModel):
    message: str
    uploaded_count: int
    documents: List[DocumentResponse]