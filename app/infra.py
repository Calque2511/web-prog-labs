import json
import logging
import uuid
from typing import Protocol

import redis

from app.schemas import UserOut

logger = logging.getLogger("app.infra")


def make_redis(url: str | None) -> redis.Redis:
    if url:
        return redis.Redis.from_url(url, decode_responses=True)
    import fakeredis

    return fakeredis.FakeRedis(decode_responses=True)


class UserCache:
    def __init__(self, client: redis.Redis, ttl_seconds: int):
        self.client = client
        self.ttl = ttl_seconds
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(user_id: int) -> str:
        return f"user:{user_id}"

    def get(self, user_id: int) -> UserOut | None:
        raw = self.client.get(self.key(user_id))
        if raw is None:
            self.misses += 1
            return None
        self.hits += 1
        return UserOut.model_validate_json(raw)

    def set(self, user: UserOut) -> None:
        self.client.set(self.key(user.id), user.model_dump_json(), ex=self.ttl)

    def invalidate(self, user_id: int) -> None:
        self.client.delete(self.key(user_id))


class EmailSender(Protocol):
    def send(self, to: str, subject: str) -> None: ...


class LogEmailSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, to: str, subject: str) -> None:
        self.sent.append((to, subject))
        logger.info("email sent", extra={"context": {"subject": subject}})


class EmailQueue:
    KEY = "queue:emails"

    def __init__(self, client: redis.Redis):
        self.client = client

    def enqueue(self, to: str, subject: str, message_id: str | None = None) -> str:
        message_id = message_id or uuid.uuid4().hex
        self.client.rpush(self.KEY, json.dumps({"id": message_id, "to": to, "subject": subject}))
        return message_id

    def size(self) -> int:
        return int(self.client.llen(self.KEY))

    def pop(self) -> dict | None:
        raw = self.client.lpop(self.KEY)
        return json.loads(raw) if raw else None


class EmailWorker:
    def __init__(self, queue: EmailQueue, sender: EmailSender, dedup_ttl: int = 86400):
        self.queue = queue
        self.sender = sender
        self.dedup_ttl = dedup_ttl

    def handle(self, message: dict) -> bool:
        # nx=True: сообщение с тем же id второй раз не обработается
        first_time = self.queue.client.set(f"processed:{message['id']}", "1", nx=True, ex=self.dedup_ttl)
        if not first_time:
            logger.info("duplicate message skipped", extra={"context": {"id": message["id"]}})
            return False
        try:
            self.sender.send(message["to"], message["subject"])
        except Exception:
            self.queue.client.delete(f"processed:{message['id']}")  # чтобы повторить позже
            self.queue.client.rpush(self.queue.KEY, json.dumps(message))
            raise
        return True

    def drain(self) -> int:
        done = 0
        while (msg := self.queue.pop()) is not None:
            done += int(self.handle(msg))
        return done
