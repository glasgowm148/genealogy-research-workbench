"""Explicit, injectable HTTP boundary for the WikiTree API."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol


DEFAULT_API_URL = "https://api.wikitree.com/api.php"


class HttpResponse(Protocol):
    """The small response surface required by :class:`WikiTreeHttpClient`."""

    status_code: int
    headers: Mapping[str, Any]
    text: str

    def json(self) -> Any: ...

    def raise_for_status(self) -> None: ...


HttpTransport = Callable[..., HttpResponse]
Backoff = float | Callable[[int], float]


class WikiTreeClientError(RuntimeError):
    """Base class for WikiTree request and response failures."""


class WikiTreeRequestError(WikiTreeClientError):
    """The HTTP request failed or returned an error status."""


class WikiTreeWafChallengeError(WikiTreeClientError):
    """WikiTree's upstream WAF challenged the API request."""


class WikiTreeResponseError(WikiTreeClientError):
    """WikiTree returned content outside the documented API envelope."""


class WikiTreeApiError(WikiTreeClientError):
    """WikiTree returned an API-level error status in a valid envelope."""


class WikiTreeHttpClient:
    """POST WikiTree API actions only when :meth:`post` is explicitly called.

    The caller supplies the transport and application ID. This keeps the
    reusable adapter independent of a particular HTTP library or research
    project, while still centralising retries and response validation.
    """

    def __init__(
        self,
        *,
        app_id: str,
        transport: HttpTransport,
        base_url: str = DEFAULT_API_URL,
        timeout: float = 45,
        max_attempts: int = 5,
        backoff: Backoff = 2.0,
        max_backoff: float = 60.0,
        headers: Mapping[str, str] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        if not app_id.strip():
            raise ValueError("WikiTree app_id cannot be empty")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if timeout <= 0:
            raise ValueError("timeout must be greater than 0")
        if max_backoff < 0:
            raise ValueError("max_backoff cannot be negative")
        self.app_id = app_id
        self.transport = transport
        self.base_url = base_url
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff = backoff
        self.max_backoff = max_backoff
        self.headers = dict(headers or {})
        self.sleeper = sleeper or time.sleep

    def post(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Submit one API action and return its validated response envelope."""
        request_payload = dict(payload)
        request_payload.setdefault("appId", self.app_id)
        response: HttpResponse | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.transport(
                    self.base_url,
                    data=request_payload,
                    timeout=self.timeout,
                    headers=self.headers,
                )
            except Exception as error:
                if attempt == self.max_attempts:
                    raise WikiTreeRequestError(
                        f"WikiTree API request failed after {self._attempt_label()}: {error}"
                    ) from error
                self.sleeper(self._delay(attempt))
                continue

            if self._header(response, "x-amzn-waf-action").casefold() == "challenge":
                raise WikiTreeWafChallengeError(
                    "WikiTree's AWS WAF challenged the API request before it "
                    "reached api.php (HTTP 202). Retry later or use the public "
                    "profile-page capture fallback."
                )

            status_code = int(response.status_code)
            retryable = status_code == 429 or status_code >= 500
            if retryable and attempt < self.max_attempts:
                self.sleeper(self._retry_delay(response, attempt))
                continue

            self._check_http_status(response, retryable)
            break

        if response is None:
            raise WikiTreeRequestError("WikiTree API request produced no response.")
        return self._parse_envelope(response)

    def _check_http_status(self, response: HttpResponse, retryable: bool) -> None:
        try:
            response.raise_for_status()
        except Exception as error:
            qualifier = f" after {self._attempt_label()}" if retryable else ""
            raise WikiTreeRequestError(
                f"WikiTree API request failed{qualifier}: {error}"
            ) from error

    def _parse_envelope(self, response: HttpResponse) -> dict[str, Any]:
        content_type = self._header(response, "content-type")
        if content_type and "json" not in content_type.casefold():
            raise WikiTreeResponseError(
                f"WikiTree returned non-JSON content: {self._preview(response)}"
            )
        try:
            data = response.json()
        except ValueError as error:
            raise WikiTreeResponseError(
                f"WikiTree returned non-JSON content: {self._preview(response)}"
            ) from error
        if not isinstance(data, list) or not data:
            raise WikiTreeResponseError("Unexpected empty response from WikiTree.")
        envelope = data[0]
        if not isinstance(envelope, dict):
            raise WikiTreeResponseError("Unexpected WikiTree response structure.")
        status = envelope.get("status")
        if status not in (0, "0", "", None):
            raise WikiTreeApiError(f"WikiTree API returned status: {status!r}")
        return envelope

    def _retry_delay(self, response: HttpResponse, attempt: int) -> float:
        retry_after = self._header(response, "retry-after")
        try:
            delay = max(0.0, float(retry_after)) if retry_after else self._delay(attempt)
        except (TypeError, ValueError):
            delay = self._delay(attempt)
        return min(delay, self.max_backoff)

    def _delay(self, attempt: int) -> float:
        delay = self.backoff(attempt) if callable(self.backoff) else self.backoff * (2 ** (attempt - 1))
        return min(max(0.0, float(delay)), self.max_backoff)

    def _attempt_label(self) -> str:
        if self.max_attempts == 5:
            return "five attempts"
        noun = "attempt" if self.max_attempts == 1 else "attempts"
        return f"{self.max_attempts} {noun}"

    @staticmethod
    def _header(response: HttpResponse, name: str) -> str:
        for key, value in response.headers.items():
            if str(key).casefold() == name.casefold():
                return str(value)
        return ""

    @staticmethod
    def _preview(response: HttpResponse) -> str:
        return str(response.text)[:500].replace("\n", " ")
