from app.answering import best_excerpt

CHUNK = (
    "d. Designate organizational personnel with required access authorizations to supervise "
    "maintenance activities. Maintenance tools must be inspected for improper modifications. "
    "Diagnostic media must be checked for malicious code before use in the system. "
    "03.08.03 Media Sanitization. Sanitize system media that contain CUI prior to disposal, "
    "release out of organizational control, or release for reuse. Sanitization techniques "
    "include clearing, purging, cryptographic erase, and destruction."
)


def test_excerpt_picks_the_passage_that_matches_the_answer():
    answer = "Sanitize drives before disposal, for example by purging or cryptographic erase [1]."
    excerpt = best_excerpt(CHUNK, answer, limit=200)
    assert "cryptographic erase" in excerpt
    assert "maintenance" not in excerpt.lower()
    assert excerpt.startswith("…")
    assert len(excerpt) <= 202  # limit plus the two ellipsis characters


def test_excerpt_falls_back_to_the_start_without_overlap():
    excerpt = best_excerpt(CHUNK, "capital of France", limit=120)
    assert excerpt.startswith("d. Designate")
    assert excerpt.endswith("…")


def test_short_chunks_are_returned_whole():
    assert best_excerpt("Retain audit records.", "audit", limit=300) == "Retain audit records."
