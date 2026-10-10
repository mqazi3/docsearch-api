from evaluation.labels import Heading, control_pages, find_headings
from evaluation.metrics import first_relevant_rank, hit_at_k, percentile, reciprocal_rank


def test_rank_and_ranking_metrics():
    rank = first_relevant_rank([107, 117, 44, 45], relevant={44, 45})

    assert rank == 3
    assert hit_at_k(rank, 1) == 0.0
    assert hit_at_k(rank, 5) == 1.0
    assert reciprocal_rank(rank) == 1 / 3
    assert first_relevant_rank([1, 2], relevant={9}) is None
    assert reciprocal_rank(None) == 0.0


def test_percentile_uses_nearest_rank():
    values = [40, 10, 30, 20]
    assert percentile(values, 50) == 20
    assert percentile(values, 95) == 40
    assert percentile([], 50) == 0.0


def test_find_headings_keeps_first_occurrence_and_skips_non_headings():
    chunks = [
        (
            44,
            50,
            "03.05.02 Device Identification and Authentication\ntext\n"
            "03.05.03 Multi-Factor Authentication",
        ),
        (107, 137, "CUI 03.05.03\n03.06.02 03.06.02.b [Assignment: frequency]"),
        (116, 153, "03.05.03 Multi-Factor Authentication"),
    ]

    headings = find_headings(chunks)

    assert [(h.control, h.page) for h in headings] == [("03.05.02", 44), ("03.05.03", 44)]


def test_find_headings_ignores_table_of_contents_lines():
    assert find_headings([(5, 1, "03.01.01 Account Management ........ 5")]) == []


def test_control_pages_span_until_next_heading():
    headings = [
        Heading("03.05.02", "Device", 44, (50, 0)),
        Heading("03.05.03", "MFA", 44, (50, 9)),
        Heading("03.05.07", "Passwords", 46, (52, 4)),
    ]

    pages = control_pages(headings)

    assert pages["03.05.02"] == {44}
    assert pages["03.05.03"] == {44, 45, 46}
    assert pages["03.05.07"] == {46}


def test_find_headings_skips_stray_earlier_mentions():
    chunks = [
        (15, 10, "requirements such as\n03.13.11 Cryptographic Protection is discussed later"),
        (
            71,
            78,
            "03.13.10 Cryptographic Key Establishment\ntext\n03.13.11 Cryptographic Protection",
        ),
    ]

    headings = find_headings(chunks)

    assert [(h.control, h.page) for h in headings] == [("03.13.10", 71), ("03.13.11", 71)]
