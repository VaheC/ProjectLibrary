from pydantic import BaseModel
from typing import Optional

class AuthRequest(BaseModel):
    login: str
    password: str
    repeat_password: str

class LoginRequest(BaseModel):
    login: str
    password: str

class AuthResponse(BaseModel):
    message: str
    user_id: int
    username: str

class LoginResponse(BaseModel):
    message: str
    user_id: int
    username: str
    access_token: str
    token_type: str
    expires_in: int

class TokenData(BaseModel):
    user_id: int
    username: str