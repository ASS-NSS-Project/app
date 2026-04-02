import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database import engine, Base
from backend.routers import items, rag

app = FastAPI()

# Basic CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite default
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create database tables based on SQLAlchemy models
Base.metadata.create_all(bind=engine)

# Register routers
# - items -> example DB endpoints      - routers/items.py
# - rag   -> example module endpoints  - routers/rag.py
app.include_router(items.router, prefix="/items", tags=["items"])
app.include_router(rag.router, prefix="/rag", tags=["rag"])