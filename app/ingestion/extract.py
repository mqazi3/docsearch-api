import io
import re
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class IngestionError(Exception):
    """A permanent problem with the document itself. Retrying will not help."""


@dataclass(frozen=True)
class Page:
    number: int | None  # None for plain-text files, which have no pages
    text: str


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")  # Windows / old Mac line endings
    text = text.replace("\x00", "")  # Postgres text columns reject NUL characters
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pages(data: bytes, content_type: str) -> list[Page]:
    if content_type == "application/pdf":
        return _extract_pdf(data)
    if content_type in {"text/plain", "text/markdown"}:
        return [Page(number=None, text=normalize_text(data.decode("utf-8")))]
    raise IngestionError(f"Unsupported content type: {content_type}")


def _extract_pdf(data: bytes) -> list[Page]:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise IngestionError("Encrypted PDFs are not supported")
        return [
            Page(number=i, text=normalize_text(page.extract_text() or ""))
            for i, page in enumerate(reader.pages, start=1)
        ]
    except PdfReadError as exc:
        raise IngestionError(f"Could not read PDF: {exc}") from exc
