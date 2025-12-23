"""
Async tests for authentication functionality.
Tests auth flows, token refresh middleware, and error handling.
"""

import json

import httpx
import pytest
import respx

from nalogo.auth import AuthProviderImpl
from nalogo.client import Client
from nalogo.exceptions import UnauthorizedException


@pytest.fixture
def sample_token_response():
    """Sample token response matching PHP test structure."""
    return {
        "token": "sample_access_token",
        "refreshToken": "sample_refresh_token",
        "tokenExpireIn": "2024-12-31T23:59:59.999Z",
        "refreshTokenExpiresIn": None,
        "profile": {
            "id": 1000000,
            "inn": "123456789012",
            "displayName": "Test User",
            "email": "test@example.com",
            "phone": "79000000000",
        },
    }


@pytest.fixture
def challenge_response():
    """Sample phone challenge response."""
    return {
        "challengeToken": "00000000-0000-0000-0000-000000000000",
        "expireDate": "2024-01-01T12:02:00.000Z",
        "expireIn": 120,
    }


class TestAuthProviderImpl:
    """Test AuthProviderImpl functionality."""

    @pytest.mark.asyncio
    async def test_create_new_access_token_success(self, sample_token_response):
        """Test successful username/password authentication."""
        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            respx_mock.post("/auth/lkfl").mock(
                return_value=httpx.Response(200, text=json.dumps(sample_token_response))
            )

            auth_provider = AuthProviderImpl()
            token_json = await auth_provider.create_new_access_token(
                "test_inn", "test_password"
            )

            # Verify token was returned and stored
            token_data = json.loads(token_json)
            assert token_data["token"] == "sample_access_token"
            assert token_data["refreshToken"] == "sample_refresh_token"

            # Verify token is stored in provider
            stored_token = await auth_provider.get_token()
            assert stored_token == token_data

    @pytest.mark.asyncio
    async def test_create_new_access_token_unauthorized(self):
        """Test failed authentication with 401 error."""
        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            respx_mock.post("/auth/lkfl").mock(
                return_value=httpx.Response(
                    401, text=json.dumps({"message": "Invalid credentials"})
                )
            )

            auth_provider = AuthProviderImpl()

            with pytest.raises(UnauthorizedException) as exc_info:
                await auth_provider.create_new_access_token(
                    "invalid_inn_example", "invalid_password_example"
                )

            assert "Invalid credentials" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_phone_challenge_success(self, challenge_response):
        """Test successful phone challenge creation."""
        with respx.mock(base_url="https://lknpd.nalog.ru/api/v2") as respx_mock:
            respx_mock.post("/auth/challenge/sms/start").mock(
                return_value=httpx.Response(200, json=challenge_response)
            )

            auth_provider = AuthProviderImpl()
            result = await auth_provider.create_phone_challenge("79000000000")

            assert result["challengeToken"] == "00000000-0000-0000-0000-000000000000"
            assert result["expireIn"] == 120

    @pytest.mark.asyncio
    async def test_create_new_access_token_by_phone_success(
        self, sample_token_response
    ):
        """Test successful phone verification."""
        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            respx_mock.post("/auth/challenge/sms/verify").mock(
                return_value=httpx.Response(200, text=json.dumps(sample_token_response))
            )

            auth_provider = AuthProviderImpl()
            token_json = await auth_provider.create_new_access_token_by_phone(
                "79000000000", "00000000-0000-0000-0000-000000000000", "123456"
            )

            token_data = json.loads(token_json)
            assert token_data["token"] == "sample_access_token"

    @pytest.mark.asyncio
    async def test_refresh_token_success(self, sample_token_response):
        """Test successful token refresh."""
        new_token_response = sample_token_response.copy()
        new_token_response["token"] = "new_access_token"

        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            respx_mock.post("/auth/token").mock(
                return_value=httpx.Response(200, text=json.dumps(new_token_response))
            )

            auth_provider = AuthProviderImpl()
            result = await auth_provider.refresh("sample_refresh_token")

            assert result is not None
            assert result["token"] == "new_access_token"

    @pytest.mark.asyncio
    async def test_refresh_token_failure(self):
        """Test failed token refresh."""
        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            respx_mock.post("/auth/token").mock(
                return_value=httpx.Response(401, text="Unauthorized")
            )

            auth_provider = AuthProviderImpl()
            result = await auth_provider.refresh("invalid_refresh_token")

            # Should return None on refresh failure (like PHP version)
            assert result is None


class TestClient:
    """Test main Client facade."""

    @pytest.mark.asyncio
    async def test_create_new_access_token(self, sample_token_response):
        """Test client authentication via username/password."""
        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            respx_mock.post("/auth/lkfl").mock(
                return_value=httpx.Response(200, text=json.dumps(sample_token_response))
            )

            client = Client()
            token_json = await client.create_new_access_token(
                "test_inn", "test_password"
            )

            token_data = json.loads(token_json)
            assert token_data["token"] == "sample_access_token"

    @pytest.mark.asyncio
    async def test_create_phone_challenge(self, challenge_response):
        """Test client phone challenge creation."""
        with respx.mock(base_url="https://lknpd.nalog.ru/api/v2") as respx_mock:
            respx_mock.post("/auth/challenge/sms/start").mock(
                return_value=httpx.Response(200, json=challenge_response)
            )

            client = Client()
            result = await client.create_phone_challenge("79000000000")

            assert result["challengeToken"] == "00000000-0000-0000-0000-000000000000"

    @pytest.mark.asyncio
    async def test_authenticate_and_get_token(self, sample_token_response):
        """Test client authentication and token retrieval."""
        client = Client()
        token_json = json.dumps(sample_token_response)

        await client.authenticate(token_json)

        retrieved_token = await client.get_access_token()
        assert retrieved_token == token_json

    @pytest.mark.asyncio
    async def test_authenticate_extracts_profile(self, sample_token_response):
        """Test that authenticate extracts user profile for receipt operations."""
        client = Client()
        token_json = json.dumps(sample_token_response)

        await client.authenticate(token_json)

        # Should be able to create receipt API (requires profile)
        receipt_api = client.receipt()
        assert receipt_api.user_inn == "123456789012"

    @pytest.mark.asyncio
    async def test_receipt_requires_authentication(self):
        """Test that receipt API requires authentication."""
        client = Client()

        with pytest.raises(ValueError, match="User profile not available"):
            client.receipt()


class TestRefreshMiddleware:
    """Test HTTP client refresh middleware."""

    @pytest.mark.asyncio
    async def test_401_triggers_refresh_and_retry(self, sample_token_response):
        """Test that 401 response triggers token refresh and retries request."""
        # Setup initial token
        client = Client()
        await client.authenticate(json.dumps(sample_token_response))

        # Updated token after refresh
        new_token_response = sample_token_response.copy()
        new_token_response["token"] = "refreshed_access_token"

        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            # First request fails with 401
            # Second request (after refresh) succeeds
            income_mock = respx_mock.post("/income")
            income_mock.side_effect = [
                httpx.Response(401, text="Unauthorized"),  # First attempt
                httpx.Response(
                    200, json={"approvedReceiptUuid": "test-uuid"}
                ),  # After refresh
            ]

            # Token refresh endpoint
            respx_mock.post("/auth/token").mock(
                return_value=httpx.Response(200, text=json.dumps(new_token_response))
            )

            # Make request that should trigger refresh
            income_api = client.income()
            result = await income_api.create("Test Service", 100, 1)

            # Verify successful result after refresh
            assert result["approvedReceiptUuid"] == "test-uuid"

            # Verify token was refreshed
            current_token = await client.get_access_token()
            current_data = json.loads(current_token)
            assert current_data["token"] == "refreshed_access_token"

    @pytest.mark.asyncio
    async def test_401_without_refresh_token_fails(self):
        """Test that 401 without valid refresh token fails."""
        # Setup token without refresh token
        token_without_refresh = {
            "token": "access_token",
            "profile": {"inn": "123456789012"},
        }

        client = Client()
        await client.authenticate(json.dumps(token_without_refresh))

        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            respx_mock.post("/income").mock(
                return_value=httpx.Response(401, text="Unauthorized")
            )

            income_api = client.income()

            with pytest.raises(UnauthorizedException):
                await income_api.create("Test Service", 100, 1)

    @pytest.mark.asyncio
    async def test_refresh_failure_propagates_401(self, sample_token_response):
        """Test that refresh failure propagates original 401 error."""
        client = Client()
        await client.authenticate(json.dumps(sample_token_response))

        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            # Income request fails with 401
            respx_mock.post("/income").mock(
                return_value=httpx.Response(401, text="Unauthorized")
            )

            # Refresh also fails
            respx_mock.post("/auth/token").mock(
                return_value=httpx.Response(401, text="Refresh failed")
            )

            income_api = client.income()

            with pytest.raises(UnauthorizedException):
                await income_api.create("Test Service", 100, 1)
