"""
Async tests for Income API functionality.
Tests income creation, cancellation, and validation.
"""

import json
from decimal import Decimal

import httpx
import pytest
import respx
from pydantic import ValidationError

from nalogo.client import Client
from nalogo.dto.income import (
    CancelCommentType,
    IncomeClient,
    IncomeServiceItem,
    IncomeType,
)


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
    # Use asyncio.run or similar in actual test
    return client, json.dumps(sample_token)


@pytest.fixture
def income_response():
    """Sample income creation response."""
    return {"approvedReceiptUuid": "test-receipt-uuid-123"}


@pytest.fixture
def cancel_response():
    """Sample income cancellation response."""
    return {
        "incomeInfo": {
            "approvedReceiptUuid": "test-receipt-uuid-123",
            "name": "Test Service",
            "operationTime": "2024-01-01T12:00:00Z",
            "requestTime": "2024-01-01T12:00:00Z",
            "paymentType": "CASH",
            "partnerCode": None,
            "totalAmount": 100.0,
            "cancellationInfo": {
                "operationTime": "2024-01-01T12:01:00Z",
                "registerTime": "2024-01-01T12:01:00Z",
                "taxPeriodId": 202401,
                "comment": "Возврат средств",
            },
            "sourceDeviceId": "test-device-id",
        }
    }


class TestIncomeAPI:
    """Test Income API functionality."""

    @pytest.mark.asyncio
    async def test_create_single_item_success(
        self, authenticated_client, income_response
    ):
        """Test successful creation of income with single item."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            respx_mock.post("/income").mock(
                return_value=httpx.Response(200, json=income_response)
            )

            income_api = client.income()
            result = await income_api.create("Test Service", 100, 1)

            assert result["approvedReceiptUuid"] == "test-receipt-uuid-123"

    @pytest.mark.asyncio
    async def test_create_multiple_items_success(
        self, authenticated_client, income_response
    ):
        """Test successful creation of income with multiple items."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            respx_mock.post("/income").mock(
                return_value=httpx.Response(200, json=income_response)
            )

            services = [
                IncomeServiceItem(
                    name="Service 1", amount=Decimal("100.50"), quantity=Decimal("1")
                ),
                IncomeServiceItem(
                    name="Service 2", amount=Decimal("200.25"), quantity=Decimal("2")
                ),
            ]

            income_api = client.income()
            result = await income_api.create_multiple_items(services)

            assert result["approvedReceiptUuid"] == "test-receipt-uuid-123"

    @pytest.mark.asyncio
    async def test_create_with_custom_client(
        self, authenticated_client, income_response
    ):
        """Test income creation with custom client information."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            request_mock = respx_mock.post("/income")
            request_mock.mock(return_value=httpx.Response(200, json=income_response))

            custom_client = IncomeClient(
                contact_phone="+79001234567",
                display_name="Custom Client",
                income_type=IncomeType.FROM_INDIVIDUAL,
                inn="123456789012",
            )

            income_api = client.income()
            result = await income_api.create(
                "Test Service", 100, 1, client=custom_client
            )

            assert result["approvedReceiptUuid"] == "test-receipt-uuid-123"

            # Verify request body contains custom client data
            request = request_mock.calls[0].request
            request_data = json.loads(request.content.decode())
            assert request_data["client"]["contactPhone"] == "+79001234567"
            assert request_data["client"]["displayName"] == "Custom Client"

    @pytest.mark.asyncio
    async def test_total_amount_calculation(
        self, authenticated_client, income_response
    ):
        """Test that total amount is calculated correctly from multiple items."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            request_mock = respx_mock.post("/income")
            request_mock.mock(return_value=httpx.Response(200, json=income_response))

            services = [
                IncomeServiceItem(
                    name="Service 1", amount=Decimal("100.50"), quantity=Decimal("2")
                ),  # 201.00
                IncomeServiceItem(
                    name="Service 2", amount=Decimal("50.25"), quantity=Decimal("3")
                ),  # 150.75
            ]

            income_api = client.income()
            await income_api.create_multiple_items(services)

            # Verify total amount calculation
            request = request_mock.calls[0].request
            request_data = json.loads(request.content.decode())
            assert request_data["totalAmount"] == "351.75"

    @pytest.mark.asyncio
    async def test_create_empty_services_validation(self, authenticated_client):
        """Test validation error for empty services list."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        income_api = client.income()

        with pytest.raises(ValueError, match="Services cannot be empty"):
            await income_api.create_multiple_items([])

    @pytest.mark.asyncio
    async def test_create_legal_entity_validation_success(
        self, authenticated_client, income_response
    ):
        """Test successful validation for legal entity client."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            respx_mock.post("/income").mock(
                return_value=httpx.Response(200, json=income_response)
            )

            legal_client = IncomeClient(
                display_name="LLC Company",
                income_type=IncomeType.FROM_LEGAL_ENTITY,
                inn="1234567890",  # 10 digits for legal entity
            )

            income_api = client.income()
            result = await income_api.create("Service", 100, 1, client=legal_client)

            assert result["approvedReceiptUuid"] == "test-receipt-uuid-123"

    @pytest.mark.asyncio
    async def test_create_legal_entity_validation_missing_inn(
        self, authenticated_client
    ):
        """Test validation error for legal entity without INN."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        legal_client = IncomeClient(
            display_name="LLC Company",
            income_type=IncomeType.FROM_LEGAL_ENTITY,
            inn=None,  # Missing INN
        )

        income_api = client.income()

        # Mock HTTP to avoid real requests - we're testing validation logic
        with (
            respx.mock(base_url="https://lknpd.nalog.ru/api/v1"),
            pytest.raises(
                ValueError, match="Client INN cannot be empty for legal entity"
            ),
        ):
            await income_api.create("Service", 100, 1, client=legal_client)

    @pytest.mark.asyncio
    async def test_create_legal_entity_validation_missing_display_name(
        self, authenticated_client
    ):
        """Test validation error for legal entity without display name."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        legal_client = IncomeClient(
            display_name=None,  # Missing display name
            income_type=IncomeType.FROM_LEGAL_ENTITY,
            inn="1234567890",
        )

        income_api = client.income()

        # Mock HTTP to avoid real requests - we're testing validation logic
        with (
            respx.mock(base_url="https://lknpd.nalog.ru/api/v1"),
            pytest.raises(
                ValueError, match="Client DisplayName cannot be empty for legal entity"
            ),
        ):
            await income_api.create("Service", 100, 1, client=legal_client)

    @pytest.mark.asyncio
    async def test_cancel_success(self, authenticated_client, cancel_response):
        """Test successful income cancellation."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            respx_mock.post("/cancel").mock(
                return_value=httpx.Response(200, json=cancel_response)
            )

            income_api = client.income()
            result = await income_api.cancel(
                "test-receipt-uuid-123", CancelCommentType.REFUND
            )

            assert (
                result["incomeInfo"]["approvedReceiptUuid"] == "test-receipt-uuid-123"
            )
            assert (
                result["incomeInfo"]["cancellationInfo"]["comment"] == "Возврат средств"
            )

    @pytest.mark.asyncio
    async def test_cancel_with_string_comment(
        self, authenticated_client, cancel_response
    ):
        """Test cancellation with string comment (should convert to enum)."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        with respx.mock(base_url="https://lknpd.nalog.ru/api/v1") as respx_mock:
            request_mock = respx_mock.post("/cancel")
            request_mock.mock(return_value=httpx.Response(200, json=cancel_response))

            income_api = client.income()
            await income_api.cancel(
                "test-receipt-uuid-123", "Возврат средств"  # String instead of enum
            )

            # Verify request contains correct comment
            request = request_mock.calls[0].request
            request_data = json.loads(request.content.decode())
            assert request_data["comment"] == "Возврат средств"

    @pytest.mark.asyncio
    async def test_cancel_empty_uuid_validation(self, authenticated_client):
        """Test validation error for empty receipt UUID."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        income_api = client.income()

        with pytest.raises(ValueError, match="Receipt UUID cannot be empty"):
            await income_api.cancel("", CancelCommentType.CANCEL)

    @pytest.mark.asyncio
    async def test_cancel_invalid_comment_validation(self, authenticated_client):
        """Test validation error for invalid comment string."""
        client, token_json = authenticated_client
        await client.authenticate(token_json)

        income_api = client.income()

        with pytest.raises(ValueError, match="Comment is invalid"):
            await income_api.cancel("test-uuid", "Invalid comment")


class TestIncomeServiceItem:
    """Test IncomeServiceItem DTO validation and serialization."""

    def test_valid_service_item_creation(self):
        """Test creation of valid service item."""
        item = IncomeServiceItem(
            name="Test Service", amount=Decimal("100.50"), quantity=Decimal("2")
        )

        assert item.name == "Test Service"
        assert item.amount == Decimal("100.50")
        assert item.quantity == Decimal("2")
        assert item.get_total_amount() == Decimal("201.00")

    def test_service_item_validation_empty_name(self):
        """Test validation error for empty name."""
        with pytest.raises(ValueError, match="Name cannot be empty"):
            IncomeServiceItem(name="", amount=Decimal("100"), quantity=Decimal("1"))

    def test_service_item_validation_negative_amount(self):
        """Test validation error for negative amount."""
        with pytest.raises(ValidationError, match="Input should be greater than 0"):
            IncomeServiceItem(
                name="Service", amount=Decimal("-100"), quantity=Decimal("1")
            )

    def test_service_item_validation_zero_quantity(self):
        """Test validation error for zero quantity."""
        with pytest.raises(ValidationError, match="Input should be greater than 0"):
            IncomeServiceItem(
                name="Service", amount=Decimal("100"), quantity=Decimal("0")
            )

    def test_service_item_serialization(self):
        """Test service item serialization to match PHP format."""
        item = IncomeServiceItem(
            name="Test Service", amount=Decimal("100.50"), quantity=Decimal("2")
        )

        serialized = item.model_dump()

        assert serialized == {
            "name": "Test Service",
            "amount": "100.50",
            "quantity": "2",
        }


class TestIncomeClient:
    """Test IncomeClient DTO validation and serialization."""

    def test_default_income_client(self):
        """Test default income client creation."""
        client = IncomeClient()

        assert client.contact_phone is None
        assert client.display_name is None
        assert client.income_type == IncomeType.FROM_INDIVIDUAL
        assert client.inn is None

    def test_income_client_serialization(self):
        """Test income client serialization to match PHP format."""
        client = IncomeClient(
            contact_phone="+79001234567",
            display_name="Test Client",
            income_type=IncomeType.FROM_LEGAL_ENTITY,
            inn="1234567890",
        )

        serialized = client.model_dump()

        assert serialized == {
            "contactPhone": "+79001234567",
            "displayName": "Test Client",
            "incomeType": "FROM_LEGAL_ENTITY",
            "inn": "1234567890",
        }

    def test_inn_validation_valid_lengths(self):
        """Test INN validation for valid lengths (10 and 12 digits)."""
        # 10 digits for legal entity
        client1 = IncomeClient(inn="1234567890")
        assert client1.inn == "1234567890"

        # 12 digits for individual
        client2 = IncomeClient(inn="123456789012")
        assert client2.inn == "123456789012"

    def test_inn_validation_invalid_length(self):
        """Test INN validation for invalid length."""
        with pytest.raises(ValueError, match="INN length must be 10 or 12 digits"):
            IncomeClient(inn="123456789")  # 9 digits

    def test_inn_validation_non_numeric(self):
        """Test INN validation for non-numeric input."""
        with pytest.raises(ValueError, match="INN must contain only numbers"):
            IncomeClient(inn="12345abcde")
