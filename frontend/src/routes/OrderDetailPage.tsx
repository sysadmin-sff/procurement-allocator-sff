import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApiError } from '../api/client';
import { materialsApi } from '../api/materials';
import { ordersApi } from '../api/orders';
import type { OrderItemPatch } from '../api/orders';
import { purchaseRecordsApi } from '../api/purchaseRecords';
import { suppliersApi } from '../api/suppliers';
import type {
  FindReplacementResult,
  Material,
  Order,
  OrderItem,
  ParsedExtraLine,
  ParsedMatchedLine,
  ParseOrderResponseResult,
  Supplier,
} from '../api/types';
import { ErrorBanner } from '../components/ErrorBanner';
import { FileInput } from '../components/FileInput';
import styles from './order-detail/OrderDetail.module.css';

const LOW_CONFIDENCE_LEVELS = new Set(['low', 'medium']);
/** Both "low" and "medium" get the same ⚠ treatment in MVP — see ADR-0018 §6:
 * "confidence как таковой доступен в ответе endpoint'а на случай будущей
 * дифференциации, но экран не обязан различать "low" и "medium" визуально". */

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

  // Same full-refresh pattern as handleReplacementApplied — after bulk
  // "Применить все совпадения" the individual PATCH responses were already
  // applied to state per-row, but a full GET keeps this consistent with the
  // rest of the page rather than trusting the accumulated PATCH responses.
  async function handleParseApplied() {
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

  // "Ожидается" footer line: goods total by confirmed_price where set,
  // falling back to quoted_price where a position hasn't been confirmed
  // yet — declined items are excluded outright, same as expected_goods_total
  // (ADR-0026) excludes them. No server-computed field exists for a
  // confirmed_price-based total (expected_goods_total is quoted_price-based),
  // so this is a local sum for this one footer line — same reasoning as the
  // target-price copy block (ADR-0027), not a recomputation of the Order's
  // own money fields. Delivery reuses expected_delivery_fee unchanged — it
  // doesn't depend on which price axis the goods total is read from.
  const expectedGoodsTotalByConfirmed = order.items
    .filter((item) => item.declined_at == null)
    .reduce((sum, item) => sum + (item.confirmed_price ?? item.quoted_price) * item.quantity, 0);
  const expectedTotalByConfirmed = expectedGoodsTotalByConfirmed + order.expected_delivery_fee;
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

        <ParseResponseSection
          order={order}
          materialById={materialById}
          onApplied={handleParseApplied}
          targetField="received_price"
          title="Распознавание ответа поставщика"
        />
        <ParseResponseSection
          order={order}
          materialById={materialById}
          onApplied={handleParseApplied}
          targetField="confirmed_price"
          title="Распознавание финального ответа (после торга)"
        />

        <div className={styles.tableScroll}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.materialColHeader}>Материал</th>
                <th className={styles.numCell}>Кол-во</th>
                <th className={styles.numCell}>
                  Отправленная
                  <br />
                  цена
                </th>
                <th className={styles.numCell}>
                  Полученная
                  <br />
                  цена
                </th>
                <th className={styles.numCell}>
                  Целевая
                  <br />
                  цена
                </th>
                <th className={styles.numCell}>
                  Подтверждённая
                  <br />
                  цена
                </th>
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
        </div>

        <div className={styles.footer}>
          <div className={styles.footerTotals}>
            <div className={styles.footerLine}>
              <span className={styles.footerLabel}>Отправлено:</span>{' '}
              <span className={styles.footerTotal}>
                Товары {formatMoney(order.total_amount)} + доставка {formatMoney(order.delivery_fee)} ={' '}
                {formatMoney(order.total_amount + order.delivery_fee)}
              </span>
            </div>
            <div className={styles.footerLine}>
              <span className={styles.footerLabel}>Ожидается:</span>{' '}
              <span className={styles.footerTotal}>
                Товары {formatMoney(expectedGoodsTotalByConfirmed)} + доставка{' '}
                {formatMoney(order.expected_delivery_fee)} = {formatMoney(expectedTotalByConfirmed)}
              </span>
            </div>
          </div>
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
          <CopyBlock
            title="Список материалов (с целевыми ценами)"
            text={buildTargetPriceOrderText({ supplierName: supplier?.name ?? order.supplier_id, order, materialById })}
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

  // Declined items are the supplier's own answer — repeating "declined" back
  // to them in their own outgoing order text is redundant, so they are left
  // out entirely rather than marked. See ADR-0027 §5.
  const includedItems = order.items.filter((item) => item.declined_at == null);

  includedItems.forEach((item, index) => {
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
    // expected_goods_total/expected_delivery_fee already exclude declined
    // items (ADR-0026, computed server-side) — not order.total_amount/
    // delivery_fee (the as-sent snapshot) and not a client-side recompute
    // from includedItems. See ADR-0027 §5.
    lines.push(`Goods total: ${formatMoney(order.expected_goods_total)}`);
    lines.push(`Delivery: ${formatMoney(order.expected_delivery_fee)}`);
    lines.push(`Grand total: ${formatMoney(order.expected_total)}`);
  } else {
    lines.pop();
  }

  return lines.join('\n');
}

/** Third copy block — the second negotiation round (ADR-0027): after seeing
 * received_price, the employee decided what to counter-offer and wants a
 * message to send back with those numbers. Only items with target_price set
 * are relevant here — a row with no counter-offer isn't part of this
 * message. Declined items are still excluded (same reasoning as
 * buildOrderText, ADR-0027 §5).
 *
 * The per-line/total figures here use target_price, which has no
 * server-computed total to read (unlike expected_goods_total, which is
 * quoted_price-based, ADR-0026) — this is a local sum for one outgoing
 * message's line items, not a recomputation of the Order's own money
 * fields (total_amount/expected_*), so it doesn't conflict with CLAUDE.md
 * principle 4. Delivery still comes from expected_delivery_fee — the
 * delivery fee doesn't depend on which price axis (quoted vs target) the
 * goods total is read from. */
function buildTargetPriceOrderText({
  supplierName,
  order,
  materialById,
}: {
  supplierName: string;
  order: Order;
  materialById: Map<string, Material>;
}): string {
  const lines: string[] = [`Order for ${supplierName}`, ''];

  const includedItems = order.items.filter(
    (item) => item.declined_at == null && item.target_price != null,
  );

  let goodsTotal = 0;
  includedItems.forEach((item, index) => {
    const material = materialById.get(item.material_id);
    const name = material?.canonical_name ?? item.material_id;
    const unit = material?.unit ?? '';
    const targetPrice = item.target_price as number;
    const lineTotal = targetPrice * item.quantity;
    goodsTotal += lineTotal;

    lines.push(`${index + 1}. ${name}`);
    lines.push(`   Qty: ${item.quantity} ${unit}`.trimEnd());
    lines.push(`   Price: ${formatMoney(targetPrice)}/unit`);
    lines.push(`   Total: ${formatMoney(lineTotal)}`);
    lines.push('');
  });

  lines.push(`Goods total: ${formatMoney(goodsTotal)}`);
  lines.push(`Delivery: ${formatMoney(order.expected_delivery_fee)}`);
  lines.push(`Grand total: ${formatMoney(goodsTotal + order.expected_delivery_fee)}`);

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
          key={item.target_price ?? 'empty'}
          className={styles.priceInput}
          type="number"
          min="0"
          step="0.01"
          placeholder="—"
          defaultValue={item.target_price ?? ''}
          disabled={saving}
          onBlur={(e) => {
            const raw = e.target.value.trim();
            const value = raw === '' ? null : Number(raw);
            if (value !== item.target_price) onPatch({ target_price: value });
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
        <PriceDelta delta={item.price_delta} deltaPct={item.price_delta_pct} isDiscrepant={isDiscrepant} />
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

/** Same visual language/threshold as the existing price_delta display,
 * reused for received_price_delta (quoted vs received) — see ADR-0027 §3.
 * Not a new pattern, just parameterized over which delta pair is shown. */
function PriceDelta({
  delta,
  deltaPct,
  isDiscrepant,
  className,
}: {
  delta: number | null;
  deltaPct: number | null;
  isDiscrepant: boolean;
  className?: string;
}) {
  if (delta == null || deltaPct == null) {
    return <span className={[styles.deltaEmpty, className].filter(Boolean).join(' ')}>—</span>;
  }
  return (
    <span className={[isDiscrepant ? styles.deltaDiscrepant : styles.delta, className].filter(Boolean).join(' ')}>
      {delta >= 0 ? '+' : ''}
      {formatMoney(delta)} ({deltaPct >= 0 ? '+' : ''}
      {deltaPct.toFixed(1)}%)
    </span>
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

function ParseResponseSection({
  order,
  materialById,
  onApplied,
  targetField,
  title,
}: {
  order: Order;
  materialById: Map<string, Material>;
  onApplied: () => void;
  /** Which OrderItem field "Применить все совпадения" writes — the first
   * block writes received_price (first supplier answer), the second writes
   * confirmed_price (answer after negotiating on target_price). Same
   * parse-response endpoint and matching logic either way — only the PATCH
   * target differs. See ADR-0027 §2. */
  targetField: 'received_price' | 'confirmed_price';
  title: string;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState<unknown>(null);
  const [result, setResult] = useState<ParseOrderResponseResult | null>(null);

  // Editable prices/inclusion for category (a), keyed by order_item_id —
  // seeded from the parse result but independently editable per ADR-0018 §4.
  const [matchedPrices, setMatchedPrices] = useState<Record<string, number>>({});
  const [matchedIncluded, setMatchedIncluded] = useState<Record<string, boolean>>({});
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<unknown>(null);
  const [applySummary, setApplySummary] = useState<string | null>(null);

  async function handleParse() {
    const file = fileInputRef.current?.files?.[0];
    if (!file) return;
    setParsing(true);
    setParseError(null);
    setApplySummary(null);
    try {
      const parsed = await ordersApi.parseResponse(order.id, file);
      setResult(parsed);
      const prices: Record<string, number> = {};
      const included: Record<string, boolean> = {};
      for (const line of parsed.matched) {
        prices[line.order_item_id] = line.price;
        included[line.order_item_id] = true; // default-checked, ADR-0018 §3a
      }
      setMatchedPrices(prices);
      setMatchedIncluded(included);
    } catch (err) {
      setResult(null);
      setParseError(err);
    } finally {
      setParsing(false);
      // The file itself is never persisted (ADR-0018 §7) — clear the input
      // so a re-upload of the same filename still fires onChange/works.
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  async function handleApplyAllMatched() {
    if (!result) return;
    const toApply = result.matched.filter((line) => matchedIncluded[line.order_item_id]);
    if (toApply.length === 0) return;

    setApplying(true);
    setApplyError(null);
    setApplySummary(null);
    let succeeded = 0;
    try {
      for (const line of toApply) {
        const price = matchedPrices[line.order_item_id];
        await ordersApi.patchItem(order.id, line.order_item_id, { [targetField]: price });
        succeeded += 1;
      }
      onApplied();
    } catch (err) {
      setApplyError(err);
    } finally {
      setApplying(false);
      setApplySummary(`Применено ${succeeded} из ${toApply.length}`);
    }
  }

  // OrderItems with no matched line at all — see ADR-0018 §3b.
  const missing = result
    ? order.items.filter((item) => !result.matched.some((line) => line.order_item_id === item.id))
    : [];

  return (
    <div className={styles.parseSection}>
      <div className={styles.parseSectionTitle}>{title}</div>

      <div className={styles.parseUploadRow}>
        <FileInput ref={fileInputRef} accept=".pdf,image/*" disabled={parsing} />
        <button type="button" className={styles.parseButton} disabled={parsing} onClick={() => void handleParse()}>
          {parsing ? 'Распознаём…' : 'Распознать цены из документа'}
        </button>
        {parsing && <span className={styles.parseLoading}>Обращаемся к ИИ — это может занять несколько секунд…</span>}
      </div>

      {parseError != null && (
        <div className={styles.parseErrorBlock}>
          {parseError instanceof ApiError
            ? parseError.message
            : 'Не удалось распознать документ. Проверьте качество файла или введите цены вручную построчно.'}
        </div>
      )}

      {result != null && (
        <>
          <div className={styles.parseResultBlock}>
            <div className={styles.parseCategoryHeader}>
              <div className={styles.parseCategoryTitle}>Совпало ({result.matched.length})</div>
              <button
                type="button"
                className={styles.parseButton}
                disabled={applying || result.matched.every((l) => !matchedIncluded[l.order_item_id])}
                onClick={() => void handleApplyAllMatched()}
              >
                {applying ? 'Применяем…' : 'Применить все совпадения'}
              </button>
            </div>

            {applyError != null && <ErrorBanner error={applyError} />}
            {applySummary != null && <div className={styles.parseApplySummary}>{applySummary}</div>}

            {result.matched.length > 0 && (
              <table className={styles.parseTable}>
                <thead>
                  <tr>
                    <th className={styles.parseCheckboxCell} />
                    <th>Наша позиция</th>
                    <th className={styles.numCell}>Отправленная цена</th>
                    <th className={styles.numCell}>
                      {targetField === 'confirmed_price' ? 'Подтверждённая цена' : 'Полученная цена'}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {result.matched.map((line) => (
                    <MatchedLineRow
                      key={line.order_item_id}
                      line={line}
                      order={order}
                      materialById={materialById}
                      included={matchedIncluded[line.order_item_id] ?? true}
                      price={matchedPrices[line.order_item_id] ?? line.price}
                      onToggleIncluded={(value) =>
                        setMatchedIncluded((prev) => ({ ...prev, [line.order_item_id]: value }))
                      }
                      onPriceChange={(value) =>
                        setMatchedPrices((prev) => ({ ...prev, [line.order_item_id]: value }))
                      }
                    />
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className={styles.parseResultBlock}>
            <div className={styles.parseCategoryHeader}>
              <div className={styles.parseCategoryTitle}>Отсутствует в ответе ({missing.length})</div>
            </div>
            {missing.length > 0 && (
              <ul className={styles.parseMissingList}>
                {missing.map((item) => (
                  <li key={item.id} className={styles.parseMissingRow}>
                    <span className={styles.parseMissingInfo}>
                      {materialById.get(item.material_id)?.canonical_name ?? item.material_id}
                    </span>
                    <MissingItemMarkUnavailable item={item} order={order} onApplied={onApplied} />
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className={styles.parseResultBlock}>
            <div className={styles.parseCategoryHeader}>
              <div className={styles.parseCategoryTitle}>Лишнее ({result.extra.length})</div>
            </div>
            {result.extra.length > 0 && (
              <ul className={styles.parseExtraList}>
                {result.extra.map((line, index) => (
                  <ExtraLineRow key={index} line={line} order={order} />
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function MatchedLineRow({
  line,
  order,
  materialById,
  included,
  price,
  onToggleIncluded,
  onPriceChange,
}: {
  line: ParsedMatchedLine;
  order: Order;
  materialById: Map<string, Material>;
  included: boolean;
  price: number;
  onToggleIncluded: (value: boolean) => void;
  onPriceChange: (value: number) => void;
}) {
  const orderItem = order.items.find((item) => item.id === line.order_item_id);
  const material = orderItem ? materialById.get(orderItem.material_id) : undefined;
  const lowConfidence = LOW_CONFIDENCE_LEVELS.has(line.confidence);

  return (
    <tr className={lowConfidence ? styles.parseLowConfidenceRow : undefined}>
      <td className={styles.parseCheckboxCell}>
        <input type="checkbox" checked={included} onChange={(e) => onToggleIncluded(e.target.checked)} />
      </td>
      <td>
        {material?.canonical_name ?? orderItem?.material_id ?? line.raw_description}
        {lowConfidence && (
          <span className={styles.parseConfidenceWarning}>⚠ низкая уверенность распознавания</span>
        )}
        <span className={styles.parseReasoning}>{line.reasoning}</span>
      </td>
      <td className={styles.numCell}>{orderItem ? formatMoney(orderItem.quoted_price) : '—'}</td>
      <td className={styles.numCell}>
        <input
          className={styles.priceInput}
          type="number"
          min="0"
          step="0.01"
          value={price}
          onChange={(e) => {
            const value = Number(e.target.value);
            if (!Number.isNaN(value)) onPriceChange(value);
          }}
        />
      </td>
    </tr>
  );
}

function MissingItemMarkUnavailable({
  item,
  order,
  onApplied,
}: {
  item: OrderItem;
  order: Order;
  onApplied: () => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const isDeclined = item.declined_at != null;

  async function handleClick() {
    setSaving(true);
    setError(null);
    try {
      await ordersApi.patchItem(order.id, item.id, { declined: !isDeclined });
      onApplied();
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <span>
      <button
        type="button"
        className={isDeclined ? styles.declineButtonActive : styles.declineButton}
        disabled={saving}
        onClick={() => void handleClick()}
      >
        {isDeclined ? 'Отклонено' : 'Отметить как недоступно'}
      </button>
      {error != null && <span className={styles.parseConfidenceWarning}>Не удалось сохранить.</span>}
    </span>
  );
}

function ExtraLineRow({ line, order }: { line: ParsedExtraLine; order: Order }) {
  const [quantity, setQuantity] = useState(line.quantity ?? 1);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [added, setAdded] = useState(false);

  async function handleAdd() {
    setAdding(true);
    setError(null);
    try {
      await purchaseRecordsApi.create(order.project_id, {
        supplier_id: order.supplier_id,
        raw_description: line.raw_description,
        quantity,
        unit_price: line.price,
        material_id: null,
      });
      setAdded(true);
    } catch (err) {
      setError(err);
    } finally {
      setAdding(false);
    }
  }

  return (
    <li className={styles.parseExtraRow}>
      <span className={styles.parseExtraInfo}>
        <span className={styles.parseExtraDescription}>{line.raw_description}</span>
        <span className={styles.parseExtraMeta}>
          {formatMoney(line.price)} ×{' '}
          <input
            className={styles.parseQtyInput}
            type="number"
            min="1"
            step="1"
            value={quantity}
            disabled={adding || added}
            onChange={(e) => {
              const value = Number(e.target.value);
              if (Number.isFinite(value)) setQuantity(value);
            }}
          />
        </span>
      </span>
      {added ? (
        <span className={styles.parseAddedNotice}>Добавлено ✓</span>
      ) : (
        <button
          type="button"
          className={styles.parseButton}
          disabled={adding || quantity <= 0}
          onClick={() => void handleAdd()}
        >
          {adding ? 'Добавляем…' : 'Добавить'}
        </button>
      )}
      {error != null && <span className={styles.parseConfidenceWarning}>Не удалось добавить.</span>}
    </li>
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
