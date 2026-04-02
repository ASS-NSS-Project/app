"""
FastAPI + SQLAlchemy CRUD boilerplate.

Endpoints:
- POST / 
    Creates a new item
    Payload: { "name": "Notebook", "description": "A paper notebook" }

- GET / 
    Returns a list of all items

Architecture:
- Uses dependency injection (`get_db`) to provide a scoped SQLAlchemy session per request
- Uses SQLAlchemy ORM (`Item`) for database interaction
- Uses Pydantic schemas (`ItemCreate`, `ItemOut`) for validation and serialization

Notes:
- Database access and business logic are defined directly in the route handlers
  (for larger projects, consider moving this logic into a dedicated `crud.py` or service layer)
- No error handling (e.g., integrity constraints, missing records)
- No transaction rollback handling on failure
- No pagination or filtering for GET endpoint
- No async database support (synchronous SQLAlchemy session)
- Data is returned as-is without transformation or additional processing
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import Item
from backend.schemas import ItemCreate, ItemOut

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/", response_model=ItemOut)
def create(item: ItemCreate, db: Session = Depends(get_db)):
    db_item = Item(**item.dict())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

@router.get("/", response_model=list[ItemOut])
def read(db: Session = Depends(get_db)):
    return db.query(Item).all()

