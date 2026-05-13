"""Shared HTTP helpers for STS2Client and MenuClient.

Both clients hit small local REST APIs with the same retry/unwrap shape:
- Retry on httpx.ConnectError / TimeoutException with exponential backoff
- Treat non-2xx as a soft failure (log + return None)
- Return parsed JSON on success

These helpers accept an explicit `logger` so each caller still logs under its
own module name, preserving existing log-scraping behavior.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx


async def retry_request(
    label: str,
    coro_factory: Callable[[], Awaitable[httpx.Response]],
    attempts: int,
    backoff_seconds: float,
    logger: logging.Logger,
) -> httpx.Response | None:
    """Execute coro_factory() with exponential backoff retry on transient failures.

    Retries up to `attempts` times on ConnectError or TimeoutException.
    Returns None when all attempts are exhausted.
    """
    for attempt in range(attempts + 1):
        try:
            return await coro_factory()
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            if attempt < attempts:
                delay = backoff_seconds * (2 ** attempt)
                logger.warning(
                    "%s: transient error (%s) — retry %d/%d in %.1fs",
                    label, type(exc).__name__, attempt + 1, attempts, delay,
                )
                await asyncio.sleep(delay)
    return None


async def fetch_json(
    label: str,
    bad_status_label: str,
    coro_factory: Callable[[], Awaitable[httpx.Response]],
    attempts: int,
    backoff_seconds: float,
    logger: logging.Logger,
) -> dict | None:
    """Call `coro_factory` with retry; return parsed JSON or None.

    On non-2xx, logs a warning that includes `response.text` (the body) so both
    GET and POST emit consistent diagnostics.
    """
    response = await retry_request(label, coro_factory, attempts, backoff_seconds, logger)
    if response is None:
        return None
    if response.is_success:
        return response.json()
    logger.warning(
        "%s returned status %s: %s",
        bad_status_label,
        response.status_code,
        response.text,
    )
    return None
