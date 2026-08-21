"""
Tax API implementation.
Based on PHP library's Api\\Tax class.
"""

from typing import Any

from ._http import AsyncHTTPClient


class TaxAPI:
    """
    Tax API for tax information and history.

    Provides async methods for:
    - Getting current tax information
    - Getting tax history by OKTMO
    - Getting payment records

    Maps to PHP Api\\Tax functionality.
    """

    def __init__(self, http_client: AsyncHTTPClient):
        self.http = http_client

    async def get(self) -> dict[str, Any]:
        """
        Get current tax information.

        Returns:
            Dictionary with current tax data

        Raises:
            DomainException: For API errors
        """
        response = await self.http.get("/taxes")
        return response.json()  # type: ignore[no-any-return]

    async def history(self, oktmo: str | None = None) -> dict[str, Any]:
        """
        Get tax history.

        Args:
            oktmo: Optional OKTMO code for filtering

        Returns:
            Dictionary with tax history records

        Raises:
            DomainException: For API errors
        """
        request_data = {"oktmo": oktmo}
        response = await self.http.post("/taxes/history", json_data=request_data)
        return response.json()  # type: ignore[no-any-return]

    async def payments(
        self, oktmo: str | None = None, only_paid: bool = False
    ) -> dict[str, Any]:
        """
        Get tax payment records.

        Args:
            oktmo: Optional OKTMO code for filtering
            only_paid: If True, return only paid records

        Returns:
            Dictionary with payment records

        Raises:
            DomainException: For API errors
        """
        request_data = {
            "oktmo": oktmo,
            "onlyPaid": only_paid,
        }
        response = await self.http.post("/taxes/payments", json_data=request_data)
        return response.json()  # type: ignore[no-any-return]
