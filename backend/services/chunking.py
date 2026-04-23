"""
services/chunking.py - Structure-aware text chunking

Three split paths:
- Prose: heading → paragraph → sentence → word, token-measured
- Table: one chunk per <table> or markdown pipe-table, Markdown serialization
- VLM: respect layout blocks from vision model output

All paths use the BGE-M3 tokenizer to measure token counts.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup, Tag

from config import get_settings
from models import ChunkType

logger = logging.getLogger(__name__)
settings = get_settings()

# Lazy-loaded tokenizer
_tokenizer = None


def get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        logger.info("Loading BGE-M3 tokenizer: %s", settings.embedding_model)
        from transformers import AutoTokenizer
        _tokenizer = AutoTokenizer.from_pretrained(settings.embedding_model)
        logger.info("BGE-M3 tokenizer loaded")
    return _tokenizer


def count_tokens(text: str) -> int:
    tok = get_tokenizer()
    return len(tok.encode(text, add_special_tokens=False))


@dataclass
class TextChunk:
    text: str
    chunk_type: ChunkType = ChunkType.text
    section_path: Optional[str] = None
    source_method: Optional[str] = None
    token_count: Optional[int] = None


# ─────────────────────────────────────────
# PROSE CHUNKER
# ─────────────────────────────────────────

def _heading_chain_from_soup(tag: Tag, soup: BeautifulSoup) -> str:
    """Walk back through siblings/parents to build heading breadcrumb."""
    headings = []
    current = tag
    while current:
        for sibling in current.find_previous_siblings():
            if hasattr(sibling, 'name') and sibling.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                headings.append(sibling.get_text(strip=True))
                break
        current = current.parent if current.parent and current.parent.name != '[document]' else None
        if current and current.name == '[document]':
            break
    return " / ".join(reversed(headings)) if headings else ""


def _split_into_sentences(text: str) -> list[str]:
    """Simple sentence splitter."""
    parts = re.split(r'(?<=[.!?])\s+', text)
    return [p.strip() for p in parts if p.strip()]


def _split_into_words(text: str, max_tokens: int) -> list[str]:
    """Split oversized text by words, grouping until max_tokens."""
    words = text.split()
    tok = get_tokenizer()
    chunks = []
    buf = []
    buf_tokens = 0
    for w in words:
        wt = len(tok.encode(w, add_special_tokens=False))
        if buf_tokens + wt > max_tokens and buf:
            chunks.append(" ".join(buf))
            buf = []
            buf_tokens = 0
        buf.append(w)
        buf_tokens += wt
    if buf:
        chunks.append(" ".join(buf))
    return chunks


def split_prose(html_or_text: str, source_method: str = "html") -> list[TextChunk]:
    """
    Split prose HTML (or plain text) into token-measured chunks.
    Hierarchy: heading → paragraph → sentence → word.
    """
    cfg = settings.chunking.prose
    target = cfg.target_tokens
    overlap = cfg.overlap_tokens
    min_tok = cfg.min_tokens
    max_tok = cfg.max_tokens

    # Try to parse as HTML; fall back to plain text
    try:
        soup = BeautifulSoup(html_or_text, "html.parser")
        # Remove noise
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        blocks = []
        current_headings: list[str] = []
        for el in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'td', 'th', 'pre', 'blockquote']):
            if el.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                level = int(el.name[1])
                # Truncate heading stack at this level
                current_headings = current_headings[:level - 1]
                current_headings.append(el.get_text(strip=True))
            else:
                txt = el.get_text(separator=" ", strip=True)
                if txt:
                    blocks.append((" / ".join(current_headings), txt))
        if not blocks:
            raise ValueError("No blocks from HTML")
    except Exception:
        # Plain text fallback: split by blank lines as paragraphs
        paragraphs = re.split(r'\n\s*\n', html_or_text)
        blocks = [("", p.strip()) for p in paragraphs if p.strip()]

    # Now build chunks by merging blocks up to target_tokens
    result: list[TextChunk] = []
    buf_texts: list[str] = []
    buf_tokens = 0
    buf_section = ""

    def flush(section: str):
        nonlocal buf_texts, buf_tokens, buf_section
        merged = " ".join(buf_texts)
        tc = count_tokens(merged)
        if tc >= min_tok:
            result.append(TextChunk(
                text=merged,
                chunk_type=ChunkType.text,
                section_path=section or buf_section,
                source_method=source_method,
                token_count=tc,
            ))
        buf_texts = []
        buf_tokens = 0

    for section, text in blocks:
        tok_count = count_tokens(text)

        # Oversized single block: split by sentence then word
        if tok_count > max_tok:
            # Flush existing buffer first
            if buf_texts:
                flush(buf_section)
            sentences = _split_into_sentences(text)
            sent_buf: list[str] = []
            sent_buf_tokens = 0
            for sent in sentences:
                st = count_tokens(sent)
                if st > max_tok:
                    # Word-split this sentence
                    if sent_buf:
                        merged = " ".join(sent_buf)
                        result.append(TextChunk(text=merged, chunk_type=ChunkType.text,
                                                section_path=section, source_method=source_method,
                                                token_count=count_tokens(merged)))
                        sent_buf = []
                        sent_buf_tokens = 0
                    for wchunk in _split_into_words(sent, max_tok):
                        result.append(TextChunk(text=wchunk, chunk_type=ChunkType.text,
                                                section_path=section, source_method=source_method,
                                                token_count=count_tokens(wchunk)))
                elif sent_buf_tokens + st > target:
                    merged = " ".join(sent_buf)
                    result.append(TextChunk(text=merged, chunk_type=ChunkType.text,
                                            section_path=section, source_method=source_method,
                                            token_count=count_tokens(merged)))
                    # Keep overlap: last sentence(s) within overlap token budget
                    overlap_sents = []
                    overlap_tok = 0
                    for s in reversed(sent_buf):
                        st2 = count_tokens(s)
                        if overlap_tok + st2 <= overlap:
                            overlap_sents.insert(0, s)
                            overlap_tok += st2
                        else:
                            break
                    sent_buf = overlap_sents + [sent]
                    sent_buf_tokens = overlap_tok + st
                else:
                    sent_buf.append(sent)
                    sent_buf_tokens += st
            if sent_buf:
                merged = " ".join(sent_buf)
                tc = count_tokens(merged)
                if tc >= min_tok:
                    result.append(TextChunk(text=merged, chunk_type=ChunkType.text,
                                            section_path=section, source_method=source_method,
                                            token_count=tc))
            buf_section = section
            continue

        # Normal block: accumulate
        if buf_tokens + tok_count > target and buf_texts:
            flush(buf_section)
            # Overlap: keep last part of buf
        buf_texts.append(text)
        buf_tokens += tok_count
        buf_section = section or buf_section

    if buf_texts:
        flush(buf_section)

    final = result if result else [TextChunk(text=html_or_text[:4000], source_method=source_method,
                                             token_count=count_tokens(html_or_text[:4000]))]
    logger.debug("split_prose: %d chunks from %d input chars", len(final), len(html_or_text),
                 extra={"event": "chunking_prose", "chunks": len(final), "source_method": source_method})
    return final


# ─────────────────────────────────────────
# TABLE CHUNKER
# ─────────────────────────────────────────

def _table_to_markdown(table_tag: Tag) -> str:
    """Convert an HTML <table> to Markdown pipe format."""
    rows = table_tag.find_all('tr')
    if not rows:
        return table_tag.get_text(separator=" ", strip=True)
    md_rows = []
    header_done = False
    for row in rows:
        cells = row.find_all(['th', 'td'])
        cell_texts = [c.get_text(separator=" ", strip=True).replace("|", "\\|") for c in cells]
        md_rows.append("| " + " | ".join(cell_texts) + " |")
        if not header_done:
            md_rows.append("| " + " | ".join(["---"] * len(cells)) + " |")
            header_done = True
    return "\n".join(md_rows)


def _split_table_by_rows(table_tag: Tag, max_tokens: int) -> list[str]:
    """Split a table that's too large into row groups, repeating header."""
    rows = table_tag.find_all('tr')
    if not rows:
        return [table_tag.get_text()]
    header_cells = rows[0].find_all(['th', 'td'])
    header_line = "| " + " | ".join(c.get_text(strip=True).replace("|", "\\|") for c in header_cells) + " |"
    sep_line = "| " + " | ".join(["---"] * len(header_cells)) + " |"

    data_rows = rows[1:]
    chunks = []
    buf_lines = [header_line, sep_line]
    buf_tokens = count_tokens("\n".join(buf_lines))

    for row in data_rows:
        cells = row.find_all(['th', 'td'])
        row_line = "| " + " | ".join(c.get_text(strip=True).replace("|", "\\|") for c in cells) + " |"
        rt = count_tokens(row_line)
        if buf_tokens + rt > max_tokens and len(buf_lines) > 2:
            chunks.append("\n".join(buf_lines))
            buf_lines = [header_line, sep_line, row_line]
            buf_tokens = count_tokens("\n".join(buf_lines))
        else:
            buf_lines.append(row_line)
            buf_tokens += rt
    if buf_lines:
        chunks.append("\n".join(buf_lines))
    return chunks


def _markdown_pipe_tables(text: str) -> list[tuple[int, int, str]]:
    """Extract markdown pipe tables. Returns list of (start, end, table_text)."""
    pattern = re.compile(r'(\|[^\n]+\|\n\|[-| :]+\|\n(?:\|[^\n]+\|\n?)*)', re.MULTILINE)
    results = []
    for m in pattern.finditer(text):
        results.append((m.start(), m.end(), m.group(0)))
    return results


def split_tables(html_or_text: str, source_method: str = "html") -> list[TextChunk]:
    """
    Extract and chunk tables from HTML or markdown text.
    Returns TextChunk objects tagged as ChunkType.table.
    """
    cfg = settings.chunking.table
    max_tokens = cfg.max_tokens
    chunks: list[TextChunk] = []

    # Try HTML tables
    soup = BeautifulSoup(html_or_text, "html.parser")
    tables = soup.find_all('table')
    for table in tables:
        md = _table_to_markdown(table)
        tok = count_tokens(md)
        if tok > max_tokens:
            for part in _split_table_by_rows(table, max_tokens):
                chunks.append(TextChunk(
                    text=part,
                    chunk_type=ChunkType.table,
                    source_method=source_method,
                    token_count=count_tokens(part),
                ))
        else:
            chunks.append(TextChunk(
                text=md,
                chunk_type=ChunkType.table,
                source_method=source_method,
                token_count=tok,
            ))

    # Try markdown pipe tables (for VLM output or markdown text)
    if not tables:
        for start, end, table_text in _markdown_pipe_tables(html_or_text):
            tok = count_tokens(table_text)
            if tok <= max_tokens:
                chunks.append(TextChunk(
                    text=table_text.strip(),
                    chunk_type=ChunkType.table,
                    source_method=source_method,
                    token_count=tok,
                ))
            # Oversized markdown tables: just keep as-is (row splitting requires HTML)

    logger.debug("split_tables: %d chunks from %d HTML tables + markdown tables",
                 len(chunks), len(tables),
                 extra={"event": "chunking_tables", "chunks": len(chunks)})
    return chunks


# ─────────────────────────────────────────
# VLM CHUNKER
# ─────────────────────────────────────────

def split_vlm(text: str) -> list[TextChunk]:
    """
    Split VLM-extracted text (from Qwen2.5-VL / Qwen3-VL).
    Respects layout blocks already identified by the VLM.
    Max 800 tokens per chunk; only splits if a block exceeds that.
    """
    cfg = settings.chunking.vlm
    max_tokens = cfg.max_tokens
    chunks: list[TextChunk] = []

    # VLM output uses blank lines or "---" as block separators
    blocks = re.split(r'\n(?:\s*[-─━]+\s*\n|\s*\n)', text)

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        tok = count_tokens(block)
        if tok <= max_tokens:
            chunks.append(TextChunk(
                text=block,
                chunk_type=ChunkType.block,
                source_method="vlm",
                token_count=tok,
            ))
        else:
            # Split by words only if block exceeds max
            for part in _split_into_words(block, max_tokens):
                chunks.append(TextChunk(
                    text=part,
                    chunk_type=ChunkType.block,
                    source_method="vlm",
                    token_count=count_tokens(part),
                ))

    final = chunks if chunks else [TextChunk(
        text=text[:3000],
        chunk_type=ChunkType.block,
        source_method="vlm",
        token_count=count_tokens(text[:3000]),
    )]
    logger.debug("split_vlm: %d chunks from %d input chars",
                 len(final), len(text),
                 extra={"event": "chunking_vlm", "chunks": len(final)})
    return final
