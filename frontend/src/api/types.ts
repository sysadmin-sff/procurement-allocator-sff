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
  website: string | null;
  region: string | null;
  catalog_link: string | null;
  status: string | null;
  payment_terms: string | null;
  portal_url: string | null;
  comments: string | null;
}

export interface SupplierCreate {
  name: string;
  contacts?: string | null;
  currency?: string;
  delivery_policy?: DeliveryPolicy;
}

/** PATCH-семантика: только заданные поля отправляются на backend, см. diff(). */
export interface SupplierUpdate {
  name?: string;
  contacts?: string | null;
  currency?: string;
  delivery_policy?: DeliveryPolicy;
  website?: string | null;
  region?: string | null;
  catalog_link?: string | null;
  status?: string | null;
  payment_terms?: string | null;
  portal_url?: string | null;
  comments?: string | null;
}

export interface Office {
  id: string;
  supplier_id: string;
  address: string;
  region: string | null;
}

export interface OfficeCreate {
  address: string;
  region?: string | null;
}

export interface OfficeUpdate {
  address?: string;
  region?: string | null;
}

export interface SupplierContact {
  id: string;
  supplier_id: string;
  office_id: string | null;
  name: string;
  role: string | null;
  phone: string | null;
  email: string | null;
}

export interface SupplierContactCreate {
  name: string;
  role?: string | null;
  phone?: string | null;
  email?: string | null;
  office_id?: string | null;
}

export interface SupplierContactUpdate {
  name?: string;
  role?: string | null;
  phone?: string | null;
  email?: string | null;
  office_id?: string | null;
}

/** GET /suppliers/{id} — offices/supplier_contacts вложены, не отдельными запросами. */
export interface SupplierDetail extends Supplier {
  offices: Office[];
  supplier_contacts: SupplierContact[];
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

export type ProjectStatus = 'draft' | 'calculated' | 'ordered' | 'completed';

export interface Project {
  id: string;
  title: string;
  created_by: string | null;
  status: ProjectStatus;
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
  ordered_at: string | null;
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

export interface OrderItem {
  id: string;
  order_id: string;
  material_id: string;
  quantity: number;
  quoted_price: number;
  confirmed_price: number | null;
  confirmed_at: string | null;
  price_delta: number | null;
  price_delta_pct: number | null;
}

export interface Order {
  id: string;
  project_id: string;
  supplier_id: string;
  status: string;
  total_amount: number;
  delivery_fee: number;
  items: OrderItem[];
}

/** One prior draft Order for a supplier already conflicting with the current
 * run — see ADR-0012. A supplier can have more than one (the bug ADR-0012
 * fixes produced exactly this), so this is always read as a list, never a
 * single value. */
export interface ExistingDraftOrder {
  order_id: string;
  total_amount: number;
  has_confirmed_prices: boolean;
}

export interface SupplierWithExistingDrafts {
  supplier_id: string;
  supplier_name: string;
  existing_draft_orders: ExistingDraftOrder[];
}

/** Body of the 409 POST .../orders returns when replace_drafts is not true
 * and a supplier in the run already has a draft Order in this project — see
 * ADR-0012 п.4. */
export interface OrderDraftConflict {
  detail: 'draft_orders_exist';
  suppliers_with_existing_drafts: SupplierWithExistingDrafts[];
}

export interface PurchaseRecord {
  id: string;
  project_id: string;
  supplier_id: string;
  raw_description: string;
  quantity: number;
  unit_price: number;
  material_id: string | null;
  created_at: string;
}

export interface PurchaseRecordCreate {
  supplier_id: string;
  raw_description: string;
  quantity: number;
  unit_price: number;
  material_id?: string | null;
}

export type PurchaseRecordUpdate = PurchaseRecordCreate;

/** planned_total/delta/delta_pct are null (not 0) when there is no Order yet
 * to compare against — see ADR-0008 п.4. */
export interface TotalComparison {
  purchased_total: number;
  planned_total: number | null;
  delta: number | null;
  delta_pct: number | null;
}

export interface SupplierTotal extends TotalComparison {
  supplier_id: string;
}

export interface PurchaseRecordListOut {
  records: PurchaseRecord[];
  project_total: TotalComparison;
  supplier_totals: SupplierTotal[];
}
