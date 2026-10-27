from unittest.mock import Mock, call

import pytest
from sqlalchemy.exc import IntegrityError

from app.errors import BusinessRuleError, ConflictError, NotFoundError
from app.infra import EmailQueue, EmailWorker, LogEmailSender, UserCache, make_redis
from app.models import User
from app.schemas import UserCreate, UserOut, UserPatch
from app.services.users import UserService

pytestmark = pytest.mark.unit


@pytest.fixture
def repo():
    r = Mock()
    r.email_exists.return_value = False
    r.get.return_value = None
    return r


@pytest.fixture
def queue():
    return Mock(spec=EmailQueue)


@pytest.fixture
def service(repo, queue):
    return UserService(repo, queue, cache=None, bcrypt_rounds=4)


def data(**over):
    base = dict(name="John Doe", email="John@Example.com", age=30, password="Secret123")
    return UserCreate(**{**base, **over})


def _stored(user: User) -> User:
    user.id, user.role = 7, "user"
    from datetime import datetime

    user.created_at = datetime(2024, 1, 1)
    return user


def test_create_user_saves_hashed_password_lowercases_email_and_enqueues_welcome(service, repo, queue):
    repo.add.side_effect = _stored
    out = service.create_user(data())

    saved: User = repo.add.call_args.args[0]
    assert saved.email == "john@example.com"
    assert saved.password_hash.startswith("$2") and "Secret123" not in saved.password_hash
    repo.commit.assert_called_once()
    queue.enqueue.assert_called_once_with("john@example.com", "Welcome!")
    assert out.id == 7 and out.email == "john@example.com"


def test_create_user_duplicate_email_does_not_touch_db_or_queue(service, repo, queue):
    repo.email_exists.return_value = True
    with pytest.raises(ConflictError):
        service.create_user(data())
    repo.add.assert_not_called()
    queue.enqueue.assert_not_called()


def test_create_user_race_on_unique_constraint_becomes_conflict(service, repo, queue):
    repo.add.side_effect = _stored
    repo.commit.side_effect = IntegrityError("INSERT", {}, Exception("dup"))
    with pytest.raises(ConflictError):
        service.create_user(data())
    repo.rollback.assert_called_once()
    queue.enqueue.assert_not_called()


@pytest.mark.parametrize(
    "over", [{"name": "Super Admin"}, {"email": "secret12@x.com", "password": "secret12"}]
)
def test_create_user_business_rules(service, repo, over):
    with pytest.raises(BusinessRuleError):
        service.create_user(data(**over))
    repo.add.assert_not_called()


def test_get_missing_user_raises_not_found(service, repo):
    with pytest.raises(NotFoundError):
        service.get_user(1)
    repo.get.assert_called_once_with(1)


def test_patch_only_changes_provided_fields_and_checks_email_uniqueness(service, repo):
    repo.get.return_value = _stored(User(name="A b", email="a@x.com", age=20, password_hash="h"))
    out = service.patch_user(7, UserPatch(age=33))
    assert (out.age, out.name) == (33, "A b")

    repo.email_exists.return_value = True
    with pytest.raises(ConflictError):
        service.patch_user(7, UserPatch(email="taken@x.com"))
    repo.email_exists.assert_called_with("taken@x.com", exclude_id=7)


def test_delete_removes_user_and_invalidates_cache(repo, queue):
    cache = Mock(spec=UserCache)
    svc = UserService(repo, queue, cache, 4)
    user = _stored(User(name="A b", email="a@x.com", age=20, password_hash="h"))
    repo.get.return_value = user
    svc.delete_user(7)
    assert repo.method_calls == [call.get(7), call.delete(user), call.commit()]
    cache.invalidate.assert_called_once_with(7)


def test_cache_aside_hits_after_first_read_and_invalidates_on_update(repo, queue):
    cache = UserCache(make_redis(None), ttl_seconds=60)
    svc = UserService(repo, queue, cache, 4)
    repo.get.return_value = _stored(User(name="A b", email="a@x.com", age=20, password_hash="h"))

    svc.get_user(7)
    svc.get_user(7)
    assert repo.get.call_count == 1 and (cache.hits, cache.misses) == (1, 1)

    svc.patch_user(7, UserPatch(age=40))
    assert cache.get(7) is None
    assert isinstance(svc.get_user(7), UserOut)


def test_cache_entry_expires_by_ttl():
    redis = make_redis(None)
    cache = UserCache(redis, ttl_seconds=60)
    from datetime import datetime

    cache.set(
        UserOut(id=1, name="A b", email="a@x.com", age=20, role="user", created_at=datetime(2024, 1, 1))
    )
    assert 0 < redis.ttl("user:1") <= 60


def test_worker_sends_each_message_once_even_if_delivered_twice():
    queue = EmailQueue(make_redis(None))
    sender = LogEmailSender()
    worker = EmailWorker(queue, sender)
    queue.enqueue("a@x.com", "Hi", message_id="m1")
    queue.enqueue("a@x.com", "Hi", message_id="m1")  # повторная доставка
    queue.enqueue("b@x.com", "Hi", message_id="m2")
    assert worker.drain() == 2
    assert sender.sent == [("a@x.com", "Hi"), ("b@x.com", "Hi")]
    assert queue.size() == 0


def test_worker_requeues_message_when_sender_fails_then_succeeds_on_retry():
    queue = EmailQueue(make_redis(None))
    sender = Mock()
    sender.send.side_effect = [RuntimeError("smtp down"), None]
    worker = EmailWorker(queue, sender)
    queue.enqueue("a@x.com", "Hi", message_id="m1")
    with pytest.raises(RuntimeError):
        worker.drain()
    assert queue.size() == 1  # сообщение не потеряно
    assert worker.drain() == 1 and sender.send.call_count == 2
