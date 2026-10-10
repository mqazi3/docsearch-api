import math

import pytest

from app.ingestion.chunking import _encoding, chunk_pages
from app.ingestion.extract import Page

LONG_TEXT = " ".join(f"control{i} requires documented procedures." for i in range(300))


def test_chunks_respect_size_and_expected_count():
    n_tokens = len(_encoding().encode(LONG_TEXT))
    chunks = chunk_pages([Page(number=1, text=LONG_TEXT)], chunk_size=50, overlap=10)

    assert all(c.token_count <= 50 for c in chunks)
    assert len(chunks) == 1 + math.ceil(max(0, n_tokens - 50) / 40)


def test_chunks_never_cross_pages_and_indexes_are_continuous():
    pages = [Page(number=1, text=LONG_TEXT), Page(number=2, text="Short second page.")]
    chunks = chunk_pages(pages, chunk_size=50, overlap=10)

    assert chunks[-1].page_number == 2
    assert chunks[-1].content == "Short second page."
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_empty_pages_are_skipped():
    pages = [Page(number=1, text=""), Page(number=2, text="Only real text.")]
    chunks = chunk_pages(pages, chunk_size=50, overlap=10)

    assert len(chunks) == 1
    assert chunks[0].page_number == 2


def test_invalid_overlap_is_rejected():
    with pytest.raises(ValueError):
        chunk_pages([Page(number=1, text="text")], chunk_size=50, overlap=50)


def test_special_token_text_is_treated_as_plain_text():
    chunks = chunk_pages([Page(number=None, text="<|endoftext|> still text")], 50, 10)
    assert "still text" in chunks[0].content
