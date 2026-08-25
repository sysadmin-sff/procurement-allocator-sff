from typing import TYPE_CHECKING

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.allocation import AllocationLine
    from app.models.office import Office
    from app.models.order import Order
    from app.models.price import Price
    from app.models.price_list import PriceListImport
    from app.models.supplier_contact import SupplierContact
    from app.models.supplier_material_alias import SupplierMaterialAlias


class Supplier(UUIDPKMixin, Base):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(50))
    """Ручное сокращение имени для компактных колонок (ADR-0017) — не участвует
    в allocation, не заменяет name нигде, кроме шапки PriceComparisonPage."""
    contacts: Mapped[str | None] = mapped_column(String(1000))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    delivery_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    """{flat_fee, free_shipping_threshold, per_order_min_amount, lead_time_days}"""
    website: Mapped[str | None] = mapped_column(String(500))
    region: Mapped[str | None] = mapped_column(String(255))
    catalog_link: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str | None] = mapped_column(String(255))
    """Свободный текст ("Активные закупки" и т.п.), не enum — см. ADR-0010."""
    payment_terms: Mapped[str | None] = mapped_column(String(100))
    """"NET 30" и т.п. — не то же самое, что delivery_policy, см. ADR-0010 п.3."""
    portal_url: Mapped[str | None] = mapped_column(String(500))
    comments: Mapped[str | None] = mapped_column(Text)

    prices: Mapped[list["Price"]] = relationship(back_populates="supplier")
    aliases: Mapped[list["SupplierMaterialAlias"]] = relationship(back_populates="supplier")
    price_list_imports: Mapped[list["PriceListImport"]] = relationship(back_populates="supplier")
    orders: Mapped[list["Order"]] = relationship(back_populates="supplier")
    allocation_lines: Mapped[list["AllocationLine"]] = relationship(
        back_populates="supplier", foreign_keys="AllocationLine.supplier_id"
    )
    offices: Mapped[list["Office"]] = relationship(back_populates="supplier")
    contacts_directory: Mapped[list["SupplierContact"]] = relationship(back_populates="supplier")
