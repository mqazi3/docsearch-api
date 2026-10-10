import uuid
from functools import lru_cache

import redis
from rq import Queue, Retry

from app.config import get_settings

INGESTION_QUEUE = "ingestion"


@lru_cache
def _rq_connection() -> redis.Redis:
    # RQ stores pickled job data, so this connection must NOT decode responses to str
    # (unlike the app's cache client).
    return redis.Redis.from_url(get_settings().redis_url)


class IngestionQueue:
    def __init__(self, queue: Queue) -> None:
        self.queue = queue

    def enqueue_ingestion(self, document_id: uuid.UUID) -> None:
        self.queue.enqueue(
            "app.tasks.process_document",
            str(document_id),
            job_timeout=600,
            retry=Retry(max=3, interval=[10, 30, 60]),
            description=f"ingest document {document_id}",
        )


def get_ingestion_queue() -> IngestionQueue:
    return IngestionQueue(Queue(INGESTION_QUEUE, connection=_rq_connection()))
