"""
FastAPI + in-memory RAG (Retrieval-Augmented Generation) boilerplate.

Endpoints:
- POST /rag/add
    Adds a text document to the RAG index
    Payload: { "text": "Some text to store" }

- POST /rag/add-file
    Loads a text file, splits it into chunks, and stores them
    Payload: { "path": "path/to/file.txt" }

- POST /rag/ask
    Queries the RAG system and returns the most relevant text chunk
    Payload: { "query": "What is this about?" }

Architecture:
- Uses a shared in-memory RAG instance
- spaCy embeddings (`en_core_web_md`) for vectorization
- Cosine similarity for retrieval

Notes:
- Data is stored in memory (lost on restart)
- Not optimized for large-scale datasets (linear search)
- No concurrency/thread-safety guarantees
- No persistence or database integration
"""
from fastapi import APIRouter

from backend.schemas import (
    RagTextInput, 
    RagQueryInput, 
    RagAnswerOutput,
)

from example_raglib import ExampleRAG

router = APIRouter()
rag = ExampleRAG()

@router.post("/add")
def add_text(data: RagTextInput):
    rag.add(data.text)
    return {"status": "added"}

@router.post("/ask", response_model=RagAnswerOutput)
def ask(data: RagQueryInput):
    return {"answer": rag.ask(data.query)}