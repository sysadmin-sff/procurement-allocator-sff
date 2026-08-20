import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApiError } from '../api/client';
import { materialsApi } from '../api/materials';
import { ordersApi } from '../api/orders';
import type { OrderItemPatch } from '../api/orders';
import { suppliersApi } from '../api/suppliers';
import type { FindReplacementResult, Material, Order, OrderItem, Supplier } from '../api/types';
import { ErrorBanner } from '../components/ErrorBanner';
import styles from './order-detail/OrderDetail.module.css';

const SIGNIFICANT_PRICE_DELTA_PCT = 10;
/** Mirrors app/allocation/order_service.py SIGNIFICANT_PRICE_DELTA_PCT — the
 * server computes price_delta_pct, this only decides the highlight threshold
 * for display. See ADR-0007 п.4. */

interface LoadedData {
  order: Order;
  materials: Material[];
  suppliers: Supplier[];
}

export function OrderDetailPage() {
  const { orderId } = useParams<{ orderId: string }>();
  const [data, setData] = useState<LoadedData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [savingItemId, setSavingItemId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<unknown>(null);

  useEffect(() => {
    if (!orderId) return;
    let cancelled = false;

    setLoading(true);
    setLoadError(null);
    Promise.all([ordersApi.get(orderId), materialsApi.list(), suppliersApi.list()])
      .then(([order, materials, suppliers]) => {
        if (cancelled) return;
        setData({ order, materials, suppliers });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoadError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [orderId]);

  async function handleItemPatch(item: OrderItem, patch: OrderItemPatch) {
    if (!data) return;
    setSaveError(null);
    setSavingItemId(item.id);
    try {
      const updated = await ordersApi.patchItem(data.order.id, item.id, patch);
      setData((prev) =>
        prev
          ? {
              ...prev,
              order: {
                ...prev.order,
                items: prev.order.items.map((i) => (i.id === item.id ? updated : i)),
              },
            }
          : prev,
      );
    } catch (err) {
      setSaveError(err);
    } finally {
      setSavingItemId(null);
    }
  }

  // After a successful replacement override, re-fetch the whole Order
  // rather than trust the PATCH's own response — the PATCH only returns the
  // AllocationLine, not the updated OrderItemOut.replaced_by_* fields for
  // this (or any other) declined row. See ADR-0014 п.6.
  async function handleReplacementApplied() {
    if (!data) return;
    setSaveError(null);
    try {
      const refreshed = await ordersApi.get(data.order.id);
      setData((prev) => (prev ? { ...prev, order: refreshed } : prev));
    } catch (err) {
      setSaveError(err);
    }
  }

  if (!orderId) {
    return <ErrorBanner error="Не указан ордер." />;
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

  const { order, materials, suppliers } = data;
  const materialById = new Map(materials.map((m) => [m.id, m]));
  const supplier = suppliers.find((s) => s.id === order.supplier_id);

  const discrepantCount = order.items.filter(
    (item) => item.price_delta_pct != null && Math.abs(item.price_delta_pct) > SIGNIFICANT_PRICE_DELTA_PCT,
  ).length;
  const declinedCount = order.items.filter((item) => item.declined_at != null).length;
  // Declined items sort to the bottom, keeping their relative order (and the
  // relative order of everything else) intact — Array.prototype.sort is a
  // stable sort per spec, so a single boolean comparator is enough. Purely a
  // display concern: order.items itself is untouched.
  const sortedItems = order.items
    .slice()
    .sort((a, b) => Number(a.declined_at != null) - Number(b.declined_at != null));

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <Link to={`/projects/${order.project_id}`} className={styles.backLink}>
          « Назад к проекту
        </Link>

        <div className={styles.header}>
          <h1 className={styles.title}>{supplier?.name ?? order.supplier_id}</h1>
        </div>

        {saveError != null && <ErrorBanner error={saveError} />}

        {(discrepantCount > 0 || declinedCount > 0) && (
          <div className={styles.discrepancyBanner} role="alert">
            {discrepantCount > 0 && (
              <span>
                ⚠ {discrepantCount} {pluralizePositions(discrepantCount)} с расхождением цены больше{' '}
                {SIGNIFICANT_PRICE_DELTA_PCT}%
              </span>
            )}
            {discrepantCount > 0 && declinedCount > 0 && <span> · </span>}
            {declinedCount > 0 && (
              <span>
                ⚠ {declinedCount} {pluralizePositions(declinedCount)} отклонено поставщиком
              </span>
            )}
          </div>
        )}

        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.materialColHeader}>Материал</th>
              <th className={styles.numCell}>Кол-во</th>
              <th className={styles.numCell}>Отправленная цена</th>
              <th className={styles.numCell}>Полученная цена</th>
              <th className={styles.numCell}>Подтверждённая цена</th>
              <th className={styles.numCell}>Расхождение</th>
              <th className={styles.statusColHeader}>Статус</th>
            </tr>
          </thead>
          <tbody>
            {sortedItems.map((item) => (
              <OrderItemRow
                key={item.id}
                item={item}
                order={order}
                material={materialById.get(item.material_id)}
                saving={savingItemId === item.id}
                onPatch={(patch) => void handleItemPatch(item, patch)}
                onReplacementApplied={handleReplacementApplied}
              />
            ))}
          </tbody>
        </table>

        <div className={styles.footer}>
          <span className={styles.footerTotal}>
            Товары: {formatMoney(order.total_amount)} + доставка {formatMoney(order.delivery_fee)}
          </span>
        </div>

        <div className={styles.copySection}>
          <CopyBlock
            title="Список материалов (с ценами)"
            text={buildOrderText({ supplierName: supplier?.name ?? order.supplier_id, order, materialById, includePrices: true })}
          />
          <CopyBlock
            title="Список материалов (без цен)"
            text={buildOrderText({ supplierName: supplier?.name ?? order.supplier_id, order, materialById, includePrices: false })}
          />
        </div>
      </div>
    </div>
  );
}

function CopyBlock({ title, text }: { title: string; text: string }) {
  const [copied, setCopied] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  async function handleCopy() {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        throw new Error('Clipboard API unavailable');
      }
    } catch {
      const textarea = textareaRef.current;
      if (textarea) {
        textarea.focus();
        textarea.select();
        document.execCommand('copy');
      }
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className={styles.copyBlock}>
      <div className={styles.copyBlockHeader}>
        <div className={styles.copyBlockTitle}>{title}</div>
        <button type="button" className={styles.copyButton} onClick={() => void handleCopy()}>
          {copied ? 'Скопировано ✓' : 'Скопировать'}
        </button>
      </div>
      <textarea
        ref={textareaRef}
        className={styles.copyTextarea}
        readOnly
        value={text}
        onFocus={(e) => e.currentTarget.select()}
      />
    </div>
  );
}

function buildOrderText({
  supplierName,
  order,
  materialById,
  includePrices,
}: {
  supplierName: string;
  order: Order;
  materialById: Map<string, Material>;
  includePrices: boolean;
}): string {
  const lines: string[] = [`Order for ${supplierName}`, ''];

  order.items.forEach((item, index) => {
    const material = materialById.get(item.material_id);
    const name = material?.canonical_name ?? item.material_id;
    const unit = material?.unit ?? '';
    lines.push(`${index + 1}. ${name}`);
    lines.push(`   Qty: ${item.quantity} ${unit}`.trimEnd());
    if (includePrices) {
      lines.push(`   Price: ${formatMoney(item.quoted_price)}/unit`);
      lines.push(`   Total: ${formatMoney(item.quoted_price * item.quantity)}`);
    }
    lines.push('');
  });

  if (includePrices) {
    const goodsTotal = order.total_amount;
    const grandTotal = goodsTotal + order.delivery_fee;
    lines.push(`Goods total: ${formatMoney(goodsTotal)}`);
    lines.push(`Delivery: ${formatMoney(order.delivery_fee)}`);
    lines.push(`Grand total: ${formatMoney(grandTotal)}`);
  } else {
    lines.pop();
  }

  return lines.join('\n');
}

function OrderItemRow({
  item,
  order,
  material,
  saving,
  onPatch,
  onReplacementApplied,
}: {
  item: OrderItem;
  order: Order;
  material: Material | undefined;
  saving: boolean;
  onPatch: (patch: OrderItemPatch) => void;
  onReplacementApplied: () => void;
}) {
  const isDiscrepant =
    item.price_delta_pct != null && Math.abs(item.price_delta_pct) > SIGNIFICANT_PRICE_DELTA_PCT;
  const isDeclined = item.declined_at != null;
  const rowClassName =
    [isDiscrepant ? styles.discrepantRow : '', isDeclined ? styles.declinedRow : '']
      .filter(Boolean)
      .join(' ') || undefined;

  return (
    <tr className={rowClassName}>
      <td className={styles.materialColCell}>{material?.canonical_name ?? item.material_id}</td>
      <td className={styles.numCell}>
        {item.quantity} {material?.unit ?? ''}
      </td>
      <td className={styles.numCell}>{formatMoney(item.quoted_price)}</td>
      <td className={styles.numCell}>
        <input
          key={item.received_price ?? 'empty'}
          className={styles.priceInput}
          type="number"
          min="0"
          step="0.01"
          placeholder="—"
          defaultValue={item.received_price ?? ''}
          disabled={saving}
          onBlur={(e) => {
            const raw = e.target.value.trim();
            const value = raw === '' ? null : Number(raw);
            if (value !== item.received_price) onPatch({ received_price: value });
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') e.currentTarget.blur();
          }}
        />
      </td>
      <td className={styles.numCell}>
        <input
          key={item.confirmed_price ?? 'empty'}
          className={styles.priceInput}
          type="number"
          min="0"
          step="0.01"
          placeholder="—"
          defaultValue={item.confirmed_price ?? ''}
          disabled={saving}
          onBlur={(e) => {
            const raw = e.target.value.trim();
            const value = raw === '' ? null : Number(raw);
            if (value !== item.confirmed_price) onPatch({ confirmed_price: value });
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') e.currentTarget.blur();
          }}
        />
      </td>
      <td className={styles.numCell}>
        {item.price_delta != null && item.price_delta_pct != null ? (
          <span className={isDiscrepant ? styles.deltaDiscrepant : styles.delta}>
            {item.price_delta >= 0 ? '+' : ''}
            {formatMoney(item.price_delta)} ({item.price_delta_pct >= 0 ? '+' : ''}
            {item.price_delta_pct.toFixed(1)}%)
          </span>
        ) : (
          <span className={styles.deltaEmpty}>—</span>
        )}
      </td>
      <td className={styles.statusColCell}>
        <button
          type="button"
          className={isDeclined ? styles.declineButtonActive : styles.declineButton}
          disabled={saving}
          onClick={() => onPatch({ declined: !isDeclined })}
        >
          {isDeclined ? 'Отклонено' : 'Отметить как недоступно'}
        </button>
        {isDeclined && (
          <input
            key={item.decline_reason ?? 'empty'}
            className={styles.declineReasonInput}
            type="text"
            placeholder="Причина (необязательно)"
            defaultValue={item.decline_reason ?? ''}
            disabled={saving}
            onBlur={(e) => {
              const raw = e.target.value.trim();
              const value = raw === '' ? null : raw;
              if (value !== item.decline_reason) onPatch({ decline_reason: value });
            }}
          />
        )}
        {isDeclined && (
          <ReplacementTrigger
            item={item}
            order={order}
            material={material}
            onReplacementApplied={onReplacementApplied}
          />
        )}
      </td>
    </tr>
  );
}

function ReplacementTrigger({
  item,
  order,
  material,
  onReplacementApplied,
}: {
  item: OrderItem;
  order: Order;
  material: Material | undefined;
  onReplacementApplied: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [notFound, setNotFound] = useState<string | null>(null);
  const [result, setResult] = useState<FindReplacementResult | null>(null);
  const [applyingSupplierId, setApplyingSupplierId] = useState<string | null>(null);
  const [applyError, setApplyError] = useState<unknown>(null);

  async function handleFindReplacement() {
    setOpen(true);
    setLoading(true);
    setNotFound(null);
    setApplyError(null);
    try {
      const found = await ordersApi.findReplacement(order.id, item.id);
      setResult(found);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setNotFound(
          typeof err.detail === 'string'
            ? err.detail
            : `Материал ${material?.canonical_name ?? item.material_id} отсутствует в текущем плане проекта.`,
        );
        setResult(null);
      } else {
        setApplyError(err);
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleSelectCandidate(supplierId: string) {
    setApplyError(null);
    setApplyingSupplierId(supplierId);
    try {
      // Single call: overrides the AllocationLine and syncs the target
      // draft Order (creates it or adds an OrderItem to the existing one)
      // in one backend transaction — see ADR-0015. Replaces the old
      // allocationApi.overrideLine + projectsApi.get(run_id) combo.
      await ordersApi.replaceAndOrder(order.id, item.id, supplierId);
      onReplacementApplied();
      setOpen(false);
      setResult(null);
    } catch (err) {
      setApplyError(err);
    } finally {
      setApplyingSupplierId(null);
    }
  }

  const replaced = item.replaced_by_supplier_id != null;

  return (
    <div className={styles.replacementSection}>
      <button
        type="button"
        className={styles.findReplacementButton}
        onClick={() => (open ? setOpen(false) : void handleFindReplacement())}
      >
        {open ? 'Скрыть кандидатов' : 'Найти замену'}
      </button>

      {replaced && (
        <div className={styles.replacedNotice}>
          → Перенесено на {item.replaced_by_supplier_name ?? item.replaced_by_supplier_id}
          {item.replacement_draft_order_id != null ? (
            <>
              {' '}
              —{' '}
              <Link to={`/orders/${item.replacement_draft_order_id}`} className={styles.replacedLink}>
                черновик уже создан »
              </Link>
            </>
          ) : (
            <span className={styles.replacedMuted}> — ордер ещё не создан</span>
          )}
        </div>
      )}

      {open && (
        <div className={styles.replacementPanel}>
          {loading && <div className={styles.replacementLoading}>Ищем кандидатов…</div>}

          {notFound != null && <div className={styles.replacementNotFound}>⚠ {notFound}</div>}

          {applyError != null && (
            <div className={styles.replacementNotFound}>
              {applyError instanceof ApiError ? applyError.message : 'Не удалось применить замену.'}
            </div>
          )}

          {result != null && result.candidates.length === 0 && (
            <div className={styles.replacementLoading}>Нет активных цен на этот материал у других поставщиков.</div>
          )}

          {result != null && result.candidates.length > 0 && (
            <ul className={styles.candidateList}>
              {result.candidates.map((candidate) => (
                <li key={candidate.supplier_id} className={styles.candidateRow}>
                  <button
                    type="button"
                    className={styles.candidateButton}
                    disabled={applyingSupplierId != null}
                    onClick={() => void handleSelectCandidate(candidate.supplier_id)}
                  >
                    <span className={styles.candidateSupplier}>
                      {candidate.supplier_name}
                      {applyingSupplierId === candidate.supplier_id && '…'}
                    </span>
                    <span className={styles.candidatePrice}>{formatMoney(candidate.price)}</span>
                  </button>
                  {candidate.availability_risk && (
                    <span className={styles.availabilityRisk}>
                      ⚠ у поставщика доступно {candidate.availability} {material?.unit ?? ''}, требуется{' '}
                      {item.quantity}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function formatMoney(value: number): string {
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pluralizePositions(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return 'позиция';
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'позиции';
  return 'позиций';
}
