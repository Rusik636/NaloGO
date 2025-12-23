"""
Domain exceptions for Moy Nalog API.
Mirrors PHP library's exception hierarchy and error handling.
"""

import logging
import re
from http import HTTPStatus

import httpx

logger = logging.getLogger(__name__)


class DomainException(Exception):  # noqa: N818 для совместимости публичного API
    """Base domain exception for all Moy Nalog API errors."""

    def __init__(self, message: str, response: httpx.Response | None = None):
        super().__init__(message)
        self.response = response

        # Log the error with response details (without sensitive data)
        if response:
            self._log_error_details(message, response)

    def _log_error_details(self, message: str, response: httpx.Response) -> None:
        """Log error details while avoiding sensitive information."""
        # Mask potential sensitive data in URLs and headers
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
        # Replace tokens/keys with asterisks
        patterns = [
            (r"(token=)[^&]*", r"\1***"),
            (r"(key=)[^&]*", r"\1***"),
            (r"(secret=)[^&]*", r"\1***"),
        ]

        for pattern, replacement in patterns:
            url = re.sub(pattern, replacement, url)
        return url

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


class UnknownErrorException(DomainException):
    """Unknown HTTP error code."""


def raise_for_status(response: httpx.Response) -> None:
    """
    Raise appropriate domain exception based on HTTP status code.

    Maps status codes to exceptions exactly like PHP ErrorHandler:
    - 400: ValidationException
    - 401: UnauthorizedException
    - 403: ForbiddenException
    - 404: NotFoundException
    - 406: ClientException
    - 422: PhoneException
    - 500: ServerException
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
    if response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR:
        raise ServerException(body, response)
    raise UnknownErrorException(body, response)
