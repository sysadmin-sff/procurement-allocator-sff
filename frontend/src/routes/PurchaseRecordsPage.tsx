import { forwardRef, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { materialsApi } from '../api/materials';
import { ordersApi } from '../api/orders';
import { projectsApi } from '../api/projects';
import { purchaseRecordsApi } from '../api/purchaseRecords';
import { suppliersApi } from '../api/suppliers';
import type {
  Material,
  Order,
  Project,
  PurchaseRecord,
  PurchaseRecordListOut,
  Supplier,
  SupplierTotal,
  TotalComparison,
} from '../api/types';
import { Button } from '../components/Button';
import { ConfirmButton } from '../components/ConfirmButton';
import { ErrorBanner } from '../components/ErrorBanner';
import styles from './purchase-records/PurchaseRecords.module.css';

interface LoadedData {
  project: Project;
  orders: Order[];
  suppliers: Supplier[];
  materials: Material[];
  purchaseData: PurchaseRecordListOut;
}

interface DraftRecord {
  supplier_id: string;
  raw_description: string;
  quantity: string;
  unit_price: string;
  material_id: string;
}

const EMPTY_DRAFT: DraftRecord = {
  supplier_id: '',
  raw_description: '',
  quantity: '',
  unit_price: '',
  material_id: '',
};

export function PurchaseRecordsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [data, setData] = useState<LoadedData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [draft, setDraft] = useState<DraftRecord>(EMPTY_DRAFT);
  const addRecordRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!projectId) return;
    void load(projectId);
  }, [projectId]);

  async function load(id: string) {
    setLoading(true);
    setLoadError(null);
    try {
      const [project, orders, suppliers, materials, purchaseData] = await Promise.all([
        projectsApi.get(id),
        ordersApi.listForProject(id),
        suppliersApi.list(),
        materialsApi.list(),
        purchaseRecordsApi.listForProject(id),
      ]);
      setData({ project, orders, suppliers, materials, purchaseData });
    } catch (err) {
      setLoadError(err);
    } finally {
      setLoading(false);
    }
  }

  async function refreshPurchaseData(id: string) {
    const purchaseData = await purchaseRecordsApi.listForProject(id);
    setData((prev) => (prev ? { ...prev, purchaseData } : prev));
  }

  async function handleCreate(payload: Parameters<typeof purchaseRecordsApi.create>[1]) {
    if (!projectId) return;
    setActionError(null);
    try {
      await purchaseRecordsApi.create(projectId, payload);
      await refreshPurchaseData(projectId);
      setDraft(EMPTY_DRAFT);
    } catch (err) {
      setActionError(err);
      throw err;
    }
  }

  /** "→ в факт" on a plan line — pre-fills the add-record form with that
   * line's values for the common case where it matched exactly, and scrolls
   * to it. Does not create a PurchaseRecord by itself — the user still has
   * to review and press "+ Добавить" (ADR-0008 п.3 keeps automatic plan/fact
   * matching out of scope; this only saves retyping for a manual match). */
  function handleCopyPlanLineToFact(supplierId: string, line: {
    raw_description: string;
    quantity: number;
    unit_price: number;
    material_id: string;
  }) {
    setDraft({
      supplier_id: supplierId,
      raw_description: line.raw_description,
      quantity: String(line.quantity),
      unit_price: String(line.unit_price),
      material_id: line.material_id,
    });
    addRecordRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  async function handleUpdate(
    record: PurchaseRecord,
    payload: Parameters<typeof purchaseRecordsApi.update>[2],
  ) {
    if (!projectId) return;
    setActionError(null);
    try {
      await purchaseRecordsApi.update(projectId, record.id, payload);
      await refreshPurchaseData(projectId);
    } catch (err) {
      setActionError(err);
    }
  }

  async function handleDelete(record: PurchaseRecord) {
    if (!projectId) return;
    setActionError(null);
    try {
      await purchaseRecordsApi.remove(projectId, record.id);
      await refreshPurchaseData(projectId);
    } catch (err) {
      setActionError(err);
    }
  }

  if (!projectId) {
    return <ErrorBanner error="Не указан проект." />;
  }

  if (loading) {
    return <div className={styles.centerWrap}>Загрузка…</div>;
  }

  if (loadError || !data) {
    return (
      <div className={styles.centerWrap}>
        <ErrorBanner error={loadError} />
      </div>
    );
  }

  const { project, orders, suppliers, materials, purchaseData } = data;
  const supplierIds = collectSupplierIds(orders, purchaseData.records);

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <Link to={`/projects/${projectId}`} className={styles.backLink}>
          « Назад к проекту
        </Link>

        <div className={styles.header}>
          <h1 className={styles.title}>Фактическая закупка — {project.title}</h1>
        </div>

        {actionError != null && <ErrorBanner error={actionError} />}

        <ProjectTotalsCard total={purchaseData.project_total} supplierCount={supplierIds.length} />

        <AddRecordCard
          ref={addRecordRef}
          suppliers={suppliers}
          materials={materials}
          draft={draft}
          onDraftChange={setDraft}
          onCreate={handleCreate}
        />

        {supplierIds.length === 0 && (
          <div className={styles.emptyColumn}>
            Нет ни плановых ордеров, ни фактических записей по этому проекту.
          </div>
        )}

        {supplierIds.map((supplierId) => (
          <SupplierSection
            key={supplierId}
            supplier={suppliers.find((s) => s.id === supplierId)}
            supplierId={supplierId}
            orders={orders.filter((o) => o.supplier_id === supplierId)}
            records={purchaseData.records.filter((r) => r.supplier_id === supplierId)}
            supplierTotal={purchaseData.supplier_totals.find((t) => t.supplier_id === supplierId)}
            materials={materials}
            allSuppliers={suppliers}
            onUpdate={handleUpdate}
            onDelete={handleDelete}
            onCopyToFact={handleCopyPlanLineToFact}
          />
        ))}
      </div>
    </div>
  );
}

/** Union of every supplier that has either a plan (Order) or a fact
 * (PurchaseRecord) in this project — an unplanned "с колёс" supplier
 * (records but no Order) must still appear. See ADR-0008 п.2. */
function collectSupplierIds(orders: Order[], records: PurchaseRecord[]): string[] {
  const ids = new Set<string>();
  for (const order of orders) ids.add(order.supplier_id);
  for (const record of records) ids.add(record.supplier_id);
  return [...ids];
}

function ProjectTotalsCard({
  total,
  supplierCount,
}: {
  total: TotalComparison;
  supplierCount: number;
}) {
  return (
    <div className={styles.totalsCard}>
      <div className={styles.totalsFigure}>
        <span className={styles.totalsLabel}>Куплено по факту</span>
        <span className={styles.totalsValue}>{formatMoney(total.purchased_total)}</span>
      </div>

      {total.planned_total != null ? (
        <>
          <div className={styles.totalsFigure}>
            <span className={styles.totalsLabel}>По плану (сумма ордеров)</span>
            <span className={styles.totalsValue}>{formatMoney(total.planned_total)}</span>
          </div>
          <div className={styles.totalsFigure}>
            <span className={styles.totalsLabel}>Расхождение</span>
            <DeltaText delta={total.delta} deltaPct={total.delta_pct} />
          </div>
        </>
      ) : (
        <div className={styles.totalsNoPlan}>
          ⚠ Ни для одного поставщика в проекте ещё не создан ордер — сравнить факт с
          планом пока не с чем.
        </div>
      )}

      {supplierCount === 0 && total.purchased_total === 0 && (
        <span className={styles.totalsLabel}>Записей пока нет</span>
      )}
    </div>
  );
}

function DeltaText({ delta, deltaPct }: { delta: number | null; deltaPct: number | null }) {
  if (delta == null || deltaPct == null) {
    return <span className={styles.totalsDelta}>—</span>;
  }
  const cls =
    delta > 0 ? styles.totalsDeltaOver : delta < 0 ? styles.totalsDeltaUnder : styles.totalsDelta;
  return (
    <span className={`${styles.totalsDelta} ${cls}`}>
      {delta >= 0 ? '+' : ''}
      {formatMoney(delta)} ({deltaPct >= 0 ? '+' : ''}
      {deltaPct.toFixed(1)}%)
    </span>
  );
}

function SupplierSection({
  supplier,
  supplierId,
  orders,
  records,
  supplierTotal,
  materials,
  allSuppliers,
  onUpdate,
  onDelete,
  onCopyToFact,
}: {
  supplier: Supplier | undefined;
  supplierId: string;
  orders: Order[];
  records: PurchaseRecord[];
  supplierTotal: SupplierTotal | undefined;
  materials: Material[];
  allSuppliers: Supplier[];
  onUpdate: (record: PurchaseRecord, payload: Parameters<typeof purchaseRecordsApi.update>[2]) => void;
  onDelete: (record: PurchaseRecord) => void;
  onCopyToFact: (
    supplierId: string,
    line: { raw_description: string; quantity: number; unit_price: number; material_id: string },
  ) => void;
}) {
  const materialById = new Map(materials.map((m) => [m.id, m]));
  const planItems = orders.flatMap((order) => order.items.map((item) => ({ order, item })));
  const hasNoOrder = orders.length === 0;

  return (
    <div className={styles.supplierCard}>
      <div className={styles.supplierHeader}>
        <span className={styles.supplierName}>{supplier?.name ?? supplierId}</span>
        {hasNoOrder && <span className={styles.supplierNoPlanBadge}>не планировался</span>}
        <span className={styles.supplierSpacer} />
        <span className={styles.supplierFigure}>
          Факт: {formatMoney(supplierTotal?.purchased_total ?? 0)}
        </span>
        {supplierTotal?.planned_total != null && (
          <span className={styles.supplierFigure}>План: {formatMoney(supplierTotal.planned_total)}</span>
        )}
        {supplierTotal?.delta != null && supplierTotal.delta_pct != null && (
          <span
            className={`${styles.supplierFigure} ${styles.supplierDelta} ${
              supplierTotal.delta > 0 ? styles.supplierDeltaOver : styles.supplierDeltaUnder
            }`}
          >
            {supplierTotal.delta >= 0 ? '+' : ''}
            {formatMoney(supplierTotal.delta)} ({supplierTotal.delta_pct >= 0 ? '+' : ''}
            {supplierTotal.delta_pct.toFixed(1)}%)
          </span>
        )}
      </div>

      <div className={styles.planFactGrid}>
        <div>
          <div className={styles.columnLabel}>План</div>
          {planItems.length === 0 ? (
            <div className={styles.emptyColumn}>
              Ордер для этого поставщика в проекте не создавался — не планировался.
            </div>
          ) : (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th className={styles.descColHeader}>Материал</th>
                  <th className={styles.numCell}>Кол-во</th>
                  <th className={styles.numCell}>Цена</th>
                  <th className={styles.copyColHeader}></th>
                </tr>
              </thead>
              <tbody>
                {planItems.map(({ order, item }) => {
                  const material = materialById.get(item.material_id);
                  return (
                    <tr key={`${order.id}-${item.id}`}>
                      <td className={styles.descColCell}>{material?.canonical_name ?? item.material_id}</td>
                      <td className={styles.numCell}>
                        {item.quantity} {material?.unit ?? ''}
                      </td>
                      <td className={styles.numCell}>{formatMoney(item.quoted_price)}</td>
                      <td className={styles.copyColCell}>
                        <button
                          type="button"
                          className={styles.copyToFactButton}
                          title="Скопировать в форму «Факт», если совпало"
                          onClick={() =>
                            onCopyToFact(supplierId, {
                              raw_description: material?.canonical_name ?? item.material_id,
                              quantity: item.quantity,
                              unit_price: item.quoted_price,
                              material_id: item.material_id,
                            })
                          }
                        >
                          →
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <div>
          <div className={styles.columnLabel}>Факт</div>
          {records.length === 0 ? (
            <div className={styles.emptyColumn}>Записей о фактической закупке ещё нет.</div>
          ) : (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th className={styles.descColHeader}>Название у поставщика</th>
                  <th className={styles.numCell}>Кол-во</th>
                  <th className={styles.numCell}>Цена</th>
                  <th className={styles.actionsColHeader}></th>
                </tr>
              </thead>
              <tbody>
                {records.map((record) => (
                  <PurchaseRecordRow
                    key={record.id}
                    record={record}
                    material={record.material_id ? materialById.get(record.material_id) : undefined}
                    materials={materials}
                    suppliers={allSuppliers}
                    onUpdate={(payload) => onUpdate(record, payload)}
                    onDelete={() => onDelete(record)}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

function PurchaseRecordRow({
  record,
  material,
  materials,
  suppliers,
  onUpdate,
  onDelete,
}: {
  record: PurchaseRecord;
  material: Material | undefined;
  materials: Material[];
  suppliers: Supplier[];
  onUpdate: (payload: Parameters<typeof purchaseRecordsApi.update>[2]) => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [description, setDescription] = useState(record.raw_description);
  const [quantity, setQuantity] = useState(String(record.quantity));
  const [unitPrice, setUnitPrice] = useState(String(record.unit_price));
  const [supplierId, setSupplierId] = useState(record.supplier_id);
  const [materialId, setMaterialId] = useState(record.material_id ?? '');
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  if (!editing) {
    return (
      <tr>
        <td className={styles.descColCell}>
          {record.raw_description}
          {material && <span className={styles.materialTag}>↳ {material.canonical_name}</span>}
        </td>
        <td className={styles.numCell}>{record.quantity}</td>
        <td className={styles.numCell}>{formatMoney(record.unit_price)}</td>
        <td className={styles.actionsColCell}>
          <div className={styles.actionsCell}>
            {!confirmingDelete && (
              <Button variant="ghost" onClick={() => setEditing(true)}>
                Изменить
              </Button>
            )}
            <ConfirmButton
              label="Удалить"
              confirmLabel="Удалить?"
              onConfirm={onDelete}
              onConfirmingChange={setConfirmingDelete}
            />
          </div>
        </td>
      </tr>
    );
  }

  function save() {
    const qty = Number(quantity);
    const price = Number(unitPrice);
    if (!description.trim() || !supplierId || !(qty > 0) || !(price >= 0)) return;
    onUpdate({
      supplier_id: supplierId,
      raw_description: description.trim(),
      quantity: qty,
      unit_price: price,
      material_id: materialId || null,
    });
    setEditing(false);
  }

  // Editing opens as a full-width row (same .addGrid layout as AddRecordCard),
  // not fields squeezed into the 4 display columns — 5 form fields (name,
  // qty, price, supplier, material) don't fit into 4 narrow table cells,
  // especially the number columns which also have to host a <select>.
  return (
    <tr className={styles.editRow}>
      <td colSpan={4}>
        <div className={styles.addGrid}>
          <div>
            <label className={styles.fieldLabel}>Название у поставщика</label>
            <input
              className={styles.editInput}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div>
            <label className={styles.fieldLabel}>Кол-во</label>
            <input
              className={styles.editInputNum}
              type="number"
              min="1"
              step="1"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </div>
          <div>
            <label className={styles.fieldLabel}>Цена за ед.</label>
            <input
              className={styles.editInputNum}
              type="number"
              min="0"
              step="0.01"
              value={unitPrice}
              onChange={(e) => setUnitPrice(e.target.value)}
            />
          </div>
          <div>
            <label className={styles.fieldLabel}>Поставщик</label>
            <select
              className={styles.editSelect}
              value={supplierId}
              onChange={(e) => setSupplierId(e.target.value)}
            >
              {suppliers.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={styles.fieldLabel}>
              Материал <span className={styles.optionalHint}>(необязательно)</span>
            </label>
            <select
              className={styles.editSelect}
              value={materialId}
              onChange={(e) => setMaterialId(e.target.value)}
            >
              <option value="">— не связано с материалом —</option>
              {materials.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.canonical_name}
                </option>
              ))}
            </select>
          </div>
          <div className={styles.actionsCell}>
            <Button variant="primary" onClick={save}>
              Сохранить
            </Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>
              Отмена
            </Button>
          </div>
        </div>
      </td>
    </tr>
  );
}

const AddRecordCard = forwardRef<
  HTMLDivElement,
  {
    suppliers: Supplier[];
    materials: Material[];
    draft: DraftRecord;
    onDraftChange: (draft: DraftRecord) => void;
    onCreate: (payload: Parameters<typeof purchaseRecordsApi.create>[1]) => Promise<void>;
  }
>(function AddRecordCard({ suppliers, materials, draft, onDraftChange, onCreate }, ref) {
  const [saving, setSaving] = useState(false);

  const qty = Number(draft.quantity);
  const price = Number(draft.unit_price);
  const canSubmit = draft.raw_description.trim() !== '' && draft.supplier_id !== '' && qty > 0 && price >= 0;

  function updateField(patch: Partial<DraftRecord>) {
    onDraftChange({ ...draft, ...patch });
  }

  async function handleAdd() {
    if (!canSubmit) return;
    setSaving(true);
    try {
      await onCreate({
        supplier_id: draft.supplier_id,
        raw_description: draft.raw_description.trim(),
        quantity: qty,
        unit_price: price,
        material_id: draft.material_id || null,
      });
      // onCreate resets the draft to EMPTY_DRAFT on success — see
      // PurchaseRecordsPage.handleCreate. Supplier is intentionally not
      // preserved across a reset: unlike the old "keep typing invoice lines
      // for the same supplier" flow, a copied-from-plan draft (п. "→ в
      // факт") should not leave a stale supplier selected for the next,
      // unrelated manual entry.
    } catch {
      // error is surfaced via the page-level ErrorBanner
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={styles.supplierCard} ref={ref}>
      <div className={styles.columnLabel}>Добавить запись о фактической закупке</div>
      <div className={styles.addSection}>
        <div className={styles.addGrid}>
          <div>
            <label className={styles.fieldLabel}>Название у поставщика</label>
            <input
              className={styles.editInput}
              placeholder='84" PREMIER SCREEN 18/14"'
              value={draft.raw_description}
              onChange={(e) => updateField({ raw_description: e.target.value })}
            />
          </div>
          <div>
            <label className={styles.fieldLabel}>Кол-во</label>
            <input
              className={styles.editInputNum}
              type="number"
              min="1"
              step="1"
              placeholder="0"
              value={draft.quantity}
              onChange={(e) => updateField({ quantity: e.target.value })}
            />
          </div>
          <div>
            <label className={styles.fieldLabel}>Цена за ед.</label>
            <input
              className={styles.editInputNum}
              type="number"
              min="0"
              step="0.01"
              placeholder="0.00"
              value={draft.unit_price}
              onChange={(e) => updateField({ unit_price: e.target.value })}
            />
          </div>
          <div>
            <label className={styles.fieldLabel}>Поставщик</label>
            <select
              className={styles.editSelect}
              value={draft.supplier_id}
              onChange={(e) => updateField({ supplier_id: e.target.value })}
            >
              <option value="">— выберите —</option>
              {suppliers.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={styles.fieldLabel}>
              Материал <span className={styles.optionalHint}>(необязательно)</span>
            </label>
            <select
              className={styles.editSelect}
              value={draft.material_id}
              onChange={(e) => updateField({ material_id: e.target.value })}
            >
              <option value="">— если хотите связать с материалом в базе —</option>
              {materials.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.canonical_name}
                </option>
              ))}
            </select>
          </div>
          <Button variant="secondary" disabled={!canSubmit || saving} onClick={() => void handleAdd()}>
            + Добавить
          </Button>
        </div>
      </div>
    </div>
  );
});

function formatMoney(value: number): string {
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
