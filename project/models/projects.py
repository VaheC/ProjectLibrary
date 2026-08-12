from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional
from .documents import DocumentResponse

class ProjectCreateRequest(BaseModel):
    name: str
    description: str

class ProjectResponse(BaseModel):
    message: str
    project_id: int
    name: str
    description: str
    created_at: datetime
    owner_id: int
    owner_username: str

class ProjectDetailResponse(BaseModel):
    project_id: int
    name: str
    description: str
    created_at: datetime
    owner_id: int
    owner_username: str
    documents: List[DocumentResponse] = []

class ProjectsListResponse(BaseModel):
    message: str
    count: int
    projects: List[ProjectDetailResponse]

class ProjectUpdateRequest(BaseModel):
    name: str
    description: str