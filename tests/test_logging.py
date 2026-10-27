import json
import logging
import sys

import pytest

from app.logging_setup import JsonFormatter, request_id_var

pytestmark = pytest.mark.unit


def make_record(message="hello", args=(), level=logging.INFO, exc_info=None):
    return logging.LogRecord("app.test", level, __file__, 1, message, args, exc_info)


def test_timestamp_is_utc_and_request_id_is_logged():
    record = make_record("hello %s", ("world",))
    record.created = 0
    token = request_id_var.set("trace-12345678")
    try:
        line = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert line["ts"] == "1970-01-01T00:00:00Z"
    assert line["request_id"] == "trace-12345678"
    assert line["message"] == "hello world"


def test_context_and_exception_are_included():
    try:
        raise ValueError("boom")
    except ValueError:
        record = make_record("failed", level=logging.ERROR, exc_info=sys.exc_info())
    record.context = {"user_id": 7}
    line = json.loads(JsonFormatter().format(record))
    assert line["context"] == {"user_id": 7}
    assert "ValueError: boom" in line["exc"]
