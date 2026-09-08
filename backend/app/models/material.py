from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
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
    color_options: Mapped[list[str] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    """Цвета, доступные для этого материала без изменения цены — извлечены
    из canonical_name при импорте, не пересчитываются на чтении. NULL или
    пустой список = материал не имеет цветового выбора. Список из ровно
    одного элемента отличается от NULL семантически, хотя для текущего
    каталога не встречается. См. ADR-0031.

    none_as_null=True: without it, SQLAlchemy's JSON type writes the JSON
    literal null for an explicitly-assigned Python None (distinct from SQL
    NULL at the storage level), which would silently break every
    `color_options IS NULL` filter (backfill script, create_orders_for_run's
    guard) for any material that ever had None assigned directly rather than
    left untouched at its column default."""
    color_fragment: Mapped[str | None] = mapped_column(String(50), nullable=True)
    """Точная подстрока в canonical_name, подлежащая замене при разрешении
    цвета (см. resolve_material_name) — например "(White/Bronze)" или
    "Bronze/White". Заполняется тем же проходом, что и color_options.
    См. ADR-0031 п.4."""
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    """text-embedding-3-small эмбеддинг canonical_name + attributes — см.
    ADR-0019 §1. NULL до бэкафилла/при сбое embeddings API (graceful
    degradation), исключается из векторного поиска матчинга."""

    prices: Mapped[list["Price"]] = relationship(back_populates="material")
    aliases: Mapped[list["SupplierMaterialAlias"]] = relationship(back_populates="material")
    project_items: Mapped[list["ProjectItem"]] = relationship(back_populates="material")
    price_list_entries: Mapped[list["PriceListEntry"]] = relationship(
        back_populates="matched_material"
    )
