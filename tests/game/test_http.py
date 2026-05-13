"""Tests for the shared HTTP helper in game/_http.py."""

import logging

import httpx
import pytest
from pytest_httpx import HTTPXMock

from game._http import fetch_json, retry_request

URL = "http://localhost:9999/thing"


# --- retry_request ---

async def test_retry_request_success_first_try(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=URL, json={"ok": True})
    async with httpx.AsyncClient() as http:
        logger = logging.getLogger("test")
        resp = await retry_request(
            "TEST", lambda: http.get(URL), attempts=2, backoff_seconds=0.0, logger=logger
        )
    assert resp is not None
    assert resp.status_code == 200


async def test_retry_request_retries_then_succeeds(httpx_mock: HTTPXMock):
    httpx_mock.add_exception(httpx.ConnectError("refused"))
    httpx_mock.add_response(url=URL, json={"ok": True})
    async with httpx.AsyncClient() as http:
        logger = logging.getLogger("test")
        resp = await retry_request(
            "TEST", lambda: http.get(URL), attempts=2, backoff_seconds=0.0, logger=logger
        )
    assert resp is not None
    assert resp.status_code == 200


async def test_retry_request_exhausts_returns_none(httpx_mock: HTTPXMock):
    for _ in range(3):
        httpx_mock.add_exception(httpx.ConnectError("refused"))
    async with httpx.AsyncClient() as http:
        logger = logging.getLogger("test")
        resp = await retry_request(
            "TEST", lambda: http.get(URL), attempts=2, backoff_seconds=0.0, logger=logger
        )
    assert resp is None


async def test_retry_request_timeout_also_retried(httpx_mock: HTTPXMock):
    httpx_mock.add_exception(httpx.TimeoutException("timed out"))
    httpx_mock.add_response(url=URL, json={"ok": True})
    async with httpx.AsyncClient() as http:
        logger = logging.getLogger("test")
        resp = await retry_request(
            "TEST", lambda: http.get(URL), attempts=2, backoff_seconds=0.0, logger=logger
        )
    assert resp is not None


async def test_retry_request_does_not_retry_on_non_2xx(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=URL, status_code=500, text="boom")
    async with httpx.AsyncClient() as http:
        logger = logging.getLogger("test")
        resp = await retry_request(
            "TEST", lambda: http.get(URL), attempts=2, backoff_seconds=0.0, logger=logger
        )
    assert resp is not None
    assert resp.status_code == 500
    assert len(httpx_mock.get_requests()) == 1


# --- fetch_json ---

async def test_fetch_json_success(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=URL, json={"hello": "world"})
    async with httpx.AsyncClient() as http:
        logger = logging.getLogger("test")
        result = await fetch_json(
            label="TEST",
            bad_status_label="TEST API",
            coro_factory=lambda: http.get(URL),
            attempts=0,
            backoff_seconds=0.0,
            logger=logger,
        )
    assert result == {"hello": "world"}


async def test_fetch_json_non_2xx_returns_none_and_logs_body(
    httpx_mock: HTTPXMock, caplog: pytest.LogCaptureFixture
):
    httpx_mock.add_response(url=URL, status_code=400, text="bad request body")
    async with httpx.AsyncClient() as http:
        test_logger = logging.getLogger("game._http.test")
        with caplog.at_level(logging.WARNING, logger="game._http.test"):
            result = await fetch_json(
                label="TEST",
                bad_status_label="TEST API",
                coro_factory=lambda: http.get(URL),
                attempts=0,
                backoff_seconds=0.0,
                logger=test_logger,
            )
    assert result is None
    # Standardized: GET and POST both log the response body
    assert "bad request body" in caplog.text
    assert "400" in caplog.text


async def test_fetch_json_transient_failure_returns_none(httpx_mock: HTTPXMock):
    httpx_mock.add_exception(httpx.ConnectError("refused"))
    async with httpx.AsyncClient() as http:
        logger = logging.getLogger("test")
        result = await fetch_json(
            label="TEST",
            bad_status_label="TEST API",
            coro_factory=lambda: http.get(URL),
            attempts=0,
            backoff_seconds=0.0,
            logger=logger,
        )
    assert result is None


async def test_fetch_json_uses_provided_logger(
    httpx_mock: HTTPXMock, caplog: pytest.LogCaptureFixture
):
    """Verifies each client preserves its own logger name (not game._http)."""
    httpx_mock.add_response(url=URL, status_code=500, text="oops")
    named_logger = logging.getLogger("game.api_client.fake")
    async with httpx.AsyncClient() as http:
        with caplog.at_level(logging.WARNING, logger="game.api_client.fake"):
            await fetch_json(
                label="X",
                bad_status_label="X API",
                coro_factory=lambda: http.get(URL),
                attempts=0,
                backoff_seconds=0.0,
                logger=named_logger,
            )
    # Confirm the record came from the caller-supplied logger
    assert any(r.name == "game.api_client.fake" for r in caplog.records)
