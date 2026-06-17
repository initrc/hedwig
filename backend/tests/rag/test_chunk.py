"""Tests for `app.rag.chunk` — the text chunker.

No real embeddings or API calls needed here — the chunker is pure text
processing.  The tests verify that paragraphs are split at the right boundaries,
overlap is applied, and edge cases (empty text, tiny paragraphs) are handled.
"""

from app.rag.chunk import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    _apply_overlap,
    _merge_short_chunks,
    _split_paragraphs,
    _split_sentences,
    chunk_text,
)

# -- paragraph splitting -----------------------------------------------------


def test_split_paragraphs_breaks_on_blank_lines() -> None:
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    result = _split_paragraphs(text)
    assert result == ["First paragraph.", "Second paragraph.", "Third paragraph."]


def test_split_paragraphs_handles_multiple_blank_lines() -> None:
    text = "A\n\n\n\nB"
    result = _split_paragraphs(text)
    assert result == ["A", "B"]


def test_split_paragraphs_returns_single_item_for_no_blank_lines() -> None:
    text = "Line one.\nLine two.\nLine three."
    result = _split_paragraphs(text)
    assert result == [text]


def test_split_paragraphs_strips_trailing_empty() -> None:
    text = "Only paragraph.\n\n"
    result = _split_paragraphs(text)
    assert result == ["Only paragraph."]


# -- sentence splitting ------------------------------------------------------


def test_split_sentences_breaks_on_period_space_capital() -> None:
    text = "First sentence. Second sentence. Third sentence."
    result = _split_sentences(text)
    assert result == ["First sentence.", "Second sentence.", "Third sentence."]


def test_split_sentences_handles_exclamation_and_question() -> None:
    text = "Wow! Really? Yes."
    result = _split_sentences(text)
    assert result == ["Wow!", "Really?", "Yes."]


def test_split_sentences_single_sentence_returns_itself() -> None:
    text = "Just one sentence here."
    result = _split_sentences(text)
    assert result == [text]


# -- chunk_text (integration) ------------------------------------------------


def test_chunk_text_returns_empty_for_empty_input() -> None:
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_chunk_text_short_text_returns_single_chunk() -> None:
    text = "A short newsletter blurb about interest rates."
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_text_respects_paragraph_boundaries() -> None:
    para1 = "First paragraph with some content." * 10  # ~350 chars
    para2 = "Second paragraph with different content." * 10
    text = f"{para1}\n\n{para2}"
    chunks = chunk_text(text)
    # Each paragraph is under CHUNK_SIZE, so they stay separate.
    assert len(chunks) == 2
    assert chunks[0].strip() == para1
    assert chunks[1].strip().startswith(para1[-CHUNK_OVERLAP:])


def test_chunk_text_long_paragraph_is_split() -> None:
    # Create a paragraph longer than CHUNK_SIZE with clear sentence breaks.
    sentence = "This is sentence number {n} about market conditions. "
    long_para = "".join(sentence.format(n=i) for i in range(100))
    assert len(long_para) > CHUNK_SIZE

    chunks = chunk_text(long_para)
    assert len(chunks) > 1
    # Every chunk should respect the size limit plus the prepended overlap.
    for chunk in chunks:
        assert len(chunk) <= CHUNK_SIZE + CHUNK_OVERLAP, (
            f"chunk too long: {len(chunk)} chars"
        )


def test_chunk_text_applies_overlap() -> None:
    para1 = "A" * 2040
    para2 = "B" * 2040
    text = f"{para1}\n\n{para2}"
    chunks = chunk_text(text)
    assert len(chunks) == 2
    # Second chunk should start with the tail of the first.
    assert chunks[1].startswith(para1[-CHUNK_OVERLAP:])


# -- _merge_short_chunks -----------------------------------------------------


def test_merge_short_chunks_merges_tiny_trailing() -> None:
    chunks = ["A" * 1000, "tiny"]
    result = _merge_short_chunks(chunks)
    assert len(result) == 1
    assert result[0] == f"{chunks[0]} tiny"


def test_merge_short_chunks_leaves_first_short_alone() -> None:
    chunks = ["tiny", "A" * 1000]
    result = _merge_short_chunks(chunks)
    assert len(result) == 2
    assert result[0] == "tiny"


def test_merge_short_chunks_preserves_single_chunk() -> None:
    assert _merge_short_chunks(["only"]) == ["only"]


# -- _apply_overlap ----------------------------------------------------------


def test_apply_overlap_prepends_tail_of_long_prev() -> None:
    """When prev is longer than CHUNK_OVERLAP, only its last N chars are prepended."""
    prev = "A" * 1000
    curr = "B" * 100
    result = _apply_overlap([prev, curr])
    assert len(result) == 2
    assert result[0] == prev
    # Second chunk starts with only the tail, not all of prev.
    tail = prev[-CHUNK_OVERLAP:]
    assert result[1].startswith(tail)
    # The full prev should not be in the second chunk.
    assert not result[1].startswith(prev)


def test_apply_overlap_prepends_whole_prev_when_short() -> None:
    """When prev is shorter than CHUNK_OVERLAP, the whole prev is prepended."""
    prev = "short"
    curr = "longer chunk here"
    assert len(prev) < CHUNK_OVERLAP
    result = _apply_overlap([prev, curr])
    assert len(result) == 2
    assert result[1].startswith(prev)
