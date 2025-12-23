"""
PaymentType-related DTO models.
Based on PHP library's Model/PaymentType classes.
"""

from typing import Any

from pydantic import BaseModel, Field


class PaymentType(BaseModel):
    """
    Payment type model.
    Maps to PHP Model\\PaymentType\\PaymentType.
    """

    id: int = Field(..., description="Payment type ID")
    type: str = Field(..., description="Payment type")
    bank_name: str = Field(..., alias="bankName", description="Bank name")
    bank_bik: str = Field(..., alias="bankBik", description="Bank BIK")
    corr_account: str = Field(
        ..., alias="corrAccount", description="Correspondent account"
    )
    favorite: bool = Field(..., description="Is favorite payment type")
    phone: str | None = Field(None, description="Phone number")
    bank_id: str | None = Field(None, alias="bankId", description="Bank ID")
    current_account: str = Field(
        ..., alias="currentAccount", description="Current account"
    )
    available_for_pa: bool = Field(
        ..., alias="availableForPa", description="Available for PA"
    )

    def is_favorite(self) -> bool:
        """Check if this payment type is marked as favorite."""
        return self.favorite

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Custom serialization to match API format."""
        _ = kwargs
        return {
            "id": self.id,
            "type": self.type,
            "bankName": self.bank_name,
            "bankBik": self.bank_bik,
            "corrAccount": self.corr_account,
            "favorite": self.favorite,
            "phone": self.phone,
            "bankId": self.bank_id,
            "currentAccount": self.current_account,
            "availableForPa": self.available_for_pa,
        }


class PaymentTypeCollection(BaseModel):
    """
    Collection of payment types.
    Maps to PHP Model\\PaymentType\\PaymentTypeCollection.
    """

    payment_types: list[PaymentType] = Field(default_factory=list)

    def __iter__(self) -> Any:
        """Make collection iterable."""
        return iter(self.payment_types)

    def __len__(self) -> int:
        """Get collection length."""
        return len(self.payment_types)

    def __getitem__(self, index: int) -> PaymentType:
        """Get item by index."""
        return self.payment_types[index]
