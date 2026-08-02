from fastapi import FastAPI
from db import Base, User, Project, SharedProject, Document
from dotenv import load_dotenv
import os
from sqlalchemy import create_engine

_ = load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL, echo=True)
Base.metadata.create_all(engine)

app = FastAPI()

@app.get('/')
def read_root():
    return {"message": "Welcome to the Project Library API!"}