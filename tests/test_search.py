import uuid

import pytest
import redis

from app.cache import get_redis
from app.config import get_settings
from app.db import SessionLocal
from app.embeddings import FakeEmbedder, get_embedder
from app.ingestion.pipeline import ingest_document
from app.main import app
from app.search import is_identifier_query, reciprocal_rank_fusion
from app.storage import get_storage
from tests.test_ingestion import make_document

DOCS = {
    "encryption.txt": "Encrypt data at rest using FIPS-validated cryptography to protect "
    "the confidentiality of controlled unclassified information.",
    "access.txt": "Limit system access to authorized users and processes acting on behalf "
    "of authorized users.",
    "audit.txt": "Create and retain system audit logs and records to enable monitoring, "
    "analysis, and investigation of unlawful activity.",
}


class CountingEmbedder(FakeEmbedder):
    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return super().embed(texts)


class BrokenCache:
    def get(self, key):
        raise redis.ConnectionError("simulated outage")

    def set(self, key, value, ex=None):
        raise redis.ConnectionError("simulated outage")


@pytest.fixture
def corpus():
    ids = {}
    for filename, text in DOCS.items():
        document_id = make_document(text.encode(), filename)
        ingest_document(document_id, SessionLocal, get_storage(), FakeEmbedder())
        ids[filename] = document_id
    return ids


def search(client, q, **params):
    response = client.get("/search", params={"q": q, **params})
    assert response.status_code == 200, response.text
    return response.json()


# --- Reciprocal rank fusion (pure function) ---


def test_rrf_ranks_items_found_by_both_methods_first():
    hits = reciprocal_rank_fusion([1, 2, 3], [3, 4])

    assert [h.chunk_id for h in hits] == [3, 1, 2, 4]
    assert (hits[0].vector_rank, hits[0].keyword_rank) == (3, 1)


def test_rrf_with_one_list_preserves_its_order():
    assert [h.chunk_id for h in reciprocal_rank_fusion([5, 6, 7], [])] == [5, 6, 7]


# --- Endpoint behavior ---


def test_keyword_search_finds_matching_document(client, corpus):
    body = search(client, "audit logs", mode="keyword")

    top = body["results"][0]
    assert top["filename"] == "audit.txt"
    assert top["keyword_rank"] == 1
    assert top["vector_rank"] is None
    assert body["took_ms"] >= 0


def test_keyword_search_matches_word_variants(client, corpus):
    # English stemming: "encrypting" matches "Encrypt".
    body = search(client, "encrypting", mode="keyword")
    assert body["results"][0]["filename"] == "encryption.txt"


def test_vector_search_ranks_identical_text_first(client, corpus):
    body = search(client, DOCS["access.txt"], mode="vector")

    assert body["results"][0]["filename"] == "access.txt"
    assert body["results"][0]["vector_rank"] == 1


def test_hybrid_search_combines_both_signals(client, corpus):
    body = search(client, DOCS["access.txt"])  # hybrid is the default

    top = body["results"][0]
    assert top["filename"] == "access.txt"
    assert top["vector_rank"] == 1
    assert top["keyword_rank"] == 1


def test_document_filter_limits_results(client, corpus):
    body = search(client, "system", mode="keyword", document_id=str(corpus["audit.txt"]))

    assert body["results"]
    assert {r["filename"] for r in body["results"]} == {"audit.txt"}


def test_no_matches_returns_empty_list(client, corpus):
    assert search(client, "zebra", mode="keyword")["results"] == []


def test_blank_query_is_rejected(client):
    assert client.get("/search", params={"q": "   "}).status_code == 422


def test_unknown_mode_is_rejected(client):
    assert client.get("/search", params={"q": "audit", "mode": "semantic"}).status_code == 422


def test_query_embedding_is_cached(client, corpus):
    embedder = CountingEmbedder()
    app.dependency_overrides[get_embedder] = lambda: embedder
    query = f"cache test {uuid.uuid4()}"  # unique, so no earlier run already cached it

    search(client, query, mode="vector")
    search(client, query, mode="vector")

    assert embedder.calls == 1


def test_search_still_works_when_cache_is_down(client, corpus):
    app.dependency_overrides[get_redis] = lambda: BrokenCache()

    body = search(client, DOCS["audit.txt"], mode="vector")

    assert body["results"][0]["filename"] == "audit.txt"


def test_unknown_document_filter_returns_404(client, corpus):
    response = client.get("/search", params={"q": "system", "document_id": str(uuid.uuid4())})
    assert response.status_code == 404


def test_hybrid_or_keyword_leg_matches_partial_terms(client, corpus, monkeypatch):
    monkeypatch.setattr(get_settings(), "hybrid_keyword_any", True)

    body = search(client, "how long should audit logs be kept")  # hybrid

    audit = next(r for r in body["results"] if r["filename"] == "audit.txt")
    assert audit["keyword_rank"] is not None


def test_keyword_mode_still_requires_all_terms(client, corpus, monkeypatch):
    monkeypatch.setattr(get_settings(), "hybrid_keyword_any", True)

    body = search(client, "how long should audit logs be kept", mode="keyword")

    assert body["results"] == []


def test_identifier_query_classification():
    assert is_identifier_query("03.05.03")
    assert is_identifier_query("IA-05(01)")
    assert is_identifier_query("  AC-2 ")
    assert not is_identifier_query("audit logs")
    assert not is_identifier_query("how long should audit logs be kept")
    assert not is_identifier_query("encryption")


def test_identifier_routing_skips_vector_leg(client, corpus, monkeypatch):
    monkeypatch.setattr(get_settings(), "identifier_routing", True)
    embedder = CountingEmbedder()
    app.dependency_overrides[get_embedder] = lambda: embedder
    mfa_text = b"Control 03.05.03 requires multi-factor authentication."
    document_id = make_document(mfa_text, "mfa.txt")
    ingest_document(document_id, SessionLocal, get_storage(), FakeEmbedder())

    body = search(client, "03.05.03")  # hybrid

    assert embedder.calls == 0
    assert all(r["vector_rank"] is None for r in body["results"])
    assert body["results"][0]["filename"] == "mfa.txt"
