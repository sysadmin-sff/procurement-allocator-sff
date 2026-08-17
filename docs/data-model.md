# Модель данных

```mermaid
erDiagram
    Supplier ||--o{ Price : "предлагает"
    Supplier ||--o{ SupplierMaterialAlias : "называет по-своему"
    Supplier ||--o{ PriceListImport : "прайс от"
    Material ||--o{ Price : "имеет цену у"
    Material ||--o{ SupplierMaterialAlias : "известен как"
    Material ||--o{ ProjectItem : "используется в"
    Material ||--o{ PriceListEntry : "сопоставлена со строкой"
    PriceListImport ||--o{ PriceListEntry : "содержит строки"
    PriceListImport ||--o{ Price : "источник цены"
    Project ||--o{ ProjectItem : "содержит"
    Project ||--o{ AllocationRun : "рассчитывается"
    AllocationRun ||--o{ AllocationLine : "состоит из"
    Project ||--o{ Order : "порождает"
    Order ||--o{ OrderItem : "содержит"
    Supplier ||--o{ Order : "получает"

    Supplier {
        uuid id
        string name
        string currency
        json delivery_policy
    }
    Material {
        uuid id
        string internal_sku "уникальный, канонический"
        string canonical_name
        string category
        string unit
    }
    SupplierMaterialAlias {
        uuid supplier_id
        uuid material_id
        string supplier_sku
        string supplier_raw_name
    }
    PriceListImport {
        uuid id
        uuid supplier_id
        string file_ref
        datetime uploaded_at
        string status "pending_review/approved/rejected"
        datetime parsed_by_ai_at
    }
    PriceListEntry {
        uuid id
        uuid import_id
        string supplier_raw_name
        string supplier_sku
        uuid matched_material_id "nullable — новый материал?"
        decimal confidence
        decimal price
        string currency
        int availability
        int min_order_qty
        string action "update/new/ignore"
    }
    Price {
        uuid material_id
        uuid supplier_id
        decimal price
        string currency
        int availability
        int min_order_qty
        date valid_from
        date valid_to
        uuid source_import_id "nullable"
    }
    Project {
        uuid id
        string title
        string status
    }
    ProjectItem {
        uuid project_id
        uuid material_id
        int quantity
    }
    AllocationRun {
        uuid id
        uuid project_id
        datetime created_at
        string algorithm_version
        json orphaned_materials "недостижимые материалы, см. ADR-0002"
    }
    AllocationLine {
        uuid allocation_run_id
        uuid material_id
        uuid supplier_id
        int quantity
        decimal unit_price
    }
    Order {
        uuid id
        uuid project_id
        uuid supplier_id
        string status
        decimal delivery_fee
    }
    OrderItem {
        uuid order_id
        uuid material_id
        int quantity
        decimal unit_price
    }
```

Правило, которое нельзя нарушать без ADR: `Material.internal_sku` — единственный источник истины
об идентичности материала. `SupplierMaterialAlias` — единственное место, где допустимы
дублирующиеся/расходящиеся названия.

`PriceListImport`/`PriceListEntry` добавлены сверх исходной диаграммы — см. `docs/decisions/0001-price-list-import-table.md`.
`PriceListEntry` — черновые строки на ревью (до аппрува, не пишутся в `Price` напрямую).

`AllocationRun.orphaned_materials` добавлено сверх исходной диаграммы — см.
`docs/decisions/0002-supplier-allocation-algorithm.md`. Список материалов проекта,
недостижимых ни у одного поставщика в нужном количестве; чисто информационный для UI,
не участвует в дальнейших расчётах.
