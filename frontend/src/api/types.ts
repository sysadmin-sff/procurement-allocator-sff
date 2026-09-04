export type UserRole = 'admin' | 'employee';

/** Response body of GET /auth/me — see ADR-0024 §2/§4. */
export interface CurrentUser {
  id: string;
  email: string;
  name: string | null;
  role: UserRole;
}

/** Row shape from GET/POST/PATCH /users — admin-only, ADR-0024 §2. */
export interface User {
  id: string;
  email: string;
  name: string | null;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface UserCreate {
  email: string;
  role: UserRole;
}

/** PATCH-семантика: только заданные поля отправляются на backend, см. diff(). */
export interface UserUpdate {
  role?: UserRole;
  is_active?: boolean;
}

export interface DeliveryPolicy {
  flat_fee: number;
  free_shipping_threshold: number | null;
  per_order_min_amount: number;
  lead_time_days: number;
}

export interface Supplier {
  id: string;
  name: string;
  short_name: string | null;
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
  short_name?: string | null;
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

/** One supplier's active Price for a material — "План" section, ADR-0016 §1/§4. */
export interface PlanCandidate {
  supplier_id: string;
  supplier_name: string;
  price: number;
  availability: number | null;
  is_cheapest: boolean;
}

/** One supplier's Order-derived response for a material — "Ответы поставщиков"
 * section, ADR-0016 §1/§3/§4. Only suppliers with an Order containing the
 * material appear. */
export interface SupplierResponse {
  supplier_id: string;
  supplier_name: string;
  quoted_price: number;
  received_price: number | null;
  confirmed_price: number | null;
  declined_at: string | null;
  decline_reason: string | null;
  is_cheapest: boolean;
}

export interface MaterialComparisonRow {
  project_item_id: string;
  material_id: string;
  plan: PlanCandidate[];
  supplier_responses: SupplierResponse[];
}

export interface PriceComparisonOut {
  rows: MaterialComparisonRow[];
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
  /** Strict categories (Doors/Gutter/Profil/Mesh/Roof panels) actually split
   * across more than one supplier in the current line state — see ADR-0028 §4. */
  split_categories: string[];
}

export interface OrderItem {
  id: string;
  order_id: string;
  material_id: string;
  quantity: number;
  quoted_price: number;
  received_price: number | null;
  /** Наша целевая цена для торга — не факт от поставщика. См. ADR-0027. */
  target_price: number | null;
  confirmed_price: number | null;
  confirmed_at: string | null;
  declined_at: string | null;
  decline_reason: string | null;
  price_delta: number | null;
  price_delta_pct: number | null;
  /** quoted vs received (не quoted vs confirmed, как price_delta) — см.
   * ADR-0027 §3. NULL при received_price === null, не 0. */
  received_price_delta: number | null;
  received_price_delta_pct: number | null;
  /** Derived, not persisted — see ADR-0014 п.3. Set only when this declined
   * item caused the current override of its material's line in the
   * project's latest AllocationRun. */
  replaced_by_supplier_id: string | null;
  replaced_by_supplier_name: string | null;
  /** Non-null if replaced_by_supplier_id has an existing draft Order in
   * this project — see ADR-0014 п.3. */
  replacement_draft_order_id: string | null;
}

/** One supplier candidate from POST .../find-replacement — see ADR-0014 п.1. */
export interface ReplacementCandidate {
  supplier_id: string;
  supplier_name: string;
  price: number;
  availability: number | null;
  availability_risk: boolean;
}

/** Response body for POST .../find-replacement — see ADR-0014 п.5. line_id
 * is the AllocationLine to PATCH (ADR-0006) when a candidate is picked. */
export interface FindReplacementResult {
  line_id: string;
  candidates: ReplacementCandidate[];
}

export interface Order {
  id: string;
  project_id: string;
  supplier_id: string;
  status: string;
  total_amount: number;
  delivery_fee: number;
  /** Derived, non-persistent — computed on GET, see ADR-0026 §1. */
  expected_goods_total: number;
  expected_delivery_fee: number;
  expected_total: number;
  declined_amount: number;
  /** Derived, non-persistent — see ADR-0026 §2. */
  fully_declined: boolean;
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

/** One row of POST .../parse-response's "matched" category — see ADR-0018 §3a. */
export interface ParsedMatchedLine {
  order_item_id: string;
  raw_description: string;
  price: number;
  quantity: number | null;
  confidence: string;
  reasoning: string;
}

/** One row of POST .../parse-response's "missing" category — see ADR-0018 §3b. */
export interface ParsedMissingItem {
  order_item_id: string;
  material_id: string;
  canonical_name: string;
  quantity: number;
  quoted_price: number;
}

/** One row of POST .../parse-response's "extra" category — see ADR-0018 §3c. */
export interface ParsedExtraLine {
  raw_description: string;
  price: number;
  quantity: number | null;
  confidence: string;
  reasoning: string;
}

/** Response body of POST /orders/{order_id}/parse-response — a preview,
 * nothing here is persisted server-side. See ADR-0018 §3. */
export interface ParseOrderResponseResult {
  matched: ParsedMatchedLine[];
  missing: ParsedMissingItem[];
  extra: ParsedExtraLine[];
}

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

/** One row of a price-list import — see ADR-0019 §4-5, ADR-0020.
 * `action` is null until the review screen applies or skips the row; until
 * then, the AI's *proposed* action is implicit: matched_material_id != null
 * means "match" was proposed, null means "new" was proposed (with
 * suggested_internal_sku as the draft SKU). */
export interface PriceListEntry {
  id: string;
  supplier_raw_name: string;
  supplier_sku: string | null;
  matched_material_id: string | null;
  confidence: number | null;
  reasoning: string | null;
  price: number;
  currency: string;
  availability: number | null;
  min_order_qty: number | null;
  action: 'match' | 'new' | 'skip' | null;
  suggested_internal_sku: string | null;
  possible_duplicate_of: string[];
}

export type PriceListImportStatus = 'pending_review' | 'approved' | 'rejected';

export interface PriceListImport {
  import_id: string;
  status: PriceListImportStatus;
  entries: PriceListEntry[];
}

export type ApplyPriceListEntryIn =
  | { action: 'match'; material_id: string }
  | { action: 'new'; internal_sku: string; canonical_name: string }
  | { action: 'skip' };
