"""
services/chunking.py - Structure-aware text splitting

After scraping a page, we need to break the full-page text into smaller pieces
(chunks) that can each be individually embedded. BGE-M3's max input is 8192 tokens,
but smaller chunks (~300-500 tokens) give better retrieval precision because they
contain one focused idea rather than many mixed ones.

Three specialised split paths — each optimised for a different kind of content:

- Prose (split_prose): headings → paragraphs → sentences → words.
  Used for regular article/doc text extracted by HTML or rendered strategies.

- Tables (split_tables): one chunk per <table> or Markdown pipe-table.
  Tables have a rigid structure that breaks if you split mid-row, so we treat
  each table as a unit and repeat the header row when a table must be divided.

- VLM (split_vlm): respects layout blocks from vision-model output.
  The VLM already organised the page into logical blocks; we trust that structure
  and only split a block further if it exceeds the token limit.

All paths use the BGE-M3 tokenizer for exact token counting rather than
approximating with char counts — models have a hard token limit, not a char limit.
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

# The BGE-M3 tokenizer is loaded once and cached here.
# It occupies ~50 MB of memory but loading it takes ~2 s; we never want to do
# that per request.
_tokenizer = None


def get_tokenizer():
    """
    Load and cache the BGE-M3 tokenizer (HuggingFace AutoTokenizer).

    We use the same tokenizer as the embedding model so token counts are exact:
    a chunk that fits according to this tokenizer will also fit inside the model.
    """
    global _tokenizer
    if _tokenizer is None:
        logger.info("Loading BGE-M3 tokenizer: %s", settings.embedding_model)
        from transformers import AutoTokenizer
        _tokenizer = AutoTokenizer.from_pretrained(settings.embedding_model)
        logger.info("BGE-M3 tokenizer loaded")
    return _tokenizer


def count_tokens(text: str) -> int:
    """
    Return the number of BGE-M3 tokens in 'text'.

    add_special_tokens=False: don't count the [CLS]/[SEP] frame tokens,
    only the actual content tokens. The caller adds the budget for special
    tokens separately.
    """
    tok = get_tokenizer()
    return len(tok.encode(text, add_special_tokens=False))


@dataclass
class TextChunk:
    """
    A single text chunk ready to be stored as a Chunk row and embedded.

    Fields:
        text: The raw text content of this chunk.
        chunk_type: ChunkType.text / .table / .block (affects search weights).
        section_path: Breadcrumb of heading titles above this chunk
                      (e.g. "Introduction / Background"), used for context.
        source_method: Which ingest strategy produced this chunk ("html", "rendered", "vlm").
        token_count: Pre-computed token count; avoids re-tokenising in the embedding step.
    """
    text: str
    chunk_type: ChunkType = ChunkType.text
    section_path: Optional[str] = None
    source_method: Optional[str] = None
    token_count: Optional[int] = None


# ---
# PROSE CHUNKER
# ---

def _heading_chain_from_soup(tag: Tag, soup: BeautifulSoup) -> str:
    """
    Walk backwards through the DOM to build a '/' separated heading breadcrumb.

    Example: if a <p> is inside <section> whose last heading was "Fees",
    which itself was under an <h1> "University Info", this returns
    "University Info / Fees".

    We climb the DOM tree, and at each level check for the most recent heading
    sibling. This gives each chunk a context path that helps the LLM understand
    where in the document the chunk came from.
    """
    headings = []
    current = tag
    while current:
        # Search preceding siblings at this level for any heading tag
        for sibling in current.find_previous_siblings():
            if hasattr(sibling, 'name') and sibling.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                headings.append(sibling.get_text(strip=True))
                break  # only take the nearest heading at this level
        # Move up to parent, stop at document root
        current = current.parent if current.parent and current.parent.name != '[document]' else None
        if current and current.name == '[document]':
            break
    # Reverse because we walked up (leaf → root); we want root → leaf order
    return " / ".join(reversed(headings)) if headings else ""


def _split_into_sentences(text: str) -> list[str]:
    """
    Split a paragraph into individual sentences.

    Uses a simple regex: split after a sentence-ending punctuation mark followed
    by whitespace. This is not perfect (e.g. "Prof. Smith" would not split) but
    is good enough for most web content and avoids heavy NLP dependencies.
    """
    parts = re.split(r'(?<=[.!?])\s+', text)
    return [p.strip() for p in parts if p.strip()]


def _split_into_words(text: str, max_tokens: int) -> list[str]:
    """
    Split text that is too long for a single chunk by grouping words.

    This is the last-resort splitter — used only when a single sentence still
    exceeds max_tokens (e.g. a very long table cell or URL-heavy paragraph).

    Algorithm: accumulate words in a buffer until adding the next word would
    exceed max_tokens, then flush the buffer as a new chunk.
    """
    words = text.split()
    tok = get_tokenizer()
    chunks = []
    buf = []
    buf_tokens = 0
    for w in words:
        # Count tokens for this individual word (including any subword splits)
        wt = len(tok.encode(w, add_special_tokens=False))
        if buf_tokens + wt > max_tokens and buf:
            # Current buffer is full — flush it and start a new one
            chunks.append(" ".join(buf))
            buf = []
            buf_tokens = 0
        buf.append(w)
        buf_tokens += wt
    if buf:
        # Don't forget the last partial buffer
        chunks.append(" ".join(buf))
    return chunks


def split_prose(html_or_text: str, source_method: str = "html") -> list[TextChunk]:
    """
    Split prose HTML (or plain text) into token-measured text chunks.

    Chunking hierarchy — we try each level in order until text fits:
    1. Keep blocks under target_tokens together (ideal path).
    2. If a block is oversized, split by sentence.
    3. If a single sentence is oversized, split by word.

    An overlap of overlap_tokens tokens is carried from the end of one chunk
    into the start of the next. This helps the embedder because a sentence that
    was the last line of chunk N also appears at the start of chunk N+1, so
    queries that match that sentence can retrieve either chunk.

    Config (from settings.chunking.prose):
        target_tokens: ideal chunk size (e.g. 400 tokens)
        overlap_tokens: how much to repeat at chunk boundaries (e.g. 50 tokens)
        min_tokens: chunks smaller than this are discarded (noise/boilerplate)
        max_tokens: hard cap — force-split anything larger

    Args:
        html_or_text: Raw HTML string or plain text.
        source_method: Label stored on each chunk ("html", "rendered", etc.).

    Returns:
        List of TextChunk objects ready for embedding.
    """
    cfg = settings.chunking.prose
    target = cfg.target_tokens
    overlap = cfg.overlap_tokens
    min_tok = cfg.min_tokens
    max_tok = cfg.max_tokens

    # Try to parse as HTML and extract semantic blocks (paragraphs, list items, etc.)
    try:
        soup = BeautifulSoup(html_or_text, "html.parser")
        # Remove non-content elements that would add noise to chunks
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        blocks = []               # list of (section_path, text) tuples
        current_headings: list[str] = []

        for el in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                                  'p', 'li', 'td', 'th', 'pre', 'blockquote']):
            if el.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                level = int(el.name[1])  # h3 → level 3
                # Trim the heading stack to this level (h3 resets h4/h5/h6 below it)
                current_headings = current_headings[:level - 1]
                current_headings.append(el.get_text(strip=True))
            else:
                txt = el.get_text(separator=" ", strip=True)
                if txt:
                    blocks.append((" / ".join(current_headings), txt))

        if not blocks:
            raise ValueError("No blocks from HTML")

    except Exception:
        # HTML parsing failed or returned nothing — treat entire input as plain text
        # and split on blank lines (Markdown paragraph style)
        paragraphs = re.split(r'\n\s*\n', html_or_text)
        blocks = [("", p.strip()) for p in paragraphs if p.strip()]

    # Accumulate blocks into chunks, flushing when we exceed target_tokens
    result: list[TextChunk] = []
    buf_texts: list[str] = []
    buf_tokens = 0
    buf_section = ""

    def flush(section: str):
        """Emit the current buffer as a TextChunk if it meets the minimum size."""
        nonlocal buf_texts, buf_tokens, buf_section
        merged = " ".join(buf_texts)
        tc = count_tokens(merged)
        if tc >= min_tok:  # discard tiny fragments (e.g. cookie banners, nav items)
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

        # A single block larger than max_tok needs sentence-level splitting
        if tok_count > max_tok:
            if buf_texts:
                flush(buf_section)  # flush any pending buffer before oversized block
            sentences = _split_into_sentences(text)
            sent_buf: list[str] = []
            sent_buf_tokens = 0
            for sent in sentences:
                st = count_tokens(sent)
                if st > max_tok:
                    # Even a single sentence is too long — must go word by word
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
                    # Buffer reached target — flush and start fresh with overlap
                    merged = " ".join(sent_buf)
                    result.append(TextChunk(text=merged, chunk_type=ChunkType.text,
                                            section_path=section, source_method=source_method,
                                            token_count=count_tokens(merged)))
                    # Carry the last few sentences into the next chunk (overlap window)
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

            # Flush any remaining sentences in the sentence buffer
            if sent_buf:
                merged = " ".join(sent_buf)
                tc = count_tokens(merged)
                if tc >= min_tok:
                    result.append(TextChunk(text=merged, chunk_type=ChunkType.text,
                                            section_path=section, source_method=source_method,
                                            token_count=tc))
            buf_section = section
            continue

        # Normal-sized block: accumulate into the running buffer
        if buf_tokens + tok_count > target and buf_texts:
            flush(buf_section)  # buffer full — emit before adding this block
        buf_texts.append(text)
        buf_tokens += tok_count
        buf_section = section or buf_section  # keep most-recent non-empty section

    # Emit any remaining buffered text
    if buf_texts:
        flush(buf_section)

    # Last-resort fallback: if the entire page produced no chunks (unusual), use a prefix
    final = result if result else [TextChunk(
        text=html_or_text[:4000],
        source_method=source_method,
        token_count=count_tokens(html_or_text[:4000]),
    )]

    logger.debug("split_prose: %d chunks from %d input chars", len(final), len(html_or_text),
                 extra={"event": "chunking_prose", "chunks": len(final), "source_method": source_method})
    return final


# ---
# TABLE CHUNKER
# ---

def _table_to_markdown(table_tag: Tag) -> str:
    """
    Convert an HTML <table> element into Markdown pipe-table format.

    Markdown pipe format example:
        | Name  | Value |
        | ---   | ---   |
        | foo   | 42    |

    The first row of the HTML table becomes the header row.
    Any pipe characters in cell text are escaped as \\| to avoid breaking the format.
    """
    rows = table_tag.find_all('tr')
    if not rows:
        return table_tag.get_text(separator=" ", strip=True)  # degenerate table
    md_rows = []
    header_done = False
    for row in rows:
        cells = row.find_all(['th', 'td'])
        # Escape pipe characters inside cell content so they don't break column alignment
        cell_texts = [c.get_text(separator=" ", strip=True).replace("|", "\\|") for c in cells]
        md_rows.append("| " + " | ".join(cell_texts) + " |")
        if not header_done:
            # Add the separator row that marks the end of the header in Markdown tables
            md_rows.append("| " + " | ".join(["---"] * len(cells)) + " |")
            header_done = True
    return "\n".join(md_rows)


def _split_table_by_rows(table_tag: Tag, max_tokens: int) -> list[str]:
    """
    Split a large HTML table into multiple Markdown chunks, each fitting within max_tokens.

    We repeat the header row at the top of every chunk so each chunk is self-contained —
    a chunk without a header would be meaningless to the embedding model.

    Args:
        table_tag: The BeautifulSoup <table> element to split.
        max_tokens: Maximum tokens per output chunk.

    Returns:
        List of Markdown table strings, each ≤ max_tokens tokens.
    """
    rows = table_tag.find_all('tr')
    if not rows:
        return [table_tag.get_text()]

    # Build the header and separator lines to repeat in every chunk
    header_cells = rows[0].find_all(['th', 'td'])
    header_line = "| " + " | ".join(c.get_text(strip=True).replace("|", "\\|") for c in header_cells) + " |"
    sep_line = "| " + " | ".join(["---"] * len(header_cells)) + " |"

    data_rows = rows[1:]  # everything after the header
    chunks = []
    buf_lines = [header_line, sep_line]
    buf_tokens = count_tokens("\n".join(buf_lines))

    for row in data_rows:
        cells = row.find_all(['th', 'td'])
        row_line = "| " + " | ".join(c.get_text(strip=True).replace("|", "\\|") for c in cells) + " |"
        rt = count_tokens(row_line)
        if buf_tokens + rt > max_tokens and len(buf_lines) > 2:
            # Buffer is full — emit this chunk and start a new one with the header
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
    """
    Find Markdown pipe-table blocks in plain text.

    A pipe table consists of a header row, a separator row (---|---),
    and one or more data rows, all made of | characters.

    Returns:
        List of (start_char, end_char, table_text) tuples.
    """
    pattern = re.compile(r'(\|[^\n]+\|\n\|[-| :]+\|\n(?:\|[^\n]+\|\n?)*)', re.MULTILINE)
    results = []
    for m in pattern.finditer(text):
        results.append((m.start(), m.end(), m.group(0)))
    return results


def split_tables(html_or_text: str, source_method: str = "html") -> list[TextChunk]:
    """
    Extract and chunk tables from HTML or Markdown text.

    Why tables need special handling:
    Splitting a table in the middle of a row would produce a meaningless fragment
    (e.g. "| 42 | 99 |" with no header). We detect tables, convert them to
    Markdown, and if they are too large we split them at row boundaries while
    repeating the header in each chunk.

    Checks HTML <table> elements first. If none found, falls back to looking
    for Markdown pipe-tables (produced by the VLM extraction path).

    Args:
        html_or_text: Raw HTML or Markdown string.
        source_method: Label stored on each chunk.

    Returns:
        List of TextChunk objects tagged as ChunkType.table.
    """
    cfg = settings.chunking.table
    max_tokens = cfg.max_tokens
    chunks: list[TextChunk] = []

    soup = BeautifulSoup(html_or_text, "html.parser")
    tables = soup.find_all('table')

    for table in tables:
        md = _table_to_markdown(table)
        tok = count_tokens(md)
        if tok > max_tokens:
            # Large table: split by rows, repeat header in each chunk
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

    # If no HTML tables found, look for Markdown pipe-tables instead
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
            # Oversized Markdown tables: keep as-is (row-splitting requires an HTML Tag object)

    logger.debug("split_tables: %d chunks from %d HTML tables + markdown tables",
                 len(chunks), len(tables),
                 extra={"event": "chunking_tables", "chunks": len(chunks)})
    return chunks


# ---
# VLM CHUNKER
# ---

def split_vlm(text: str) -> list[TextChunk]:
    """
    Split text extracted by the vision-language model into chunks.

    The VLM (Qwen2.5-VL / Qwen3-VL) already structures its output into logical
    layout blocks separated by blank lines or "---" dividers. We respect that
    structure and treat each block as one chunk.

    Only applies further splitting (by word) if a single block exceeds max_tokens.
    This is rare — VLM blocks are usually headings, short paragraphs, or tables
    that naturally fit within a few hundred tokens.

    Args:
        text: The Markdown-formatted text returned by ExtractionService.

    Returns:
        List of TextChunk objects tagged as ChunkType.block.
    """
    cfg = settings.chunking.vlm
    max_tokens = cfg.max_tokens
    chunks: list[TextChunk] = []

    # Split on blank lines or horizontal rules (—, ─, ━ separators used by the VLM)
    blocks = re.split(r'\n(?:\s*[-─━]+\s*\n|\s*\n)', text)

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        tok = count_tokens(block)
        if tok <= max_tokens:
            # Block fits as-is — keep the VLM's natural segmentation
            chunks.append(TextChunk(
                text=block,
                chunk_type=ChunkType.block,
                source_method="vlm",
                token_count=tok,
            ))
        else:
            # Oversized block — fall back to word-level splitting
            for part in _split_into_words(block, max_tokens):
                chunks.append(TextChunk(
                    text=part,
                    chunk_type=ChunkType.block,
                    source_method="vlm",
                    token_count=count_tokens(part),
                ))

    # Last-resort fallback: if nothing was parsed, use a 3000-char prefix
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
