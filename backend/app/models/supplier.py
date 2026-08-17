from typing import TYPE_CHECKING

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.allocation import AllocationLine
    from app.models.order import Order
    from app.models.price import Price
    from app.models.price_list import PriceListImport
    from app.models.supplier_material_alias import SupplierMaterialAlias


class Supplier(UUIDPKMixin, Base):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contacts: Mapped[str | None] = mapped_column(String(1000))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    delivery_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    """{flat_fee, free_shipping_threshold, per_order_min_amount, lead_time_days}"""

    prices: Mapped[list["Price"]] = relationship(back_populates="supplier")
    aliases: Mapped[list["SupplierMaterialAlias"]] = relationship(back_populates="supplier")
    price_list_imports: Mapped[list["PriceListImport"]] = relationship(back_populates="supplier")
    orders: Mapped[list["Order"]] = relationship(back_populates="supplier")
    allocation_lines: Mapped[list["AllocationLine"]] = relationship(back_populates="supplier")
