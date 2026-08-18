export interface DeliveryPolicy {
  flat_fee: number;
  free_shipping_threshold: number | null;
  per_order_min_amount: number;
  lead_time_days: number;
}

export interface Supplier {
  id: string;
  name: string;
  contacts: string | null;
  currency: string;
  delivery_policy: DeliveryPolicy;
}

export interface SupplierCreate {
  name: string;
  contacts?: string | null;
  currency?: string;
  delivery_policy?: DeliveryPolicy;
}

export interface Material {
  id: string;
  internal_sku: string;
  canonical_name: string;
  category: string | null;
  unit: string;
  attributes: Record<string, unknown>;
}

export interface MaterialCreate {
  internal_sku: string;
  canonical_name: string;
  category?: string | null;
  unit: string;
  attributes?: Record<string, unknown>;
}

export interface Price {
  id: string;
  material_id: string;
  supplier_id: string;
  price: number;
  currency: string;
  availability: number | null;
  min_order_qty: number | null;
  valid_from: string;
  valid_to: string | null;
  source_import_id: string | null;
}

export interface PriceCreate {
  material_id: string;
  supplier_id: string;
  price: number;
  currency?: string;
  availability?: number | null;
  min_order_qty?: number | null;
  valid_from: string;
  valid_to?: string | null;
}

export interface PriceUpdate {
  price?: number;
  currency?: string;
  availability?: number | null;
  min_order_qty?: number | null;
  valid_from: string;
  valid_to?: string | null;
}

export interface Project {
  id: string;
  title: string;
  created_by: string | null;
  status: string;
  created_at: string;
}

export interface ProjectCreate {
  title: string;
  created_by?: string | null;
}

export interface ProjectItem {
  id: string;
  project_id: string;
  material_id: string;
  quantity: number;
}

export interface ProjectItemCreate {
  material_id: string;
  quantity: number;
}

export interface LatestAllocationRun {
  id: string;
  created_at: string;
  status: AllocationRunStatus;
}

export interface ProjectWithItems extends Project {
  items: ProjectItem[];
  latest_allocation_run: LatestAllocationRun | null;
}

export interface AllocationLine {
  id: string;
  material_id: string;
  supplier_id: string;
  quantity: number;
  unit_price: number;
  line_total: number;
  overridden_at: string | null;
  original_supplier_id: string | null;
  original_unit_price: number | null;
}

export interface OrphanedMaterial {
  material_id: string;
  required_quantity: number;
  best_partial_supplier_id: string | null;
  best_partial_available: number | null;
}

export interface SupplierAllocationSummary {
  supplier_id: string;
  goods_total: number;
  delivery_fee: number;
  free_shipping_achieved: boolean;
  below_min_order: boolean;
}

export type AllocationRunStatus = 'ok' | 'infeasible';

export interface AllocationRun {
  id: string;
  project_id: string;
  created_at: string;
  algorithm_version: string | null;
  status: AllocationRunStatus;
  lines: AllocationLine[];
  orphaned_materials: OrphanedMaterial[];
  supplier_summaries: SupplierAllocationSummary[];
}
