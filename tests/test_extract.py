from app.ingestion.extract import normalize_text


def test_normalizes_windows_line_endings():
    assert normalize_text("a\r\n\r\n\r\nb") == "a\n\nb"


def test_strips_nul_characters_and_extra_spaces():
    assert normalize_text("a\x00b   c") == "ab c"
