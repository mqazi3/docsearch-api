from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

import tiktoken

from app.ingestion.extract import Page


@dataclass(frozen=True)
class TextChunk:
    index: int
    content: str
    page_number: int | None
    token_count: int


@lru_cache
def _encoding() -> tiktoken.Encoding:
    # The same tokenizer text-embedding-3-small uses, so token counts are exact.
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_encoding().encode(text, disallowed_special=()))


def chunk_pages(pages: Iterable[Page], chunk_size: int, overlap: int) -> list[TextChunk]:
    """Split each page into overlapping token windows. Chunks never cross pages."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not 0 <= overlap < chunk_size:
        raise ValueError("overlap must be >= 0 and smaller than chunk_size")

    encoding = _encoding()
    step = chunk_size - overlap
    chunks: list[TextChunk] = []

    for page in pages:
        # disallowed_special=() treats text like "<|endoftext|>" as ordinary text
        # instead of raising an error.
        tokens = encoding.encode(page.text, disallowed_special=())
        start = 0
        while start < len(tokens):
            window = tokens[start : start + chunk_size]
            content = encoding.decode(window).strip()
            if content:
                chunks.append(
                    TextChunk(
                        index=len(chunks),
                        content=content,
                        page_number=page.number,
                        token_count=len(window),
                    )
                )
            if start + chunk_size >= len(tokens):
                break
            start += step

    return chunks
