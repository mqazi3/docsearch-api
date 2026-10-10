import re
from collections.abc import Iterable
from dataclasses import dataclass

# A control heading on its own line, e.g. "03.05.07 Password Management".
# The title must start with a capital letter, which excludes appendix table rows
# like "03.06.02 03.06.02.b [Assignment: ...]".
HEADING = re.compile(r"^(03\.\d{2}\.\d{2}) ([A-Z].*)$")


@dataclass(frozen=True)
class Heading:
    control: str
    title: str
    page: int
    position: tuple[int, int]  # (chunk_index, line number): order within a page


def find_headings(chunks: Iterable[tuple[int | None, int, str]]) -> list[Heading]:
    """Locate each control's real heading.

    Headings appear in control-ID order, so their pages never decrease. For each control
    (in ID order) take the earliest heading-shaped line at or after the previous control's
    page. This skips stray mentions in earlier chapters whose line wrapping makes them
    look like headings. `chunks` must be in document order.
    """
    occurrences: dict[str, list[Heading]] = {}
    for page, chunk_index, content in chunks:
        if page is None:
            continue
        for line_no, raw in enumerate(content.split("\n")):
            line = raw.strip()
            if "...." in line:  # table-of-contents dot leaders
                continue
            match = HEADING.match(line)
            if match:
                occurrences.setdefault(match.group(1), []).append(
                    Heading(match.group(1), match.group(2), page, (chunk_index, line_no))
                )

    headings: list[Heading] = []
    last_page = 0
    for control in sorted(occurrences):  # zero-padded IDs sort in document order
        candidates = [h for h in occurrences[control] if h.page >= last_page]
        if not candidates:
            continue
        chosen = min(candidates, key=lambda h: (h.page, h.position))
        headings.append(chosen)
        last_page = chosen.page
    return sorted(headings, key=lambda h: (h.page, h.position))


def control_pages(headings: list[Heading]) -> dict[str, set[int]]:
    """Each control spans from its heading's page through the page where the next one starts."""
    pages: dict[str, set[int]] = {}
    for i, heading in enumerate(headings):
        end = headings[i + 1].page if i + 1 < len(headings) else heading.page
        pages[heading.control] = set(range(heading.page, end + 1))
    return pages
