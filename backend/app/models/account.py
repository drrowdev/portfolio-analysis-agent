import enum
import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class AccountType(str, enum.Enum):
    arvo_osuustili = "arvo_osuustili"
    osakesaastotili = "osakesaastotili"
    espp = "espp"
    crypto = "crypto"


class TaxTreatment(str, enum.Enum):
    standard = "standard"      # Arvo-osuustili: 30/34% capital gains per sale
    deferred = "deferred"      # OST: tax only on withdrawal growth
    espp = "espp"              # Fidelity ESPP: qualifying/disqualifying disposition
    crypto = "crypto"          # Crypto: 30/34% capital gains, FIFO cost basis


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255))
    broker: Mapped[str] = mapped_column(String(50))  # nordnet | fidelity
    account_type: Mapped[AccountType] = mapped_column(Enum(AccountType))
    external_id: Mapped[str] = mapped_column(String(50))
    currency: Mapped[str] = mapped_column(String(3))  # EUR | USD
    tax_treatment: Mapped[TaxTreatment] = mapped_column(Enum(TaxTreatment))
    ost_lifetime_deposits: Mapped[Optional[Decimal]] = mapped_column(default=None)

    holdings: Mapped[list["Holding"]] = relationship(back_populates="account")  # noqa: F821
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")  # noqa: F821
