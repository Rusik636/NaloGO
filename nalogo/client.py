"""
Main client facade for Moy Nalog API.
Based on PHP library's ApiClient class.
"""

import json
from datetime import tzinfo
from typing import Any

from ._http import AsyncHTTPClient
from .auth import AuthProviderImpl
from .income import IncomeAPI
from .payment_type import PaymentTypeAPI
from .receipt import ReceiptAPI
from .tax import TaxAPI
from .timezone import resolve_timezone
from .user import UserAPI


class Client:
    """
    Main async client for Moy Nalog API.

    Provides factory methods for API modules and authentication methods.
    Maps to PHP ApiClient functionality with async support.

    Example:
        >>> client = Client()
        >>> token = await client.create_new_access_token("inn", "password")
        >>> await client.authenticate(token)
        >>> income_api = client.income()
        >>> result = await income_api.create("Service", 100, 1)
    """

    def __init__(
        self,
        base_url: str = "https://lknpd.nalog.ru/api",
        storage_path: str | None = None,
        device_id: str | None = None,
        timeout: float = 10.0,
        timezone: str | tzinfo | None = None,
    ):
        """
        Initialize Moy Nalog API client.

        Args:
            base_url: API base URL (default: https://lknpd.nalog.ru/api)
            storage_path: Optional file path for token storage
            device_id: Optional device ID (auto-generated if not provided)
            timeout: HTTP request timeout in seconds
            timezone: IANA timezone name (e.g. "Asia/Yekaterinburg") or tzinfo
                used to interpret datetimes passed to the API without an
                offset, such as operation_time. Defaults to
                "Europe/Moscow". Receipts are
                always transmitted in Moscow time regardless of this setting,
                because that is how the tax authority records them; this only
                controls what a datetime without an offset is taken to mean.
        """
        self.base_url = base_url
        self.timeout = timeout
        self.timezone = resolve_timezone(timezone)

        self.auth_provider = AuthProviderImpl(
            base_url=base_url,
            storage_path=storage_path,
            device_id=device_id,
            timeout=timeout,
        )

        self.http_client = AsyncHTTPClient(
            base_url=f"{base_url}/v1",
            auth_provider=self.auth_provider,
            default_headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referrer": "https://lknpd.nalog.ru/auth/login",
            },
            timeout=timeout,
        )

        # User profile data (for receipt operations)
        self._user_profile: dict[str, Any] | None = None

    async def aclose(self) -> None:
        """
        Close pooled HTTP connections.

        Both the API client and the auth provider keep a connection pool alive
        for reuse; this releases them. Safe to call more than once.
        """
        await self.http_client.aclose()
        await self.auth_provider.aclose()

    async def __aenter__(self) -> "Client":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def create_new_access_token(self, username: str, password: str) -> str:
        """
        Create new access token using INN and password.

        Args:
            username: INN (tax identification number)
            password: Password

        Returns:
            JSON string with access token data

        Raises:
            UnauthorizedException: For invalid credentials
            DomainException: For other API errors
        """
        return await self.auth_provider.create_new_access_token(username, password)

    async def create_phone_challenge(self, phone: str) -> dict[str, Any]:
        """
        Start phone-based authentication challenge.

        Args:
            phone: Phone number (e.g., "79000000000")

        Returns:
            Dictionary with challengeToken, expireDate, expireIn

        Raises:
            DomainException: For API errors
        """
        return await self.auth_provider.create_phone_challenge(phone)

    async def create_new_access_token_by_phone(
        self, phone: str, challenge_token: str, verification_code: str
    ) -> str:
        """
        Complete phone-based authentication with SMS code.

        Args:
            phone: Phone number
            challenge_token: Token from create_phone_challenge()
            verification_code: SMS verification code

        Returns:
            JSON string with access token data

        Raises:
            UnauthorizedException: For invalid verification
            DomainException: For other API errors
        """
        return await self.auth_provider.create_new_access_token_by_phone(
            phone, challenge_token, verification_code
        )

    async def authenticate(self, access_token: str) -> None:
        """
        Authenticate client with access token.

        Args:
            access_token: JSON string with token data

        Raises:
            ValueError: For invalid token JSON
        """
        await self.auth_provider.set_token(access_token)

        # Parse token to extract user profile (like PHP version)
        try:
            token_data = json.loads(access_token)
            if "profile" in token_data:
                self._user_profile = token_data["profile"]
        except json.JSONDecodeError:
            # If token parsing fails, profile will remain None
            pass

    async def get_access_token(self) -> str | None:
        """
        Get current access token (may be refreshed).

        Returns:
            Current access token JSON string or None
        """
        token_data = await self.auth_provider.get_token()
        if token_data:
            return json.dumps(token_data)
        return None

    def income(self) -> IncomeAPI:
        """
        Get Income API instance.

        Returns:
            IncomeAPI instance for creating/cancelling receipts
        """
        return IncomeAPI(self.http_client, timezone=self.timezone)

    def receipt(self) -> ReceiptAPI:
        """
        Get Receipt API instance.

        Returns:
            ReceiptAPI instance for accessing receipt data

        Raises:
            ValueError: If user is not authenticated (no profile data)
        """
        if not self._user_profile or "inn" not in self._user_profile:
            raise ValueError("User profile not available. Please authenticate first.")

        return ReceiptAPI(
            http_client=self.http_client,
            base_endpoint=self.base_url,
            user_inn=self._user_profile["inn"],
        )

    def payment_type(self) -> PaymentTypeAPI:
        """
        Get PaymentType API instance.

        Returns:
            PaymentTypeAPI instance for managing payment methods
        """
        return PaymentTypeAPI(self.http_client)

    def tax(self) -> TaxAPI:
        """
        Get Tax API instance.

        Returns:
            TaxAPI instance for tax information and history
        """
        return TaxAPI(self.http_client)

    def user(self) -> UserAPI:
        """
        Get User API instance.

        Returns:
            UserAPI instance for user information
        """
        return UserAPI(self.http_client)
