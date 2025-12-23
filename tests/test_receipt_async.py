"""
Async tests for Receipt API functionality.
Tests receipt URL composition and JSON data retrieval.
"""

import json

import httpx
import pytest
import respx

from nalogo.client import Client


@pytest.fixture
def authenticated_client():
    """Client with authentication set up."""
    sample_token = {
        "token": "test_access_token_example",
        "refreshToken": "test_refresh_token_example",
        "profile": {
            "inn": "123456789012",
            "displayName": "Test User",
        },
    }

    client = Client()
    return client, json.dumps(sample_token)


@pytest.fixture
def receipt_json_response():
    """Sample receipt JSON response."""
    return {
        "id": "test-receipt-uuid-123",
        "operationTime": "2024-01-01T12:00:00Z",
        "requestTime": "2024-01-01T12:00:00Z",
        "totalAmount": 100.0,
        "services": [
            {
                "name": "Test Service",
                "amount": "100.00",
                "quantity": "1",
            }
        ],
        "client": {
            "contactPhone": None,
            "displayName": None,
            "incomeType": "FROM_INDIVIDUAL",
            "inn": None,
        },
        "paymentType": "CASH",
        "approvedReceiptUuid": "test-receipt-uuid-123",
    }


class TestReceiptAPI:
    """Test Receipt API functionality."""

    @pytest.mark.asyncio
    async def test_print_url_composition(self, authenticated_client):
        """Test receipt print URL composition."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        receipt_api = client.receipt()

        # Test URL composition
        url = receipt_api.print_url("test-receipt-uuid-123")

        expected_url = "https://lknpd.nalog.ru/api/receipt/123456789012/test-receipt-uuid-123/print"
        assert url == expected_url

    @pytest.mark.asyncio
    async def test_print_url_empty_uuid_validation(self, authenticated_client):
        """Test validation error for empty receipt UUID in print_url."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        receipt_api = client.receipt()

        with pytest.raises(ValueError, match="Receipt UUID cannot be empty"):
            receipt_api.print_url("")

    @pytest.mark.asyncio
    async def test_print_url_whitespace_trimming(self, authenticated_client):
        """Test that print_url trims whitespace from UUID."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        receipt_api = client.receipt()

        url = receipt_api.print_url("  test-receipt-uuid-123  ")

        expected_url = "https://lknpd.nalog.ru/api/receipt/123456789012/test-receipt-uuid-123/print"
        assert url == expected_url

    @pytest.mark.asyncio
    async def test_json_success(self, authenticated_client, receipt_json_response):
        """Test successful receipt JSON retrieval."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            respx_mock.get("/receipt/123456789012/test-receipt-uuid-123/json").mock(
                return_value=httpx.Response(200, json=receipt_json_response)
            )

            receipt_api = client.receipt()
            result = await receipt_api.json("test-receipt-uuid-123")

            assert result["id"] == "test-receipt-uuid-123"
            assert result["totalAmount"] == 100.0
            assert len(result["services"]) == 1

    @pytest.mark.asyncio
    async def test_json_empty_uuid_validation(self, authenticated_client):
        """Test validation error for empty receipt UUID in json method."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        receipt_api = client.receipt()

        with pytest.raises(ValueError, match="Receipt UUID cannot be empty"):
            await receipt_api.json("")

    @pytest.mark.asyncio
    async def test_json_whitespace_trimming(
        self, authenticated_client, receipt_json_response
    ):
        """Test that json method trims whitespace from UUID."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            # Mock should expect trimmed UUID
            respx_mock.get("/receipt/123456789012/test-receipt-uuid-123/json").mock(
                return_value=httpx.Response(200, json=receipt_json_response)
            )

            receipt_api = client.receipt()
            result = await receipt_api.json("  test-receipt-uuid-123  ")

            assert result["id"] == "test-receipt-uuid-123"

    @pytest.mark.asyncio
    async def test_json_request_path_composition(
        self, authenticated_client, receipt_json_response
    ):
        """Test that json method composes correct request path."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            request_mock = respx_mock.get(
                "/receipt/123456789012/test-receipt-uuid-123/json"
            )
            request_mock.mock(
                return_value=httpx.Response(200, json=receipt_json_response)
            )

            receipt_api = client.receipt()
            await receipt_api.json("test-receipt-uuid-123")

            # Verify the exact path was called
            assert request_mock.called
            assert len(request_mock.calls) == 1

    @pytest.mark.asyncio
    async def test_receipt_api_requires_authenticated_user(self):
        """Test that Receipt API requires authenticated user with profile."""
        client = Client()

        # No authentication - should fail
        with pytest.raises(ValueError, match="User profile not available"):
            client.receipt()

    @pytest.mark.asyncio
    async def test_receipt_api_uses_user_inn_from_profile(self, authenticated_client):
        """Test that Receipt API uses INN from user profile."""
        _ = authenticated_client
        # Create client with different INN in profile
        custom_token = {
            "token": "test_access_token_example",
            "profile": {
                "inn": "987654321098",  # Different INN
                "displayName": "Custom User",
            },
        }

        client = Client()
        await client.authenticate(json.dumps(custom_token))

        receipt_api = client.receipt()

        # Test URL uses the profile INN
        url = receipt_api.print_url("test-uuid")
        expected_url = "https://lknpd.nalog.ru/api/receipt/987654321098/test-uuid/print"
        assert url == expected_url

    @pytest.mark.asyncio
    async def test_receipt_api_with_custom_base_url(self):
        """Test Receipt API with custom base URL."""
        custom_token = {
            "token": "test_access_token_example",
            "profile": {
                "inn": "123456789012",
                "displayName": "Test User",
            },
        }

        # Create client with custom base URL
        client = Client(base_url="https://custom.api.example.com/api")
        await client.authenticate(json.dumps(custom_token))

        receipt_api = client.receipt()

        # Test URL uses custom base URL
        url = receipt_api.print_url("test-uuid")
        expected_url = (
            "https://custom.api.example.com/api/receipt/123456789012/test-uuid/print"
        )
        assert url == expected_url
