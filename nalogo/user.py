"""
User API implementation.
Based on PHP library's Api\\User class.
"""

from typing import Any

from ._http import AsyncHTTPClient


class UserAPI:
    """
    User API for user information.

    Provides async methods for:
    - Getting current user information

    Maps to PHP Api\\User functionality.
    """

    def __init__(self, http_client: AsyncHTTPClient):
        self.http = http_client

    async def get(self) -> dict[str, Any]:
        """
        Get current user information.

        Returns:
            Dictionary with user profile data including:
            - id, inn, displayName, email, phone
            - registration dates, status, restrictions
            - avatar, receipt settings, etc.

        Raises:
            DomainException: For API errors
        """
        response = await self.http.get("/user")
        return response.json()  # type: ignore[no-any-return]
