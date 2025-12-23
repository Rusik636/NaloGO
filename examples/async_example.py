#!/usr/bin/env python3
"""
End-to-end async example for nalogo library.

This example demonstrates a complete workflow:
1. Phone challenge authentication
2. SMS verification
3. Income receipt creation
4. Receipt JSON retrieval
5. Receipt print URL generation

Note: This example uses mocked responses for demonstration.
For real usage, replace mock responses with actual SMS codes and API responses.
"""

import asyncio
import contextlib
import logging
from decimal import Decimal

from nalogo import Client
from nalogo.dto.income import IncomeClient, IncomeServiceItem, IncomeType
from nalogo.exceptions import (
    DomainException,
    PhoneException,
    UnauthorizedException,
    ValidationException,
)

# Configure logging to see the library's error handling
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


async def phone_challenge_flow_example():
    """
    Example: Phone challenge authentication flow.
    """

    try:
        client = Client()

        # Step 1: Start phone challenge
        phone = "79999999999"  # Example phone number

        # In real usage, this would send an SMS
        challenge_response = await client.create_phone_challenge(phone)

        # Step 2: Simulate SMS code verification
        # In real usage, get this from user input
        sms_code = str(input("Введите SMS код: "))  # Example SMS code

        token_json = await client.create_new_access_token_by_phone(
            phone, challenge_response["challengeToken"], sms_code
        )

        # Step 3: Authenticate client
        await client.authenticate(token_json)

        return client

    except PhoneException:
        return None
    except UnauthorizedException:
        return None
    except Exception:
        return None


async def income_creation_example(client: Client):
    """
    Example: Creating income receipts.
    """

    try:
        income_api = client.income()

        # Example 1: Simple receipt
        result = await income_api.create(
            name="Консультационные услуги", amount=Decimal("5000.00"), quantity=1
        )

        receipt_uuid = result.get("approvedReceiptUuid")

        # Example 2: Multiple items receipt
        services = [
            IncomeServiceItem(
                name="Разработка веб-сайта",
                amount=Decimal("25000.00"),
                quantity=Decimal("1"),
            ),
            IncomeServiceItem(
                name="Техническая поддержка",
                amount=Decimal("3000.00"),
                quantity=Decimal("3"),  # 3 months
            ),
        ]

        result = await income_api.create_multiple_items(services)
        multi_receipt_uuid = result.get("approvedReceiptUuid")

        # Example 3: Receipt for legal entity
        legal_client = IncomeClient(
            contact_phone="+79001234567",
            display_name="ООО 'Пример Технологии'",
            income_type=IncomeType.FROM_LEGAL_ENTITY,
            inn="1234567890",
        )

        result = await income_api.create(
            name="Разработка программного обеспечения",
            amount=Decimal("100000.00"),
            quantity=1,
            client=legal_client,
        )

        legal_receipt_uuid = result.get("approvedReceiptUuid")

        return receipt_uuid, multi_receipt_uuid, legal_receipt_uuid

    except ValidationException:
        return None, None, None
    except Exception:
        return None, None, None


async def receipt_operations_example(client: Client, receipt_uuid: str):
    """
    Example: Receipt operations.
    """

    try:
        receipt_api = client.receipt()

        # Example 1: Get receipt JSON data
        receipt_data = await receipt_api.json(receipt_uuid)

        # Example 2: Generate print URL
        receipt_api.print_url(receipt_uuid)

        return receipt_data

    except Exception:
        return None


async def additional_apis_example(client: Client):
    """
    Example: Additional API endpoints.
    """

    try:
        # User information
        user_api = client.user()
        await user_api.get()

        # Payment types
        payment_api = client.payment_type()
        await payment_api.table()

        favorite = await payment_api.favorite()
        if favorite:
            pass

        # Tax information
        tax_api = client.tax()
        await tax_api.get()

        # Tax history
        await tax_api.history()

    except Exception:
        pass


async def error_handling_example():
    """
    Example: Error handling and validation.
    """

    client = Client()

    # Example 1: Authentication error
    with contextlib.suppress(UnauthorizedException):
        await client.create_new_access_token(
            "invalid_inn_example", "invalid_password_example"
        )

    # Example 2: Validation error
    with contextlib.suppress(Exception):
        # This should fail validation
        IncomeServiceItem(name="", amount=Decimal("-100"), quantity=Decimal("0"))

    # Example 3: Phone challenge error
    with contextlib.suppress(PhoneException, DomainException, Exception):
        await client.create_phone_challenge("invalid_phone")


async def token_management_example():
    """
    Example: Token storage and management.
    """

    # Example with file-based token storage
    Client(storage_path="./example_token.json")

    # Example with custom device ID
    Client(device_id="my-custom-device-123")

    # Example with custom endpoint
    Client(base_url="https://custom.api.example.com/api")


async def main():
    """
    Main async example function.
    """

    # Example 1: Phone authentication flow
    # Note: In real usage, this would work with actual API
    try:
        client = await phone_challenge_flow_example()

        if client:
            # Example 2: Income creation
            receipt_uuids = await income_creation_example(client)

            if receipt_uuids[0]:
                # Example 3: Receipt operations
                await receipt_operations_example(client, receipt_uuids[0])

                # Example 4: Additional APIs
                await additional_apis_example(client)

    except Exception:
        pass

    # Example 5: Error handling
    await error_handling_example()

    # Example 6: Token management
    await token_management_example()


if __name__ == "__main__":
    # Run the async example
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception:
        pass
