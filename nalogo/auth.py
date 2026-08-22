"""
Authentication provider implementation.
Based on PHP library's Authenticator class.
"""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import Any

import httpx

from ._http import AuthProvider
from .dto.device import DeviceInfo
from .exceptions import raise_for_status, wrap_transport_error

logger = logging.getLogger(__name__)

#: Refresh this long before the token actually expires, so a request never
#: races the expiry and burns a guaranteed 401 round-trip.
EXPIRY_MARGIN = timedelta(minutes=1)


def generate_device_id() -> str:
    """Generate device ID similar to PHP's DeviceIdGenerator."""
    return str(uuid.uuid4()).replace("-", "")[:21].lower()


# DeviceInfo is now imported from dto.device


class AuthProviderImpl(AuthProvider):
    """
    Authentication provider implementation.

    Provides methods for:
    - Username/password authentication (INN + password)
    - Phone-based authentication (2-step: challenge + verify)
    - Token refresh
    - Token storage (in-memory or file-based)
    """

    def __init__(
        self,
        base_url: str = "https://lknpd.nalog.ru/api",
        storage_path: str | None = None,
        device_id: str | None = None,
        timeout: float = 10.0,
    ):
        self.base_url_v1 = f"{base_url}/v1"
        self.base_url_v2 = f"{base_url}/v2"
        self.storage_path = storage_path
        self.timeout = timeout
        self.device_id = device_id or generate_device_id()
        self.device_info = DeviceInfo(sourceDeviceId=self.device_id)
        self._token_data: dict[str, Any] | None = None
        self._client: httpx.AsyncClient | None = None

        # Default headers similar to PHP Authenticator
        self.default_headers = {
            "Referrer": "https://lknpd.nalog.ru/auth/login",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        if self.storage_path:
            self._load_token_from_storage()

    async def _get_client(self) -> httpx.AsyncClient:
        """
        Lazily create the shared HTTP client.

        One client for the provider's lifetime instead of one per call: a new
        client means a new connection pool and a fresh TLS handshake on every
        authentication round-trip.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        """Close the shared HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _post(self, url: str, payload: dict[str, Any]) -> httpx.Response:
        """POST to an auth endpoint, turning transport failures into ours."""
        client = await self._get_client()
        try:
            return await client.post(
                url,
                json=payload,
                headers=self.default_headers,
                timeout=self.timeout,
            )
        except httpx.RequestError as exc:
            wrap_transport_error(exc, exc.request)

    def _load_token_from_storage(self) -> None:
        """Load token from file storage."""
        if not self.storage_path:
            return
        storage_path = Path(self.storage_path)
        if not storage_path.exists():
            return

        try:
            with storage_path.open(encoding="utf-8") as f:
                self._token_data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Could not read the stored access token from %s: %s. "
                "Authentication will be required.",
                storage_path,
                exc,
            )

    def _save_token_to_storage(self) -> None:
        """Save token to file storage."""
        if not self.storage_path or not self._token_data:
            return

        storage_path = Path(self.storage_path)
        try:
            storage_path.parent.mkdir(parents=True, exist_ok=True)

            with storage_path.open("w", encoding="utf-8") as f:
                json.dump(self._token_data, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            # Not raised on purpose: authentication itself succeeded and the
            # token is live in memory, so failing the call would be worse than
            # losing persistence. But it must not pass unnoticed either - the
            # process would silently come back with a stale session after a
            # restart. Path only, never the token itself.
            logger.warning(
                "Could not persist the access token to %s: %s. "
                "The token is valid for this process but will be lost on restart.",
                storage_path,
                exc,
            )

    async def get_token(self) -> dict[str, Any] | None:
        """Get current access token data."""
        return self._token_data

    async def set_token(self, token_json: str) -> None:
        """
        Set access token from JSON string.

        Args:
            token_json: JSON string containing token data
        """
        try:
            self._token_data = json.loads(token_json)
            self._save_token_to_storage()
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid token JSON: {e}") from e

    async def create_new_access_token(self, username: str, password: str) -> str:
        """
        Create new access token using INN and password.

        Mirrors PHP Authenticator::createAccessToken().

        Args:
            username: INN (tax identification number)
            password: Password

        Returns:
            JSON string with token data

        Raises:
            Domain exceptions for authentication errors
        """
        request_data = {
            "username": username,
            "password": password,
            "deviceInfo": self.device_info.model_dump(),
        }

        response = await self._post(f"{self.base_url_v1}/auth/lkfl", request_data)
        raise_for_status(response)

        token_json = response.text
        await self.set_token(token_json)
        return token_json

    async def create_phone_challenge(self, phone: str) -> dict[str, Any]:
        """
        Start phone-based authentication challenge.

        Mirrors PHP ApiClient::createPhoneChallenge() - uses v2 API.

        Args:
            phone: Phone number (e.g., "79000000000")

        Returns:
            Dictionary with challengeToken, expireDate, expireIn

        Raises:
            Domain exceptions for API errors
        """
        request_data = {
            "phone": phone,
            "requireTpToBeActive": True,
        }

        response = await self._post(
            f"{self.base_url_v2}/auth/challenge/sms/start", request_data
        )
        raise_for_status(response)
        return response.json()  # type: ignore[no-any-return]

    async def create_new_access_token_by_phone(
        self, phone: str, challenge_token: str, verification_code: str
    ) -> str:
        """
        Complete phone-based authentication with SMS code.

        Mirrors PHP Authenticator::createAccessTokenByPhone().

        Args:
            phone: Phone number
            challenge_token: Token from create_phone_challenge()
            verification_code: SMS verification code

        Returns:
            JSON string with token data

        Raises:
            Domain exceptions for authentication errors
        """
        request_data = {
            "phone": phone,
            "code": verification_code,
            "challengeToken": challenge_token,
            "deviceInfo": self.device_info.model_dump(),
        }

        response = await self._post(
            f"{self.base_url_v1}/auth/challenge/sms/verify", request_data
        )
        raise_for_status(response)

        token_json = response.text
        await self.set_token(token_json)
        return token_json

    async def refresh(self, refresh_token: str) -> dict[str, Any] | None:
        """
        Refresh access token using refresh token.

        Returns the new token data, or None when the tax service *rejected*
        the refresh token. Transport failures raise NetworkException instead.

        Deliberately diverges from the PHP-derived original, which caught
        every exception and returned None. That made a blinked connection
        indistinguishable from a revoked token: the 401 travelled on to the
        caller, who then told a perfectly valid user to re-link their account.
        The PHP original does not do this either — there
        Authenticator::refreshAccessToken lets transport errors surface as
        ClientExceptionInterface rather than turning them into null.

        A failed refresh never touches the stored token: whatever was saved
        before stays valid for the next attempt.
        """
        request_data = {
            "deviceInfo": self.device_info.model_dump(),
            "refreshToken": refresh_token,
        }

        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.base_url_v1}/auth/token",
                json=request_data,
                headers=self.default_headers,
                timeout=self.timeout,
            )
        except httpx.RequestError as exc:
            logger.warning(
                "Token refresh could not reach the API: %s", type(exc).__name__
            )
            wrap_transport_error(exc, exc.request)

        if response.status_code != HTTPStatus.OK:
            # A real answer, and the answer is no.
            logger.warning(
                "Token refresh rejected with status %d", response.status_code
            )
            return None

        await self.set_token(response.text)
        return self._token_data

    # ------------------------------------------------------------------
    # Token lifetime
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_expiry(token_data: dict[str, Any] | None) -> datetime | None:
        """Read tokenExpireIn from a token payload, if it is usable."""
        if not token_data:
            return None
        raw = token_data.get("tokenExpireIn")
        if not isinstance(raw, str) or not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    def is_token_expiring(self, margin: timedelta = EXPIRY_MARGIN) -> bool:
        """
        Whether the current token is expired or about to expire.

        An unknown or unparseable expiry answers False, i.e. no proactive
        refresh. Some references treat unknown as expired; here that would be
        actively harmful. The tax service rotates the refresh token on every
        successful refresh, so a token payload without tokenExpireIn would
        trigger a refresh before *every* request and spin the rotation
        endlessly. The reactive 401 path already covers that case correctly,
        at the cost of one round-trip.
        """
        if not self._token_data:
            return False
        expiry = self._parse_expiry(self._token_data)
        if expiry is None:
            return False
        return datetime.now(UTC) + margin >= expiry
