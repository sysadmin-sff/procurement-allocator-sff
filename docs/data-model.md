# Модель данных

```mermaid
erDiagram
    Supplier ||--o{ Price : "предлагает"
    Supplier ||--o{ SupplierMaterialAlias : "называет по-своему"
    Material ||--o{ Price : "имеет цену у"
    Material ||--o{ SupplierMaterialAlias : "известен как"
    Material ||--o{ ProjectItem : "используется в"
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
    Price {
        uuid material_id
        uuid supplier_id
        decimal price
        string currency
        int availability
        date valid_from
        date valid_to
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
