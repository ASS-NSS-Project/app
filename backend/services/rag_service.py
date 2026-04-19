"""
services/rag_service.py - RAG Query Engine

RAG = Retrieval-Augmented Generation

Without RAG: Ask the LLM a question → answers from its training data
With RAG:    Ask the LLM a question →
             1. Find relevant text chunks from OUR database
             2. Give those chunks to the LLM as context
             3. LLM answers based on OUR data, with citations

Uses the e-INFRA AIaaS OpenAI-compatible API (LLM_BASE_URL / LLM_MODEL).
"""

import logging
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from config import get_settings
from services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)
settings = get_settings()


class RAGService:
    """
    Handles both RAG and no-RAG query modes.
    """

    def __init__(self):
        self.client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
        )
        self.embedder = EmbeddingService()

    async def query(
        self,
        question: str,
        mode: str = "rag",
        top_k: int = 5,
        source_id: Optional[str] = None,
        strict_grounding: bool = True,
        db: Optional[Session] = None,
    ) -> dict:
        if mode == "rag":
            return await self._query_rag(question, top_k, source_id, strict_grounding, db)
        else:
            return await self._query_no_rag(question)

    async def _query_rag(
        self,
        question: str,
        top_k: int,
        source_id: Optional[str],
        strict_grounding: bool,
        db: Optional[Session] = None,
    ) -> dict:
        # Step 1: Retrieve relevant chunks (text fetched from Postgres via db)
        chunks = self.embedder.search(query=question, top_k=top_k, source_id=source_id, db=db)

        if not chunks:
            return {
                "answer": "I could not find any relevant information in the knowledge base for this question.",
                "mode": "rag",
                "citations": [],
                "chunks_retrieved": 0,
            }

        # Step 2: Build context string from retrieved chunks
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            context_parts.append(f"[{i}] Source: {chunk['citation_url']}\n{chunk['text']}")
        context = "\n\n---\n\n".join(context_parts)

        # Step 3: Call LLM
        logger.info(f"Sending RAG query to LLM ({settings.llm_model}): '{question[:80]}'")
        response = await self.client.chat.completions.create(
            model=settings.llm_model,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": self._build_rag_system_prompt(strict_grounding)},
                {"role": "user", "content": (
                    f"Context documents:\n\n{context}\n\n---\n\n"
                    f"Question: {question}\n\n"
                    f"Answer based on the context documents above. "
                    f"Cite sources using [1], [2], etc. notation. "
                    f"If the context doesn't contain enough information to answer, say so clearly."
                )},
            ],
        )

        answer = response.choices[0].message.content

        citations = [
            {
                "index": i + 1,
                "url": chunk["citation_url"],
                "text": chunk["text"][:300] + "..." if len(chunk["text"]) > 300 else chunk["text"],
                "relevance_score": round(chunk["score"], 3),
            }
            for i, chunk in enumerate(chunks)
        ]

        return {
            "answer": answer,
            "mode": "rag",
            "citations": citations,
            "chunks_retrieved": len(chunks),
        }

    async def _query_no_rag(self, question: str) -> dict:
        """No-RAG mode: ask the LLM directly, no retrieval."""
        logger.info(f"Sending no-RAG query to LLM ({settings.llm_model})")
        response = await self.client.chat.completions.create(
            model=settings.llm_model,
            max_tokens=2048,
            messages=[{"role": "user", "content": question}],
        )

        return {
            "answer": response.choices[0].message.content,
            "mode": "no_rag",
            "citations": [],
            "chunks_retrieved": 0,
        }

    def _build_rag_system_prompt(self, strict_grounding: bool) -> str:
        if strict_grounding:
            return """You are a precise research assistant with access to a curated knowledge base.

RULES:
1. Answer ONLY using the information in the provided context documents
2. Every factual claim must be supported by a citation [1], [2], etc.
3. If the context doesn't contain the answer, explicitly say: "The available documents do not contain information about this."
4. Do NOT use your general knowledge to fill gaps
5. Be concise and factual

Your citations allow users to verify every claim you make."""
        else:
            return """You are a helpful research assistant.
You have been provided with context documents from a knowledge base.
Use these documents as your primary source, but you may supplement with general knowledge when clearly needed.
Always cite the context documents when you use them with [1], [2], etc. notation."""
