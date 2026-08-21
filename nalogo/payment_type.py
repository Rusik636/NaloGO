"""
PaymentType API implementation.
Based on PHP library's Api\\PaymentType class.
"""

from typing import Any

from ._http import AsyncHTTPClient


class PaymentTypeAPI:
    """
    PaymentType API for managing payment methods.

    Provides async methods for:
    - Getting payment types table
    - Finding favorite payment type

    Maps to PHP Api\\PaymentType functionality.
    """

    def __init__(self, http_client: AsyncHTTPClient):
        self.http = http_client

    async def table(self) -> list[dict[str, Any]]:
        """
        Get all available payment types.

        Returns:
            List of payment type dictionaries with bank information

        Raises:
            DomainException: For API errors
        """
        response = await self.http.get("/payment-type/table")
        return response.json()  # type: ignore[no-any-return]

    async def favorite(self) -> dict[str, Any] | None:
        """
        Get favorite payment type.

        Maps to PHP PaymentType::favorite().
        Finds the first payment type marked as favorite from the table.

        Returns:
            Payment type dictionary if favorite found, None otherwise

        Raises:
            DomainException: For API errors
        """
        payment_types = await self.table()

        # Find first payment type with favorite=True
        for payment_type in payment_types:
            if payment_type.get("favorite", False):
                return payment_type

        return None
