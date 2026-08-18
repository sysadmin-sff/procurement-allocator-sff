import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { allocationApi } from '../api/allocation';
import { materialsApi } from '../api/materials';
import { ordersApi } from '../api/orders';
import { pricesApi } from '../api/prices';
import { projectsApi } from '../api/projects';
import { suppliersApi } from '../api/suppliers';
import type { AllocationLine, AllocationRun, Material, Price, ProjectWithItems, Supplier } from '../api/types';
import { Button } from '../components/Button';
import { ErrorBanner } from '../components/ErrorBanner';
import styles from './allocation-result/AllocationResult.module.css';

interface LoadedData {
  run: AllocationRun;
  project: ProjectWithItems;
  suppliers: Supplier[];
  materials: Material[];
  prices: Price[];
}

export function AllocationResultPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<LoadedData | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;

    setLoading(true);
    setError(null);
    Promise.all([
      allocationApi.run(projectId),
      projectsApi.get(projectId),
      suppliersApi.list(),
      materialsApi.list(),
      pricesApi.list(),
    ])
      .then(([run, project, suppliers, materials, prices]) => {
        if (cancelled) return;
        setData({ run, project, suppliers, materials, prices });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (!projectId) {
    return <ErrorBanner error="Не указан проект." />;
  }

  if (loading) {
    return <div className={styles.centerWrap}>Считаем распределение…</div>;
  }

  if (error) {
    return (
      <div className={styles.centerWrap}>
        <div>
          <ErrorBanner error={error} />
          <Button variant="secondary" onClick={() => navigate(`/projects/${projectId}`)}>
            « Назад к проекту
          </Button>
        </div>
      </div>
    );
  }

  if (!data) {
    return null;
  }

  const { run } = data;

  if (run.status === 'infeasible') {
    return (
      <div className={styles.centerWrap}>
        <div className={styles.infeasibleCard}>
          <div className={styles.infeasibleTitle}>Расчёт невыполним</div>
          <p className={styles.infeasibleText}>
            Не удалось построить план закупки — часть условий поставщиков делает расчёт
            невыполнимым (например, минимальная сумма заказа). Проверьте цены и условия
            поставщиков.
          </p>
          <Button variant="secondary" onClick={() => navigate(`/projects/${projectId}`)}>
            « Назад к проекту
          </Button>
        </div>
      </div>
    );
  }

  return (
    <AllocationResultOk
      data={data}
      onBack={() => navigate(`/projects/${projectId}`)}
      onRunChange={(run) => setData((prev) => (prev ? { ...prev, run } : prev))}
      onOrdersCreated={() => navigate(`/projects/${projectId}`)}
    />
  );
}

function AllocationResultOk({
  data,
  onBack,
  onRunChange,
  onOrdersCreated,
}: {
  data: LoadedData;
  onBack: () => void;
  onRunChange: (run: AllocationRun) => void;
  onOrdersCreated: () => void;
}) {
  const { run, project, suppliers, materials, prices } = data;

  const supplierById = new Map(suppliers.map((s) => [s.id, s]));
  const materialById = new Map(materials.map((m) => [m.id, m]));

  const grandTotal = run.supplier_summaries.reduce(
    (sum, s) => sum + s.goods_total + s.delivery_fee,
    0,
  );

  const cheapestByMaterial = buildCheapestPriceIndex(prices);
  const pricesByMaterial = buildPricesByMaterialIndex(prices);

  const [overrideError, setOverrideError] = useState<unknown>(null);
  const [savingLineId, setSavingLineId] = useState<string | null>(null);
  const [creatingOrders, setCreatingOrders] = useState(false);
  const [createOrdersError, setCreateOrdersError] = useState<unknown>(null);

  async function handleOverride(lineId: string, supplierId: string) {
    setOverrideError(null);
    setSavingLineId(lineId);
    try {
      await allocationApi.overrideLine(project.id, run.id, lineId, supplierId);
      const refreshed = await allocationApi.get(project.id, run.id);
      onRunChange(refreshed);
    } catch (err) {
      setOverrideError(err);
    } finally {
      setSavingLineId(null);
    }
  }

  async function handleCreateOrders() {
    setCreateOrdersError(null);
    setCreatingOrders(true);
    try {
      await ordersApi.createForRun(project.id, run.id);
      onOrdersCreated();
    } catch (err) {
      setCreateOrdersError(err);
    } finally {
      setCreatingOrders(false);
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <button type="button" className={styles.backLink} onClick={onBack}>
          « Назад к проекту
        </button>

        <div className={styles.header}>
          <h1 className={styles.title}>{project.title}</h1>
          <div className={styles.headerMeta}>
            <span className={styles.headerTotal}>{formatMoney(grandTotal)}</span>
            <span>
              {run.supplier_summaries.length}{' '}
              {pluralizeSuppliers(run.supplier_summaries.length)}
            </span>
          </div>
        </div>

        {overrideError != null && <ErrorBanner error={overrideError} />}

        {run.orphaned_materials.length > 0 && (
          <div className={styles.warningBlock} role="alert">
            <div className={styles.warningTitle}>
              Не удалось разместить часть материалов
            </div>
            <div className={styles.warningList}>
              {run.orphaned_materials.map((o) => {
                const material = materialById.get(o.material_id);
                return (
                  <div key={o.material_id} className={styles.warningRow}>
                    <span className={styles.warningMaterial}>
                      {material?.canonical_name ?? o.material_id}
                    </span>
                    <span className={styles.warningQty}>
                      требуется {o.required_quantity} {material?.unit ?? ''}
                      {o.best_partial_supplier_id && o.best_partial_available != null && (
                        <>
                          {' '}
                          — частично доступно {o.best_partial_available} у{' '}
                          {supplierById.get(o.best_partial_supplier_id)?.name ??
                            o.best_partial_supplier_id}
                        </>
                      )}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {run.supplier_summaries.map((summary) => {
          const supplier = supplierById.get(summary.supplier_id);
          const lines = run.lines.filter((l) => l.supplier_id === summary.supplier_id);
          const cardTotal = summary.goods_total + summary.delivery_fee;

          return (
            <div key={summary.supplier_id} className={styles.supplierCard}>
              <div className={styles.supplierHeader}>
                <span className={styles.supplierName}>
                  {supplier?.name ?? summary.supplier_id}
                </span>
                <span className={styles.supplierSpacer} />
                <span
                  className={
                    summary.free_shipping_achieved
                      ? `${styles.supplierDelivery} ${styles.supplierDeliveryFree}`
                      : styles.supplierDelivery
                  }
                >
                  Доставка:{' '}
                  {summary.free_shipping_achieved ? 'бесплатно' : formatMoney(summary.delivery_fee)}
                </span>
                <span className={styles.supplierTotal}>{formatMoney(cardTotal)}</span>
              </div>

              {summary.below_min_order && (
                <div className={styles.belowMinOrderNotice} role="alert">
                  ⚠ Сумма заказа {formatMoney(summary.goods_total)} меньше минимальной{' '}
                  {formatMoney(supplier?.delivery_policy.per_order_min_amount ?? 0)} — поставщик
                  может отклонить заказ.
                </div>
              )}

              <table className={styles.table}>
                <thead>
                  <tr>
                    <th className={styles.materialColHeader}>Материал</th>
                    <th className={styles.numCell}>Кол-во</th>
                    <th className={styles.numCell}>Цена за ед.</th>
                    <th className={styles.numCell}>Поставщик</th>
                    <th className={styles.numCell}>Сумма</th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((line) => (
                    <LineRow
                      key={line.id}
                      line={line}
                      material={materialById.get(line.material_id)}
                      cheapest={cheapestByMaterial.get(line.material_id)}
                      supplierOptions={pricesByMaterial.get(line.material_id) ?? []}
                      supplierById={supplierById}
                      saving={savingLineId === line.id}
                      onOverride={(supplierId) => handleOverride(line.id, supplierId)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          );
        })}

        {createOrdersError != null && <ErrorBanner error={createOrdersError} />}

        <div className={styles.footer}>
          <Button variant="primary" disabled={creatingOrders} onClick={() => void handleCreateOrders()}>
            {creatingOrders ? 'Создаём ордера…' : 'Подтвердить и создать ордера'}
          </Button>
          <span className={styles.footerHint}>
            Создаст по одному ордеру на каждого поставщика — необратимо.
          </span>
        </div>
      </div>
    </div>
  );
}

function LineRow({
  line,
  material,
  cheapest,
  supplierOptions,
  supplierById,
  saving,
  onOverride,
}: {
  line: AllocationLine;
  material: Material | undefined;
  cheapest: { price: number; supplierIds: string[] } | undefined;
  supplierOptions: Price[];
  supplierById: Map<string, Supplier>;
  saving: boolean;
  onOverride: (supplierId: string) => void;
}) {
  const isCheapest = !cheapest || line.unit_price <= cheapest.price;
  const delta = cheapest ? line.unit_price - cheapest.price : null;
  const cheapestSupplierName =
    cheapest && cheapest.supplierIds.length > 0
      ? (supplierById.get(cheapest.supplierIds[0])?.name ?? cheapest.supplierIds[0])
      : null;

  const isOverridden = line.overridden_at != null;
  const originalSupplierName =
    line.original_supplier_id != null
      ? (supplierById.get(line.original_supplier_id)?.name ?? line.original_supplier_id)
      : null;

  // ADR-0007 п.2: comparing two backend-supplied timestamps as-is is not
  // money arithmetic, so this stays a client-side check (CLAUDE.md принцип 4
  // restricts money math, not date ordering).
  const changedAfterOrder =
    line.ordered_at != null &&
    line.overridden_at != null &&
    new Date(line.overridden_at).getTime() > new Date(line.ordered_at).getTime();

  const currentPrice = supplierOptions.find((p) => p.supplier_id === line.supplier_id);
  const availabilityShort =
    currentPrice?.availability != null && currentPrice.availability < line.quantity;

  return (
    <tr>
      <td className={styles.materialColCell}>
        <span className={styles.materialCell}>
          {material?.canonical_name ?? line.material_id}
          {!isCheapest && (
            <span className={styles.badge}>
              не самая дешёвая цена
              {delta != null && delta > 0 && cheapestSupplierName && (
                <span className={styles.badgeText}>
                  {' '}
                  — дороже на {formatMoney(delta)} за единицу, чем у {cheapestSupplierName}
                </span>
              )}
            </span>
          )}
          {isOverridden && (
            <span className={styles.overrideBadge}>
              изменено вручную
              {originalSupplierName && line.original_unit_price != null && (
                <span className={styles.overrideNote}>
                  {' '}
                  было: {originalSupplierName}, {formatMoney(line.original_unit_price)}/ед.
                </span>
              )}
            </span>
          )}
        </span>
        {availabilityShort && currentPrice && (
          <span className={styles.availabilityRisk}>
            ⚠ у поставщика доступно {currentPrice.availability} {material?.unit ?? ''}, требуется{' '}
            {line.quantity}
          </span>
        )}
        {changedAfterOrder && (
          <span className={styles.orderStaleWarning}>
            ⚠ изменено после отправки ордера — это изменение не попало в уже созданный ордер
          </span>
        )}
      </td>
      <td className={styles.numCell}>
        {line.quantity} {material?.unit ?? ''}
      </td>
      <td className={styles.numCell}>{formatMoney(line.unit_price)}</td>
      <td className={styles.numCell}>
        <select
          className={styles.supplierSelect}
          value={line.supplier_id}
          disabled={saving}
          onChange={(e) => onOverride(e.target.value)}
        >
          {supplierOptions.map((price) => (
            <option key={price.supplier_id} value={price.supplier_id}>
              {supplierById.get(price.supplier_id)?.name ?? price.supplier_id} —{' '}
              {formatMoney(price.price)}
            </option>
          ))}
        </select>
      </td>
      <td className={styles.numCell}>{formatMoney(line.line_total)}</td>
    </tr>
  );
}

function buildCheapestPriceIndex(
  prices: Price[],
): Map<string, { price: number; supplierIds: string[] }> {
  const index = new Map<string, { price: number; supplierIds: string[] }>();
  for (const price of prices) {
    if (price.valid_to != null) continue;
    const existing = index.get(price.material_id);
    if (!existing || price.price < existing.price) {
      index.set(price.material_id, { price: price.price, supplierIds: [price.supplier_id] });
    } else if (price.price === existing.price) {
      existing.supplierIds.push(price.supplier_id);
    }
  }
  return index;
}

/** Active prices grouped by material_id — the option set for the per-line supplier override select. */
function buildPricesByMaterialIndex(prices: Price[]): Map<string, Price[]> {
  const index = new Map<string, Price[]>();
  for (const price of prices) {
    if (price.valid_to != null) continue;
    const list = index.get(price.material_id);
    if (list) {
      list.push(price);
    } else {
      index.set(price.material_id, [price]);
    }
  }
  return index;
}

function formatMoney(value: number): string {
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pluralizeSuppliers(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return 'поставщик';
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'поставщика';
  return 'поставщиков';
}
