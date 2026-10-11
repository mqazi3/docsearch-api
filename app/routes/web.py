import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.config import Settings, get_settings

router = APIRouter(include_in_schema=False)

PAGE_PATH = Path(__file__).resolve().parent.parent / "static" / "index.html"
KEY_PLACEHOLDER = "__DEMO_KEY__"


@lru_cache
def _page_template() -> str:
    return PAGE_PATH.read_text(encoding="utf-8")


@router.get("/", response_class=HTMLResponse)
def landing_page(settings: Settings = Depends(get_settings)) -> HTMLResponse:
    """Demo page. The public demo key is a reader key: rate-limited and unable to upload."""
    key = settings.public_demo_key.get_secret_value() if settings.public_demo_key else ""
    key = key.strip() or None  # unset and empty both mean "demo off"
    # json.dumps produces a valid JS string literal (or null). Escaping "</" keeps the
    # value from closing the surrounding <script> tag.
    literal = json.dumps(key).replace("</", "<\\/")
    page = _page_template().replace(KEY_PLACEHOLDER, literal)
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})
