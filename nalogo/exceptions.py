"""
Domain exceptions for Moy Nalog API.
Mirrors PHP library's exception hierarchy and error handling.
"""

import logging
import re
from http import HTTPStatus
from typing import Never

import httpx

logger = logging.getLogger(__name__)

_URL_SECRET_PATTERNS = [
    (r"(token=)[^&]*", r"\1***"),
    (r"(key=)[^&]*", r"\1***"),
    (r"(secret=)[^&]*", r"\1***"),
]


def mask_url(url: str) -> str:
    """
    Mask secrets that may appear in a URL query string.

    Module-level so that every logging path can reuse it, including the
    transport-error path that has no response object to work from.
    """
    for pattern, replacement in _URL_SECRET_PATTERNS:
        url = re.sub(pattern, replacement, url)
    return url


class DomainException(Exception):  # noqa: N818 для совместимости публичного API
    """Base domain exception for all Moy Nalog API errors."""

    def __init__(self, message: str, response: httpx.Response | None = None):
        super().__init__(message)
        self.response = response

        if response:
            self._log_error_details(message, response)

    def _log_error_details(self, message: str, response: httpx.Response) -> None:
        """Log error details while avoiding sensitive information."""
        safe_url = self._mask_sensitive_url(str(response.url))
        safe_headers = self._mask_sensitive_headers(dict(response.headers))

        logger.error(
            "API Error: %s | Status: %d | URL: %s | Headers: %s | Body: %s",
            message,
            response.status_code,
            safe_url,
            safe_headers,
            self._get_safe_response_body(response),
        )

    def _mask_sensitive_url(self, url: str) -> str:
        """Mask potential sensitive data in URL."""
        return mask_url(url)

    def _mask_sensitive_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Mask sensitive headers."""
        safe_headers = headers.copy()
        sensitive_keys = ["authorization", "x-api-key", "cookie", "set-cookie"]

        for key in sensitive_keys:
            if key.lower() in [h.lower() for h in safe_headers]:
                # Find the actual key (case-insensitive)
                actual_key = next(k for k in safe_headers if k.lower() == key.lower())
                safe_headers[actual_key] = "***"

        return safe_headers

    def _get_safe_response_body(self, response: httpx.Response) -> str:
        """Get response body with potential sensitive data masked."""
        try:
            body = response.text[:1000]  # Limit body size for logging
            # Mask potential tokens in JSON responses
            patterns = [
                (r'("token":\s*")[^"]*(")', r"\1***\2"),
                (r'("refreshToken":\s*")[^"]*(")', r"\1***\2"),
                (r'("password":\s*")[^"]*(")', r"\1***\2"),
                (r'("secret":\s*")[^"]*(")', r"\1***\2"),
            ]

            for pattern, replacement in patterns:
                body = re.sub(pattern, replacement, body)

            return body
        except Exception:
            return "[Failed to read response body]"


class ValidationException(DomainException):
    """HTTP 400 - Validation error."""


class UnauthorizedException(DomainException):
    """HTTP 401 - Authentication required or invalid credentials."""


class ForbiddenException(DomainException):
    """HTTP 403 - Access forbidden."""


class NotFoundException(DomainException):
    """HTTP 404 - Resource not found."""


class ClientException(DomainException):
    """HTTP 406 - Client error (e.g., wrong Accept headers)."""


class PhoneException(DomainException):
    """HTTP 422 - Phone-related error (SMS, verification, etc.)."""


class ServerException(DomainException):
    """HTTP 500 - Internal server error."""


class RateLimitException(DomainException):
    """
    HTTP 429 - too many requests.

    Distinct from UnknownErrorException on purpose: the caller must be able to
    tell "slow down and come back" from "something unrecognised broke".
    ``retry_after`` carries the Retry-After header in seconds when the API
    sends one.
    """

    def __init__(
        self,
        message: str,
        response: httpx.Response | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message, response)
        self.retry_after = retry_after


class ServiceUnavailableException(ServerException):
    """
    HTTP 502, 503, 504 - the service is temporarily unreachable.

    Subclasses ServerException because these are server-side failures: code
    that already handles ServerException keeps working. Split out because a
    gateway error or scheduled maintenance at the tax service is worth
    retrying, unlike a genuine 500.
    """


class UnknownErrorException(DomainException):
    """Unknown HTTP error code."""


class NetworkException(DomainException):
    """
    No response was received at all.

    The decisive distinction in this hierarchy: every exception above means
    the tax service answered and refused, this one means it never answered.
    The first is fixed by a human, the second by trying again. Conflating them
    makes callers revoke access or demand re-linking of an account that is
    perfectly fine.

    ``response`` is always None. ``request_may_have_been_sent`` says whether
    the request could already have reached the server — decisive for
    non-idempotent calls such as issuing a receipt.
    """

    #: Conservative default: assume the server may have seen the request.
    request_may_have_been_sent = True

    def __init__(self, message: str, request: httpx.Request | None = None):
        super().__init__(message, None)
        self.request = request


class ConnectionException(NetworkException):
    """
    The connection was never established, so the request never left.

    Safe to retry even for non-idempotent calls: the server cannot have
    created anything from a request it never received.
    """

    request_may_have_been_sent = False


class TimeoutException(NetworkException):
    """
    The request was sent but no reply arrived in time.

    NOT safe to blind-retry a receipt: the tax service may have processed it
    and only the answer was lost.
    """


def wrap_transport_error(exc: Exception, request: httpx.Request | None = None) -> Never:
    """
    Re-raise an httpx transport failure as the library's NetworkException.

    Deliberately diverges from the PHP original, where transport errors escape
    as the HTTP client's own type: callers of this library catch
    DomainException, and a raw httpx error would slip past every handler they
    wrote.
    """
    url = mask_url(str(request.url)) if request is not None else "the API"
    detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__

    if isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout | httpx.PoolTimeout):
        # Handshake never completed, or no connection was free: nothing was
        # transmitted, so a retry cannot duplicate anything.
        raise ConnectionException(
            f"Could not connect to {url} ({detail})", request
        ) from exc
    if isinstance(exc, httpx.TimeoutException):
        raise TimeoutException(
            f"No response from {url} in time ({detail})", request
        ) from exc
    raise NetworkException(f"Request to {url} failed ({detail})", request) from exc


class InputException(DomainException, ValueError):  # noqa: N818
    """
    Invalid value passed to the library.

    Unlike the exceptions above, this family is raised locally before any
    request is made, so ``response`` is always None. Also inherits ValueError,
    so generic ``except ValueError`` handlers keep working.
    """


class TimezoneException(InputException):
    """Unusable timezone: unknown IANA name or unsupported type."""


class DateTimeFormatException(InputException):
    """Datetime string that cannot be parsed as ISO 8601."""


_UNAVAILABLE_STATUSES = frozenset(
    {
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
    }
)


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Read Retry-After as seconds. Only the delta-seconds form is handled."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw.strip())
    except ValueError:
        # HTTP-date form; callers get None and fall back to their own backoff
        return None


def raise_for_status(response: httpx.Response) -> None:
    """
    Raise appropriate domain exception based on HTTP status code.

    Maps status codes to exceptions. 400, 401, 403, 404, 406, 422 and 500
    follow PHP ErrorHandler exactly. 429 and 502/503/504 are ours: the PHP
    original lumps them into the catch-all, which leaves the caller unable to
    tell "wait and retry" from "something unrecognised broke".

    - 400: ValidationException
    - 401: UnauthorizedException
    - 403: ForbiddenException
    - 404: NotFoundException
    - 406: ClientException
    - 422: PhoneException
    - 429: RateLimitException (carries retry_after)
    - 500: ServerException
    - 502, 503, 504: ServiceUnavailableException
    - default: UnknownErrorException

    Args:
        response: httpx.Response object

    Raises:
        DomainException: Appropriate exception for status code
    """
    if response.status_code < HTTPStatus.BAD_REQUEST:
        return

    body = response.text

    if response.status_code == HTTPStatus.BAD_REQUEST:
        raise ValidationException(body, response)
    if response.status_code == HTTPStatus.UNAUTHORIZED:
        raise UnauthorizedException(body, response)
    if response.status_code == HTTPStatus.FORBIDDEN:
        raise ForbiddenException(body, response)
    if response.status_code == HTTPStatus.NOT_FOUND:
        raise NotFoundException(body, response)
    if response.status_code == HTTPStatus.NOT_ACCEPTABLE:
        raise ClientException("Wrong Accept headers", response)
    if response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY:
        raise PhoneException(body, response)
    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        raise RateLimitException(body, response, _parse_retry_after(response))
    if response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR:
        raise ServerException(body, response)
    if response.status_code in _UNAVAILABLE_STATUSES:
        raise ServiceUnavailableException(body, response)
    raise UnknownErrorException(body, response)
