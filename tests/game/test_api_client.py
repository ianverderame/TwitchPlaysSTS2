import httpx
import pytest
from pytest_httpx import HTTPXMock

from game.api_client import STS2Client

BASE_URL = "http://localhost:15526"
ENDPOINT = f"{BASE_URL}/api/v1/singleplayer"


@pytest.fixture
def client() -> STS2Client:
    """No-retry client for straightforward success/error tests."""
    return STS2Client(base_url=BASE_URL, http_retry_attempts=0)


@pytest.fixture
def retrying_client() -> STS2Client:
    """Client with 2 retries and zero backoff for retry behaviour tests."""
    return STS2Client(base_url=BASE_URL, http_retry_attempts=2, http_retry_backoff_seconds=0.0)


# --- get_state ---

async def test_get_state_success(client: STS2Client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=ENDPOINT, json={"state_type": "menu"})
    result = await client.get_state()
    assert result == {"state_type": "menu"}


async def test_get_state_non_2xx_returns_none(client: STS2Client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=ENDPOINT, status_code=500)
    result = await client.get_state()
    assert result is None


async def test_get_state_connect_error_returns_none(client: STS2Client, httpx_mock: HTTPXMock):
    httpx_mock.add_exception(httpx.ConnectError("refused"))
    result = await client.get_state()
    assert result is None


async def test_get_state_timeout_returns_none(client: STS2Client, httpx_mock: HTTPXMock):
    httpx_mock.add_exception(httpx.TimeoutException("timed out"))
    result = await client.get_state()
    assert result is None


async def test_get_state_404_returns_none(client: STS2Client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=ENDPOINT, status_code=404)
    result = await client.get_state()
    assert result is None


# --- post_action ---

async def test_post_action_success(client: STS2Client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=ENDPOINT, method="POST", json={"status": "ok"})
    result = await client.post_action({"action": "end_turn"})
    assert result == {"status": "ok"}


async def test_post_action_sends_correct_body(client: STS2Client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=ENDPOINT, method="POST", json={"status": "ok"})
    await client.post_action({"action": "play_card", "card_index": 0})
    request = httpx_mock.get_request()
    import json
    body = json.loads(request.content)
    assert body == {"action": "play_card", "card_index": 0}


async def test_post_action_non_2xx_returns_none(client: STS2Client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=ENDPOINT, method="POST", status_code=400, text="bad request")
    result = await client.post_action({"action": "end_turn"})
    assert result is None


async def test_post_action_connect_error_returns_none(client: STS2Client, httpx_mock: HTTPXMock):
    httpx_mock.add_exception(httpx.ConnectError("refused"))
    result = await client.post_action({"action": "end_turn"})
    assert result is None


async def test_post_action_timeout_returns_none(client: STS2Client, httpx_mock: HTTPXMock):
    httpx_mock.add_exception(httpx.TimeoutException("timed out"))
    result = await client.post_action({"action": "end_turn"})
    assert result is None


# --- retry with exponential backoff ---

async def test_get_state_retries_on_connect_error_then_succeeds(
    retrying_client: STS2Client, httpx_mock: HTTPXMock
):
    """First attempt fails with ConnectError; second succeeds."""
    httpx_mock.add_exception(httpx.ConnectError("refused"))
    httpx_mock.add_response(url=ENDPOINT, json={"state_type": "menu"})
    result = await retrying_client.get_state()
    assert result == {"state_type": "menu"}


async def test_get_state_exhausts_retries_returns_none(
    retrying_client: STS2Client, httpx_mock: HTTPXMock
):
    """All 3 attempts (1 initial + 2 retries) raise ConnectError — should return None."""
    for _ in range(3):
        httpx_mock.add_exception(httpx.ConnectError("refused"))
    result = await retrying_client.get_state()
    assert result is None


async def test_post_action_retries_on_timeout_then_succeeds(
    retrying_client: STS2Client, httpx_mock: HTTPXMock
):
    """First attempt times out; second succeeds."""
    httpx_mock.add_exception(httpx.TimeoutException("timed out"))
    httpx_mock.add_response(url=ENDPOINT, method="POST", json={"status": "ok"})
    result = await retrying_client.post_action({"action": "end_turn"})
    assert result == {"status": "ok"}


async def test_post_action_does_not_retry_on_http_error(
    retrying_client: STS2Client, httpx_mock: HTTPXMock
):
    """HTTP 500 is not a transient failure — no retry, returns None immediately."""
    httpx_mock.add_response(url=ENDPOINT, method="POST", status_code=500, text="error")
    result = await retrying_client.post_action({"action": "end_turn"})
    assert result is None
    assert len(httpx_mock.get_requests()) == 1  # exactly one attempt


# --- dry_run mode ---

async def test_post_action_dry_run_skips_http(httpx_mock: HTTPXMock):
    dry_client = STS2Client(base_url=BASE_URL, dry_run=True)
    result = await dry_client.post_action({"action": "end_turn"})
    assert result is not None
    assert result["status"] == "ok"
    assert "[DRY RUN]" in result["message"]
    assert httpx_mock.get_requests() == []


async def test_get_state_still_works_in_dry_run(httpx_mock: HTTPXMock):
    dry_client = STS2Client(base_url=BASE_URL, dry_run=True)
    httpx_mock.add_response(url=ENDPOINT, json={"state_type": "monster"})
    result = await dry_client.get_state()
    assert result == {"state_type": "monster"}
