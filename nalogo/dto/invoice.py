"""
Invoice-related DTO models.
Based on PHP library's DTO classes for invoices.

Note: Invoice functionality is marked as "Not implemented" in the PHP library,
but DTO structures are provided for future implementation.
"""

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_serializer


class InvoiceServiceItem(BaseModel):
    """
    Invoice service item model.
    Maps to PHP DTO\\InvoiceServiceItem.

    Similar to IncomeServiceItem but for invoices.
    """

    name: str = Field(..., description="Service name/description")
    amount: Decimal = Field(..., description="Service amount", gt=0)
    quantity: Decimal = Field(..., description="Service quantity", gt=0)

    @field_serializer("amount", "quantity")
    def serialize_decimal(self, value: Decimal) -> str:
        """Serialize Decimal as string."""
        return str(value)

    def get_total_amount(self) -> Decimal:
        """Calculate total amount (amount * quantity)."""
        return self.amount * self.quantity

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Custom serialization to match API format."""
        _ = kwargs
        return {
            "name": self.name,
            "amount": str(self.amount),
            "quantity": str(self.quantity),
        }


class InvoiceClient(BaseModel):
    """
    Invoice client information model.
    Maps to PHP DTO\\InvoiceClient.

    Similar to IncomeClient but for invoices.
    """

    contact_phone: str | None = Field(
        None, alias="contactPhone", description="Client contact phone"
    )
    display_name: str | None = Field(
        None, alias="displayName", description="Client display name"
    )
    inn: str | None = Field(None, description="Client INN")

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Custom serialization to match API format."""
        _ = kwargs
        return {
            "contactPhone": self.contact_phone,
            "displayName": self.display_name,
            "inn": self.inn,
        }
