"""
services/rag_service.py - RAG Query Engine

RAG = Retrieval-Augmented Generation

Without RAG: Ask Claude a question → Claude answers from its training data
With RAG:    Ask Claude a question → 
             1. Find relevant text chunks from OUR database
             2. Give those chunks to Claude as context
             3. Claude answers based on OUR data, with citations

This means answers are:
- Grounded in your specific data (not general knowledge)
- Traceable (you can see which document each claim came from)
- Up-to-date (your scraped data, not Claude's training cutoff)
"""

import logging
from typing import Optional

import anthropic

from config import get_settings
from services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)
settings = get_settings()


class RAGService:
    """
    Handles both RAG and no-RAG query modes.
    """

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.embedder = EmbeddingService()

    async def query(
        self,
        question: str,
        mode: str = "rag",          # "rag" or "no_rag"
        top_k: int = 5,
        source_id: Optional[str] = None,
        strict_grounding: bool = True,
    ) -> dict:
        """
        Answer a question using the specified mode.
        
        Returns:
            {
                "answer": "The answer text...",
                "mode": "rag",
                "citations": [
                    {"url": "https://...", "text": "Supporting passage...", "score": 0.92}
                ],
                "chunks_retrieved": 5,
            }
        """
        if mode == "rag":
            return await self._query_rag(question, top_k, source_id, strict_grounding)
        else:
            return await self._query_no_rag(question)

    async def _query_rag(
        self,
        question: str,
        top_k: int,
        source_id: Optional[str],
        strict_grounding: bool,
    ) -> dict:
        """
        RAG mode:
        1. Retrieve relevant chunks from Qdrant
        2. Build a prompt with those chunks as context
        3. Ask Claude to answer based only on the context
        """

        # Step 1: Retrieve relevant chunks
        chunks = self.embedder.search(
            query=question,
            top_k=top_k,
            source_id=source_id,
        )

        if not chunks:
            return {
                "answer": "I could not find any relevant information in the knowledge base for this question.",
                "mode": "rag",
                "citations": [],
                "chunks_retrieved": 0,
            }

        # Step 2: Build context string from retrieved chunks
        # Each chunk is numbered so Claude can cite them
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            context_parts.append(
                f"[{i}] Source: {chunk['citation_url']}\n{chunk['text']}"
            )
        context = "\n\n---\n\n".join(context_parts)

        # Step 3: Build the prompt
        system_prompt = self._build_rag_system_prompt(strict_grounding)
        user_prompt = f"""Context documents:

{context}

---

Question: {question}

Answer based on the context documents above. 
Cite sources using [1], [2], etc. notation.
If the context doesn't contain enough information to answer, say so clearly."""

        # Step 4: Call Claude
        logger.info(f"Sending RAG query to Claude: '{question[:80]}...'")
        message = self.client.messages.create(
            model=settings.anthropic_model,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        answer = message.content[0].text

        # Build citations list for the response
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
        """
        No-RAG mode: just ask Claude the question directly.
        Used for benchmarking: how much does our data improve answers?
        """
        message = self.client.messages.create(
            model=settings.anthropic_model,
            max_tokens=2048,
            messages=[{"role": "user", "content": question}],
        )

        return {
            "answer": message.content[0].text,
            "mode": "no_rag",
            "citations": [],
            "chunks_retrieved": 0,
        }

    def _build_rag_system_prompt(self, strict_grounding: bool) -> str:
        """
        The system prompt tells Claude how to behave when answering.
        
        With strict_grounding=True: Claude only uses the provided context.
        This prevents hallucination and ensures all claims are traceable.
        """
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
