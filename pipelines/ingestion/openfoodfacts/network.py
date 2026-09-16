import threading
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx


class FetchError(Exception):
    """Safe error code; never includes raw URLs, headers, or response contents."""


class RateLimiter:
    def __init__(self, requests_per_second: float):
        self.interval = 1 / requests_per_second
        self.lock = threading.Lock()
        self.next_request = 0.0

    def wait(self) -> None:
        with self.lock:
            delay = max(0, self.next_request - time.monotonic())
            time.sleep(delay)
            self.next_request = time.monotonic() + self.interval


def retry_delay(value: str | None, attempt: int) -> float:
    if value:
        try:
            return max(0, float(value))
        except ValueError:
            try:
                return max(0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                pass
    return min(2**attempt, 30)


def fetch_bytes(
    client: httpx.Client,
    url: str,
    *,
    limit: int,
    retries: int,
    limiter: RateLimiter,
    headers: dict | None = None,
    allowed_url=None,
) -> tuple[bytes, httpx.Headers, str, int]:
    for attempt in range(retries + 1):
        limiter.wait()
        delay = 0.0
        try:
            endpoint = url
            for _ in range(4):
                if allowed_url and not allowed_url(endpoint):
                    raise FetchError("unsafe_redirect")
                with client.stream("GET", endpoint, headers=headers, follow_redirects=False) as res:
                    if res.is_redirect:
                        endpoint = str(res.url.join(res.headers.get("location", "")))
                        continue
                    if res.status_code in {429, 500, 502, 503, 504}:
                        delay = retry_delay(res.headers.get("retry-after"), attempt)
                        raise FetchError(f"http_{res.status_code}")
                    if res.status_code not in {200, 206}:
                        raise FetchError(f"http_{res.status_code}")
                    data = bytearray()
                    for chunk in res.iter_bytes():
                        if len(data) + len(chunk) > limit:
                            raise FetchError("response_too_large")
                        data.extend(chunk)
                    return bytes(data), res.headers, endpoint, res.status_code
            raise FetchError("redirect_limit")
        except httpx.TransportError:
            reason = "network_error"
            delay = retry_delay(None, attempt)
        except FetchError as error:
            reason = str(error)
            if reason not in {"http_429", "http_500", "http_502", "http_503", "http_504"}:
                raise
        if attempt == retries:
            raise FetchError(reason)
        # Never retry earlier than Retry-After. Long server cooldowns defer to a later run.
        if delay > 120:
            raise FetchError("retry_after_deferred")
        time.sleep(delay)
    raise FetchError("retry_exhausted")
