import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import lru_cache

import tiktoken

from app.ingestion.extract import Page

# A numbered section heading at the start of a line, e.g. "03.05.03 Multi-Factor ...",
# "3.5. Identification and Authentication", "2.1 Purpose". The capital letter after the
# number excludes table rows like "03.06.02 03.06.02.b [Assignment: ...]".
NUMBERED_HEADING = re.compile(r"^\d+(?:\.\d+)+\.?\s+[A-Z]")


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


def split_sections(text: str) -> list[str]:
    """Split text so each numbered heading starts a new section."""
    sections: list[list[str]] = [[]]
    for line in text.split("\n"):
        if NUMBERED_HEADING.match(line.strip()) and any(s.strip() for s in sections[-1]):
            sections.append([])
        sections[-1].append(line)
    return [joined for s in sections if (joined := "\n".join(s).strip())]


def _windows(tokens: list[int], chunk_size: int, step: int) -> Iterator[list[int]]:
    start = 0
    while start < len(tokens):
        yield tokens[start : start + chunk_size]
        if start + chunk_size >= len(tokens):
            break
        start += step


def chunk_pages(
    pages: Iterable[Page],
    chunk_size: int,
    overlap: int,
    split_on_headings: bool = False,
) -> list[TextChunk]:
    """Split pages into overlapping token windows. Chunks never cross pages, and with
    split_on_headings they also never cross a numbered section heading."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not 0 <= overlap < chunk_size:
        raise ValueError("overlap must be >= 0 and smaller than chunk_size")

    encoding = _encoding()
    step = chunk_size - overlap
    chunks: list[TextChunk] = []

    for page in pages:
        segments = split_sections(page.text) if split_on_headings else [page.text]
        for segment in segments:
            # disallowed_special=() treats text like "<|endoftext|>" as ordinary text.
            tokens = encoding.encode(segment, disallowed_special=())
            for window in _windows(tokens, chunk_size, step):
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
    return chunks
