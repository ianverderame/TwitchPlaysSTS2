import httpx
import pytest
from pytest_httpx import HTTPXMock

from game.api_client import STS2Client

BASE_URL = "http://localhost:15526"
ENDPOINT = f"{BASE_URL}/api/v1/singleplayer"


@pytest.fixture
def client() -> STS2Client:
    return STS2Client(base_url=BASE_URL)


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
