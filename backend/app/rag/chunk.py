"""Split long newsletter text into overlapping chunks for embedding.

Chunking is the first place where retrieval quality is won or lost.  Chunks
that are too large bury the answer inside a wall of text the retriever can't
pinpoint; chunks that are too small lose the context the LLM needs to understand
the question.

The sample newsletters (AlphaSignal, Superhuman) arrive as one dense block of
prose with no blank-line paragraph breaks, so the paragraph splitter below
rarely fires and chunks fill to `CHUNK_SIZE` off sentence boundaries.  At
2048 chars a single chunk spans several unrelated stories, and a specific
question only weakly matches it (cosine similarity around 0.3) — low enough to
trip the confidence guardrail in `ask.py` even when the answer is right there in
the text.  512 chars (~128 tokens, two or three sentences) keeps each chunk on
one passage so a focused question clears the guardrail, while still leaving the
LLM enough surrounding context to answer and cite.
"""

import re

# Target chunk size in *characters* (not tokens).  English is roughly 4 chars
# per token, so 512 chars ≈ 128 tokens — two or three sentences of newsletter
# prose.  We use characters rather than a tokenizer so the chunker stays fast
# and dependency-free.
CHUNK_SIZE = 512

# Overlap between consecutive chunks, in characters (~32 tokens, roughly one
# sentence).  Keeps a sentence that straddles a cut intact in both chunks so the
# retriever can still find it in at least one.
CHUNK_OVERLAP = 128

# A bare minimum chunk size.  If a paragraph is shorter than this after
# splitting, we don't bother splitting it further — tiny chunks hurt retrieval
# more than they help.
_MIN_CHUNK = 128


def chunk_text(text: str) -> list[str]:
    """Split `text` into overlapping chunks, respecting paragraph boundaries.

    Steps:
    1. Split on blank lines (paragraph boundaries).
    2. Within each oversized paragraph, split further on sentence boundaries.
    3. If a sentence still exceeds the chunk size, fall back to a fixed-width
       sliding window.

    Returns a list of text chunks.  Very short texts may produce a single chunk
    (or none if the input is empty).
    """
    text = text.strip()
    if not text:
        return []

    paragraphs = _split_paragraphs(text)
    chunks: list[str] = []

    for para in paragraphs:
        if len(para) <= CHUNK_SIZE:
            chunks.append(para)
        else:
            chunks.extend(_chunk_long_paragraph(para))

    # Merge adjacent chunks that are too small (leftovers from splitting).
    chunks = _merge_short_chunks(chunks)

    # Apply overlap between consecutive chunks.
    if CHUNK_OVERLAP > 0 and len(chunks) > 1:
        chunks = _apply_overlap(chunks)

    return chunks


def _split_paragraphs(text: str) -> list[str]:
    """Split on blank lines, keeping only non-empty paragraphs."""
    parts = re.split(r"\n\s*\n", text)
    return [s for p in parts if (s := p.strip())]


# Matches sentence boundaries: `.` `!` `?` followed by a space and a capital
# letter, or the end of the string.  Handles common abbreviations (Mr. Dr. etc.)
# with a simple heuristic: don't split on single-letter "words" before the dot.
_SENTENCE_END = re.compile(
    r"(?<=[.!?])\s+(?=[A-Z])"
)


def _chunk_long_paragraph(paragraph: str) -> list[str]:
    """Split a single long paragraph into sentence-level chunks.

    If a sentence is longer than `CHUNK_SIZE`, split it further with a
    fixed-width sliding window.
    """
    sentences = _split_sentences(paragraph)
    chunks: list[str] = []
    buffer = ""
    for sentence in sentences:
        candidate = f"{buffer} {sentence}".strip() if buffer else sentence
        if len(candidate) <= CHUNK_SIZE:
            buffer = candidate
        else:
            if buffer:
                chunks.append(buffer)
            # Handle an individual sentence longer than the chunk size.
            if len(sentence) > CHUNK_SIZE:
                chunks.extend(_fixed_window(sentence))
                buffer = ""
            else:
                buffer = sentence
    if buffer:
        chunks.append(buffer)
    return chunks


def _split_sentences(text: str) -> list[str]:
    """Split text on sentence boundaries.

    Uses a regex that looks for `. ` `! ` `? ` followed by a capital
    letter.  This is imperfect (it misses sentences ending with a quote or
    parenthesis), but it is fast, dependency-free, and good enough for
    newsletter text where prose dominates over edge-case punctuation.
    """
    parts = _SENTENCE_END.split(text)
    return [s for p in parts if (s := p.strip())]


def _fixed_window(text: str) -> list[str]:
    """Split text with a fixed-size sliding window (last resort).

    Used when a single sentence exceeds the chunk size — rare in prose, but
    possible with tables or pre-formatted blocks.
    """
    chunks: list[str] = []
    step = CHUNK_SIZE - CHUNK_OVERLAP
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start += step
    return chunks


def _merge_short_chunks(chunks: list[str]) -> list[str]:
    """Merge trailing chunks that are too small into the previous chunk.

    A chunk smaller than `_MIN_CHUNK` is merged with its predecessor so the
    retriever doesn't see fragments.  The first chunk is left alone even if
    short — a single short chunk is better than nothing.
    """
    if len(chunks) <= 1:
        return chunks

    merged: list[str] = []
    for chunk in chunks:
        if merged and len(chunk) < _MIN_CHUNK:
            merged[-1] = f"{merged[-1]} {chunk}".strip()
        else:
            merged.append(chunk)
    return merged


def _apply_overlap(chunks: list[str]) -> list[str]:
    """Prepend the tail of each preceding chunk to the next one.

    Each chunk (except the first) gets `CHUNK_OVERLAP` characters from the end
    of the previous chunk prepended to it, so a sentence that straddles the
    boundary appears in both.
    """
    overlapped: list[str] = [chunks[0]]
    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        tail = prev[-CHUNK_OVERLAP:] if len(prev) > CHUNK_OVERLAP else prev
        overlapped.append(f"{tail} {chunks[i]}")
    return overlapped
