from datetime import date

from sqlalchemy import ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import Base


class Sku(Base):
    __tablename__ = "skus"

    sku_id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    category: Mapped[str]
    list_price: Mapped[float | None]
    discontinued: Mapped[bool]
    replaced_by: Mapped[str | None] = mapped_column(ForeignKey("skus.sku_id"))
    in_stock: Mapped[bool]


class Customer(Base):
    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    account_tier: Mapped[str]

    sites: Mapped[list["Site"]] = relationship(back_populates="customer")
    contracts: Mapped[list["Contract"]] = relationship(back_populates="customer")


class Site(Base):
    __tablename__ = "sites"

    site_id: Mapped[str] = mapped_column(primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"))
    address: Mapped[str]
    zip: Mapped[str]

    customer: Mapped[Customer] = relationship(back_populates="sites")


class Contract(Base):
    __tablename__ = "contracts"

    contract_id: Mapped[str] = mapped_column(primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"))
    discount_category: Mapped[str]
    covered_categories: Mapped[list[str]] = mapped_column(ARRAY(Text))
    effective_from: Mapped[date]
    effective_to: Mapped[date]
    discount_pct: Mapped[float] = mapped_column(server_default=text("0"))

    customer: Mapped[Customer] = relationship(back_populates="contracts")


class SkuRequirement(Base):
    __tablename__ = "sku_requirements"

    sku_id: Mapped[str] = mapped_column(ForeignKey("skus.sku_id"), primary_key=True)
    required_sku_id: Mapped[str] = mapped_column(ForeignKey("skus.sku_id"), primary_key=True)


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey("skus.sku_id"), index=True)
    unit_price: Mapped[float]
    quoted_on: Mapped[date]
