from typing import TYPE_CHECKING

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.price import Price
    from app.models.price_list import PriceListEntry
    from app.models.project import ProjectItem
    from app.models.supplier_material_alias import SupplierMaterialAlias


class Material(UUIDPKMixin, Base):
    __tablename__ = "materials"

    internal_sku: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    """диаметр, материал, класс и т.д. — для будущего фасетного поиска"""

    prices: Mapped[list["Price"]] = relationship(back_populates="material")
    aliases: Mapped[list["SupplierMaterialAlias"]] = relationship(back_populates="material")
    project_items: Mapped[list["ProjectItem"]] = relationship(back_populates="material")
    price_list_entries: Mapped[list["PriceListEntry"]] = relationship(
        back_populates="matched_material"
    )
