"""
Internal HTTP client and authentication middleware.
Based on PHP library's AuthenticationPlugin and HTTP architecture.
"""

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from http import HTTPStatus
from typing import Any

import httpx

from .exceptions import (
    NetworkException,
    ServiceUnavailableException,
    raise_for_status,
    wrap_transport_error,
)

logger = logging.getLogger(__name__)

#: Methods that may be repeated without creating a second document.
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE = 0.5
DEFAULT_BACKOFF_CAP = 8.0


class AuthProvider(ABC):
    """Abstract interface for authentication provider."""

    @abstractmethod
    async def get_token(self) -> dict[str, Any] | None:
        """Get current access token data."""

    @abstractmethod
    async def refresh(self, refresh_token: str) -> dict[str, Any] | None:
        """Refresh access token using refresh token."""


class AsyncHTTPClient:
    """
    Async HTTP client with automatic token refresh on 401 responses.

    Based on PHP's AuthenticationPlugin behavior:
    - Adds Bearer authorization header
    - On 401 response, attempts token refresh once
    - Retries request with new token

    Retry policy is deliberately narrow. Issuing a receipt is not idempotent
    at the tax service: a blind repeat can produce a second document, which is
    worse than a failed call. So a request is repeated only when it provably
    never reached the server, or when the method is safe to repeat.
    """

    def __init__(
        self,
        base_url: str,
        auth_provider: AuthProvider,
        default_headers: dict[str, str] | None = None,
        timeout: float = 10.0,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ):
        self.base_url = base_url
        self.auth_provider = auth_provider
        self.default_headers = default_headers or {}
        self.timeout = timeout
        self._refresh_lock = asyncio.Lock()
        self.max_attempts = max(1, max_attempts)
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Connection reuse
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """
        Lazily create the shared HTTP client.

        Previously every request opened its own AsyncClient, which meant a new
        connection pool and a fresh TLS handshake per receipt.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        """Close the shared HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def _get_auth_headers(self) -> dict[str, str]:
        """Get authorization headers from current token."""
        token_data = await self.auth_provider.get_token()
        if not token_data or "token" not in token_data:
            return {}

        return {"Authorization": f"Bearer {token_data['token']}"}

    async def _refresh_if_needed(self) -> None:
        """
        Refresh proactively when the token is about to expire.

        Without this every expiry costs a guaranteed 401 round-trip before the
        reactive refresh path kicks in. Silent no-op for providers that do not
        expose an expiry (the abstract AuthProvider does not require it).
        """
        is_expiring = getattr(self.auth_provider, "is_token_expiring", None)
        if is_expiring is None or not is_expiring():
            return

        async with self._refresh_lock:
            if not is_expiring():
                # Another coroutine refreshed while we waited for the lock.
                return
            token_data = await self.auth_provider.get_token()
            if not token_data or "refreshToken" not in token_data:
                return
            await self.auth_provider.refresh(token_data["refreshToken"])

    async def _handle_401_response(
        self, client: httpx.AsyncClient, request: httpx.Request
    ) -> httpx.Response | None:
        """
        Handle 401 response by refreshing token and retrying request.

        The token in use is captured before the lock and compared after it.
        Without that comparison two concurrent 401s produce two refreshes in a
        row, and since the tax service rotates the refresh token on every
        successful call, the second one travels with an already-spent token
        and can cost the whole session.

        Returns None when the refresh was genuinely rejected, so the caller
        surfaces the original 401. A refresh that failed on the network raises
        NetworkException instead of returning None - a blinked connection must
        never be reported as "your access is invalid".
        """
        stale_token = (await self.auth_provider.get_token() or {}).get("token")

        async with self._refresh_lock:
            token_data = await self.auth_provider.get_token()
            if not token_data or "refreshToken" not in token_data:
                return None

            if token_data.get("token") and token_data["token"] != stale_token:
                # Someone else refreshed while we queued; reuse their result.
                new_token_data: dict[str, Any] | None = token_data
            else:
                new_token_data = await self.auth_provider.refresh(
                    token_data["refreshToken"]
                )

            if not new_token_data or "token" not in new_token_data:
                return None

            request.headers["Authorization"] = f"Bearer {new_token_data['token']}"

            try:
                return await client.send(request)
            except httpx.RequestError as exc:
                # Without this the retry's transport failure escaped as a raw
                # httpx error, past every `except DomainException` handler.
                wrap_transport_error(exc, request)

    # ------------------------------------------------------------------
    # Requests
    # ------------------------------------------------------------------

    def _backoff(self, attempt: int) -> float:
        """Exponential backoff with full jitter, capped."""
        window = min(DEFAULT_BACKOFF_BASE * (2**attempt), DEFAULT_BACKOFF_CAP)
        # Не криптография: разброс нужен, чтобы клиенты не били залпом.
        return random.uniform(0, window)

    def _may_retry(self, method: str, error: Exception) -> bool:
        """
        Whether repeating this request is safe.

        Idempotent methods may always be repeated. Everything else - and that
        includes POST /income, which issues a receipt - only when the request
        provably never left, so the server cannot have acted on it.
        """
        if method.upper() in IDEMPOTENT_METHODS:
            return True
        return (
            isinstance(error, NetworkException) and not error.request_may_have_been_sent
        )

    async def request(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Make HTTP request with automatic auth, retry and 401 refresh logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (e.g., "/income")
            headers: Additional headers
            json_data: JSON request body
            **kwargs: Additional httpx.AsyncClient.request arguments

        Returns:
            httpx.Response object

        Raises:
            NetworkException: The API never answered
            DomainException: The API answered and refused
        """
        await self._refresh_if_needed()

        for attempt in range(self.max_attempts):
            try:
                return await self._attempt(method, path, headers, json_data, **kwargs)
            except (NetworkException, ServiceUnavailableException) as exc:
                if attempt + 1 >= self.max_attempts or not self._may_retry(method, exc):
                    raise
                delay = self._backoff(attempt)
                logger.warning(
                    "%s %s failed (%s), retrying in %.2fs (attempt %d/%d)",
                    method,
                    path,
                    type(exc).__name__,
                    delay,
                    attempt + 2,
                    self.max_attempts,
                )
                await asyncio.sleep(delay)

        # Недостижимо: последняя итерация всегда возвращает результат или
        # пробрасывает исключение, но mypy этого не выводит.
        raise AssertionError("retry loop exited without a result")

    async def _attempt(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """One send, including the 401 refresh dance. No retries here."""
        request_headers = self.default_headers.copy()
        auth_headers = await self._get_auth_headers()
        request_headers.update(auth_headers)
        if headers:
            request_headers.update(headers)

        request_kwargs = {
            "method": method,
            "url": self.base_url + path,
            "headers": request_headers,
            "timeout": self.timeout,
            **kwargs,
        }

        if json_data is not None:
            request_kwargs["json"] = json_data

        client = await self._get_client()

        try:
            response = await client.request(**request_kwargs)
        except httpx.RequestError as exc:
            # The whole point of the NetworkException family: callers catching
            # DomainException would otherwise miss a dropped connection.
            wrap_transport_error(exc, exc.request)

        if response.status_code == HTTPStatus.UNAUTHORIZED:
            retry_request = client.build_request(**request_kwargs)
            retry_response = await self._handle_401_response(client, retry_request)
            if retry_response is not None:
                response = retry_response

        raise_for_status(response)

        return response

    async def get(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """GET request."""
        return await self.request("GET", path, headers=headers, **kwargs)

    async def post(
        self,
        path: str,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """POST request with JSON data."""
        return await self.request(
            "POST", path, headers=headers, json_data=json_data, **kwargs
        )

    async def put(
        self,
        path: str,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """PUT request with JSON data."""
        return await self.request(
            "PUT", path, headers=headers, json_data=json_data, **kwargs
        )

    async def delete(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """DELETE request."""
        return await self.request("DELETE", path, headers=headers, **kwargs)
