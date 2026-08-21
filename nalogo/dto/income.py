"""
Income-related DTO models.
Based on PHP library's DTO and Enum classes.
"""

from datetime import datetime, tzinfo
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_serializer, field_validator

from ..timezone import (
    API_TIMEZONE,
    DEFAULT_INPUT_TIMEZONE,
    parse_datetime,
    resolve_timezone,
    to_api_timezone,
)


class IncomeType(StrEnum):
    """Income type enumeration. Maps to PHP Enum\\IncomeType."""

    FROM_INDIVIDUAL = "FROM_INDIVIDUAL"
    FROM_LEGAL_ENTITY = "FROM_LEGAL_ENTITY"
    FROM_FOREIGN_AGENCY = "FROM_FOREIGN_AGENCY"


class PaymentType(StrEnum):
    """Payment type enumeration. Maps to PHP Enum\\PaymentType."""

    CASH = "CASH"
    ACCOUNT = "ACCOUNT"


class CancelCommentType(StrEnum):
    """Cancel comment type enumeration. Maps to PHP Enum\\CancelCommentType."""

    CANCEL = "Чек сформирован ошибочно"
    REFUND = "Возврат средств"


class AtomDateTime(BaseModel):
    """
    DateTime wrapper for ISO/ATOM serialization.
    Maps to PHP DTO\\DateTime behavior.

    Values are always serialized in ``API_TIMEZONE`` (Moscow) with their
    offset, e.g. ``2025-12-28T00:30:00+03:00``. The tax authority reads the
    wall clock and ignores the offset, so sending any other zone would record
    the receipt at the wrong time.
    """

    model_config = {"arbitrary_types_allowed": True}

    value: datetime = Field(default_factory=lambda: datetime.now(API_TIMEZONE))
    input_tz: tzinfo = Field(default=DEFAULT_INPUT_TIMEZONE, exclude=True)

    @field_serializer("value")
    def serialize_datetime(self, dt: datetime) -> str:
        """Serialize to ATOM format in the timezone the API records."""
        # timespec="seconds" matches PHP's DATE_ATOM, which has no fractions
        return to_api_timezone(dt, self.input_tz).isoformat(timespec="seconds")

    @classmethod
    def now(cls, tz: str | tzinfo | None = None) -> "AtomDateTime":
        """
        Create AtomDateTime for the current moment.

        ``tz`` is accepted for symmetry with :meth:`from_datetime` but does not
        affect the result: "now" is an unambiguous instant.
        """
        return cls(value=datetime.now(API_TIMEZONE), input_tz=resolve_timezone(tz))

    @classmethod
    def from_datetime(
        cls, dt: datetime | str, tz: str | tzinfo | None = None
    ) -> "AtomDateTime":
        """
        Create AtomDateTime from a datetime object or ISO 8601 string.

        Values without an offset are read as wall clock time in ``tz``; values
        carrying one ignore it. Both end up in API_TIMEZONE.
        """
        input_tz = resolve_timezone(tz)
        return cls(value=parse_datetime(dt, input_tz), input_tz=input_tz)


class IncomeServiceItem(BaseModel):
    """
    Service item for income creation.
    Maps to PHP DTO\\IncomeServiceItem.
    """

    name: str = Field(..., description="Service name/description")
    amount: Decimal = Field(..., description="Service amount", gt=0)
    quantity: Decimal = Field(..., description="Service quantity", gt=0)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate name is not empty."""
        if not v.strip():
            raise ValueError("Name cannot be empty")
        return v.strip()

    @field_validator("amount", "quantity")
    @classmethod
    def validate_positive_decimal(cls, v: Decimal) -> Decimal:
        """Validate decimal values are positive."""
        if v <= 0:
            raise ValueError("Amount and quantity must be greater than 0")
        return v

    @field_serializer("amount", "quantity")
    def serialize_decimal(self, value: Decimal) -> str:
        """Serialize Decimal as string (like PHP BigDecimal)."""
        return str(value)

    def get_total_amount(self) -> Decimal:
        """Calculate total amount (amount * quantity)."""
        return self.amount * self.quantity

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Custom serialization to match PHP jsonSerialize format."""
        _ = kwargs
        return {
            "name": self.name,
            "amount": str(self.amount),
            "quantity": str(self.quantity),
        }


class IncomeClient(BaseModel):
    """
    Client information for income creation.
    Maps to PHP DTO\\IncomeClient.
    """

    contact_phone: str | None = Field(default=None, description="Client contact phone")
    display_name: str | None = Field(default=None, description="Client display name")
    income_type: IncomeType = Field(
        default=IncomeType.FROM_INDIVIDUAL, description="Income type"
    )
    inn: str | None = Field(default=None, description="Client INN (tax ID)")

    @field_validator("inn")
    @classmethod
    def validate_inn(cls, v: str | None, info: Any) -> str | None:
        """Validate INN format for legal entities."""
        _ = info
        if v is None:
            return v

        v = v.strip()
        if not v:
            return None

        if not v.isdigit():
            raise ValueError("INN must contain only numbers")

        # Check length (10 for legal entities, 12 for individuals)
        if len(v) not in [10, 12]:
            raise ValueError("INN length must be 10 or 12 digits")

        return v

    @field_validator("display_name")
    @classmethod
    def validate_display_name_for_legal_entity(
        cls, v: str | None, info: Any
    ) -> str | None:
        """Validate display name is provided for legal entities."""
        _ = info
        # Note: This validation is applied in the API layer in PHP,
        # but we can do basic validation here
        if v is not None:
            v = v.strip()
            if not v:
                return None
        return v

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Custom serialization to match PHP jsonSerialize format."""
        _ = kwargs
        return {
            "contactPhone": self.contact_phone,
            "displayName": self.display_name,
            "incomeType": self.income_type.value,
            "inn": self.inn,
        }


class IncomeRequest(BaseModel):
    """
    Complete income creation request.
    Maps to PHP request structure in Income::createMultipleItems().
    """

    operation_time: AtomDateTime = Field(default_factory=AtomDateTime.now)
    request_time: AtomDateTime = Field(default_factory=AtomDateTime.now)
    services: list[IncomeServiceItem] = Field(..., min_length=1)
    total_amount: str = Field(..., description="Total amount as string")
    client: IncomeClient = Field(default_factory=IncomeClient)
    payment_type: PaymentType = Field(default=PaymentType.CASH)
    ignore_max_total_income_restriction: bool = Field(default=False)

    @field_validator("services")
    @classmethod
    def validate_services(cls, v: list[IncomeServiceItem]) -> list[IncomeServiceItem]:
        """Validate services list is not empty."""
        if not v:
            raise ValueError("Services cannot be empty")
        return v

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Custom serialization to match PHP request format."""
        _ = kwargs
        return {
            "operationTime": self.operation_time.serialize_datetime(
                self.operation_time.value
            ),
            "requestTime": self.request_time.serialize_datetime(
                self.request_time.value
            ),
            "services": [service.model_dump() for service in self.services],
            "totalAmount": self.total_amount,
            "client": self.client.model_dump(),
            "paymentType": self.payment_type.value,
            "ignoreMaxTotalIncomeRestriction": self.ignore_max_total_income_restriction,
        }


class CancelRequest(BaseModel):
    """
    Income cancellation request.
    Maps to PHP request structure in Income::cancel().
    """

    operation_time: AtomDateTime = Field(default_factory=AtomDateTime.now)
    request_time: AtomDateTime = Field(default_factory=AtomDateTime.now)
    comment: CancelCommentType = Field(..., description="Cancellation reason")
    receipt_uuid: str = Field(..., description="Receipt UUID to cancel")
    partner_code: str | None = Field(default=None, description="Partner code")

    @field_validator("receipt_uuid")
    @classmethod
    def validate_receipt_uuid(cls, v: str) -> str:
        """Validate receipt UUID is not empty."""
        if not v.strip():
            raise ValueError("Receipt UUID cannot be empty")
        return v.strip()

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Custom serialization to match PHP request format."""
        _ = kwargs
        return {
            "operationTime": self.operation_time.serialize_datetime(
                self.operation_time.value
            ),
            "requestTime": self.request_time.serialize_datetime(
                self.request_time.value
            ),
            "comment": self.comment.value,
            "receiptUuid": self.receipt_uuid,
            "partnerCode": self.partner_code,
        }
