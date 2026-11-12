import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { pricesApi } from '../../api/prices';
import type {
  PriceMatrix,
  PriceMatrixCell,
  PriceMatrixRow,
  PriceMatrixSupplier,
} from '../../api/types';
import { ErrorBanner } from '../../components/ErrorBanner';
import crudStyles from '../../components/CrudScreen.module.css';
import { useCategories } from '../../hooks/useCategories';
import { buildCategoryOrder, groupByCategory } from '../../lib/groupByCategory';
import { PriceHistoryPopover } from './PriceHistoryPopover';
import { formatDate, formatMoney, formatPct } from './format';
import styles from './PriceMatrix.module.css';

/**
 * Матрица цен «все материалы × все поставщики» (ADR-0054, ui-reference §10).
 * Всё сравнение (направление, %, самая дешёвая, «давно не обновлялся»)
 * приходит с backend — здесь только фильтры отображения и вёрстка.
 * Фильтры живут в URL, чтобы ссылку на конкретный срез можно было переслать.
 */
export function PriceMatrixPage() {
  const [params, setParams] = useSearchParams();
  const compareTo = params.get('compare_to');
  const query = params.get('q') ?? '';
  const category = params.get('category') ?? '';
  const onlyChanged = params.get('changed') === '1';
  const hideEmpty = params.get('hide_empty') === '1';

  const [matrix, setMatrix] = useState<PriceMatrix | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [openCell, setOpenCell] = useState<{
    row: PriceMatrixRow;
    supplier: PriceMatrixSupplier;
    anchor: DOMRect;
  } | null>(null);
  const { categories } = useCategories();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    pricesApi
      .matrix(compareTo)
      .then((data) => {
        if (!cancelled) setMatrix(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [compareTo]);

  function updateParam(key: string, value: string | null) {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true },
    );
  }

  const categoryOrder = useMemo(() => buildCategoryOrder(categories), [categories]);

  const groups = useMemo(() => {
    if (!matrix) return [];
    const needle = query.trim().toLowerCase();
    const changeCounts = (cell: PriceMatrixCell) =>
      cell.change === 'up' || cell.change === 'down' || (compareTo != null && cell.change === 'new');
    const visible = matrix.rows.filter((row) => {
      if (category && row.category_name !== category) return false;
      if (hideEmpty && row.cells.length === 0) return false;
      if (onlyChanged && !row.cells.some(changeCounts)) return false;
      if (
        needle &&
        !row.canonical_name.toLowerCase().includes(needle) &&
        !row.internal_sku.toLowerCase().includes(needle)
      ) {
        return false;
      }
      return true;
    });
    return groupByCategory(visible, categoryOrder);
  }, [matrix, query, category, hideEmpty, onlyChanged, compareTo, categoryOrder]);

  const visibleRowCount = groups.reduce((sum, g) => sum + g.items.length, 0);
  const categoryNames = useMemo(
    () => [...new Set((matrix?.rows ?? []).map((r) => r.category_name).filter((c): c is string => !!c))]
      .sort((a, b) => (categoryOrder.get(a) ?? Infinity) - (categoryOrder.get(b) ?? Infinity)),
    [matrix, categoryOrder],
  );

  return (
    <div className={crudStyles.page}>
      <div className={`${crudStyles.inner} ${styles.wideInner}`}>
        <div className={crudStyles.header}>
          <h1 className={crudStyles.title}>Цены поставщиков</h1>
          {matrix && <span className={styles.asOf}>на {formatDate(matrix.as_of)}</span>}
        </div>

        <div className={crudStyles.stack}>
          <div className={`${crudStyles.card} ${crudStyles.cardPadded}`}>
            <div className={styles.toolbar}>
              <div className={styles.toolbarGroup}>
                <span className={styles.toolbarLabel}>Сравнить с</span>
                <div className={styles.segmented} role="group" aria-label="База сравнения">
                  <button
                    type="button"
                    className={compareTo == null ? styles.segmentActive : styles.segment}
                    onClick={() => updateParam('compare_to', null)}
                  >
                    предыдущей ценой
                  </button>
                  <button
                    type="button"
                    className={compareTo != null ? styles.segmentActive : styles.segment}
                    onClick={() => updateParam('compare_to', compareTo ?? startOfMonth(new Date()))}
                  >
                    ценой на дату
                  </button>
                </div>
                {compareTo != null && (
                  <>
                    <input
                      type="date"
                      aria-label="Дата сравнения"
                      className={`${crudStyles.input} ${styles.dateInput}`}
                      value={compareTo}
                      max={matrix?.as_of}
                      onChange={(e) => e.target.value && updateParam('compare_to', e.target.value)}
                    />
                    <button
                      type="button"
                      className={styles.preset}
                      onClick={() => updateParam('compare_to', startOfMonth(new Date()))}
                    >
                      1-е число месяца
                    </button>
                    <button
                      type="button"
                      className={styles.preset}
                      onClick={() => updateParam('compare_to', startOfMonth(new Date(), -1))}
                    >
                      1-е число прошлого
                    </button>
                  </>
                )}
              </div>

              <div className={styles.toolbarGroup}>
                <input
                  type="search"
                  placeholder="Материал или SKU"
                  aria-label="Поиск материала"
                  className={`${crudStyles.input} ${styles.searchInput}`}
                  value={query}
                  onChange={(e) => updateParam('q', e.target.value || null)}
                />
                <select
                  aria-label="Категория"
                  className={`${crudStyles.select} ${styles.categorySelect}`}
                  value={category}
                  onChange={(e) => updateParam('category', e.target.value || null)}
                >
                  <option value="">Все категории</option>
                  {categoryNames.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
                <label className={styles.checkbox}>
                  <input
                    type="checkbox"
                    checked={onlyChanged}
                    onChange={(e) => updateParam('changed', e.target.checked ? '1' : null)}
                  />
                  только изменённые
                </label>
                <label className={styles.checkbox}>
                  <input
                    type="checkbox"
                    checked={hideEmpty}
                    onChange={(e) => updateParam('hide_empty', e.target.checked ? '1' : null)}
                  />
                  скрыть без цен
                </label>
              </div>
            </div>

            {matrix && (
              <div className={styles.summary}>
                <span className={styles.summaryDown}>▼ подешевело: {matrix.summary.down}</span>
                <span className={styles.summaryUp}>▲ подорожало: {matrix.summary.up}</span>
                <span className={styles.summaryNeutral}>
                  {compareTo != null ? 'новых после даты' : 'без истории'}: {matrix.summary.new}
                </span>
                <span className={styles.summaryNeutral}>без изменений: {matrix.summary.same}</span>
                <span className={styles.summaryHint}>
                  {compareTo != null
                    ? `сравнение с ценами на ${formatDate(compareTo)}`
                    : 'сравнение с предыдущей ценой каждого поставщика'}
                </span>
              </div>
            )}
          </div>

          {loading && !matrix && <div className={crudStyles.loading}>Загрузка…</div>}
          {loadError != null && <ErrorBanner error={loadError} />}

          {matrix && (
            <div className={`${crudStyles.card} ${loading ? styles.reloading : ''}`}>
              {matrix.suppliers.length === 0 ? (
                <div className={styles.emptyState}>В справочнике пока нет ни одной действующей цены.</div>
              ) : visibleRowCount === 0 ? (
                <div className={styles.emptyState}>Под фильтры не попал ни один материал.</div>
              ) : (
                <Matrix
                  matrix={matrix}
                  groups={groups}
                  compareMode={compareTo != null}
                  onOpenCell={(row, supplier, anchor) => setOpenCell({ row, supplier, anchor })}
                />
              )}
            </div>
          )}

          {matrix && (
            <p className={styles.legend}>
              <span className={styles.cellDown}>▼ ниже базы</span>
              <span className={styles.cellUp}>▲ выше базы</span>
              <span className={styles.legendCheapest}>самая низкая в строке</span>
              <span>
                <span className={styles.staleText}>красная дата</span> — поставщик не обновлял цены
                больше {matrix.stale_after_days} дней
              </span>
              <span>Нажмите на цену, чтобы увидеть историю.</span>
            </p>
          )}
        </div>
      </div>

      {openCell && (
        <PriceHistoryPopover
          key={`${openCell.row.material_id}:${openCell.supplier.id}`}
          materialId={openCell.row.material_id}
          materialName={openCell.row.canonical_name}
          supplierId={openCell.supplier.id}
          supplierName={openCell.supplier.short_name || openCell.supplier.name}
          anchor={openCell.anchor}
          onClose={() => setOpenCell(null)}
        />
      )}
    </div>
  );
}

function Matrix({
  matrix,
  groups,
  compareMode,
  onOpenCell,
}: {
  matrix: PriceMatrix;
  groups: { category: string | null; items: PriceMatrixRow[] }[];
  compareMode: boolean;
  onOpenCell: (row: PriceMatrixRow, supplier: PriceMatrixSupplier, anchor: DOMRect) => void;
}) {
  const columnCount = matrix.suppliers.length + 1;
  return (
    <div className={styles.matrixScroll}>
      <table className={styles.matrixTable}>
        <thead>
          <tr>
            <th className={styles.materialColHeader}>Материал</th>
            {matrix.suppliers.map((supplier) => (
              <SupplierHeader key={supplier.id} supplier={supplier} />
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <GroupRows
              key={group.category ?? '__none'}
              category={group.category}
              rows={group.items}
              suppliers={matrix.suppliers}
              columnCount={columnCount}
              compareMode={compareMode}
              onOpenCell={onOpenCell}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SupplierHeader({ supplier }: { supplier: PriceMatrixSupplier }) {
  const label = supplier.short_name || supplier.name;
  return (
    <th title={supplier.name}>
      <Link to={`/suppliers/${supplier.id}`} className={styles.supplierLink}>
        {label}
      </Link>
      <span
        className={supplier.is_stale ? styles.staleText : styles.supplierMeta}
        title="Дата последнего изменения цены у поставщика"
      >
        {supplier.last_price_date
          ? `${formatDate(supplier.last_price_date)} · ${supplier.days_since_update} дн.`
          : 'нет данных'}
      </span>
      {(supplier.changes.down > 0 || supplier.changes.up > 0) && (
        <span className={styles.supplierMeta}>
          {supplier.changes.down > 0 && <span className={styles.summaryDown}>▼{supplier.changes.down}</span>}
          {supplier.changes.down > 0 && supplier.changes.up > 0 && ' '}
          {supplier.changes.up > 0 && <span className={styles.summaryUp}>▲{supplier.changes.up}</span>}
        </span>
      )}
    </th>
  );
}

function GroupRows({
  category,
  rows,
  suppliers,
  columnCount,
  compareMode,
  onOpenCell,
}: {
  category: string | null;
  rows: PriceMatrixRow[];
  suppliers: PriceMatrixSupplier[];
  columnCount: number;
  compareMode: boolean;
  onOpenCell: (row: PriceMatrixRow, supplier: PriceMatrixSupplier, anchor: DOMRect) => void;
}) {
  return (
    <>
      <tr className={styles.categoryRow}>
        <td className={styles.categoryCell} colSpan={columnCount}>
          <span className={styles.categoryLabel}>{category ?? 'Без категории'}</span>
        </td>
      </tr>
      {rows.map((row) => {
        const bySupplier = new Map(row.cells.map((c) => [c.supplier_id, c]));
        return (
          <tr key={row.material_id}>
            <td className={styles.materialColCell}>
              <span className={styles.materialName}>{row.canonical_name}</span>
              <span className={styles.materialMeta}>
                {row.internal_sku} · {row.unit}
              </span>
            </td>
            {suppliers.map((supplier) => {
              const cell = bySupplier.get(supplier.id);
              return cell ? (
                <PriceCell
                  key={supplier.id}
                  cell={cell}
                  compareMode={compareMode}
                  onOpen={(anchor) => onOpenCell(row, supplier, anchor)}
                />
              ) : (
                <td key={supplier.id} className={styles.emptyCell} />
              );
            })}
          </tr>
        );
      })}
    </>
  );
}

function PriceCell({
  cell,
  compareMode,
  onOpen,
}: {
  cell: PriceMatrixCell;
  compareMode: boolean;
  onOpen: (anchor: DOMRect) => void;
}) {
  const changeClass =
    cell.change === 'down' ? styles.cellDown : cell.change === 'up' ? styles.cellUp : '';
  const arrow = cell.change === 'down' ? '▼' : cell.change === 'up' ? '▲' : null;
  const showNew = compareMode && cell.change === 'new';

  return (
    <td className={styles.priceTd}>
      <button
        type="button"
        className={`${styles.priceButton} ${changeClass} ${cell.is_cheapest ? styles.cheapest : ''}`}
        title={cellTitle(cell, compareMode)}
        onClick={(e) => onOpen(e.currentTarget.getBoundingClientRect())}
      >
        {formatMoney(cell.price)}
        {arrow && <span className={styles.arrow}>{arrow}</span>}
        {showNew && <span className={styles.newMark}>нов.</span>}
      </button>
    </td>
  );
}

function cellTitle(cell: PriceMatrixCell, compareMode: boolean): string {
  const since = `Действует с ${formatDate(cell.valid_from)}`;
  if (cell.baseline_price == null || cell.baseline_valid_from == null) {
    return compareMode ? `${since}. На дату сравнения цены не было.` : `${since}. Предыдущих цен нет.`;
  }
  const pct = cell.change_pct != null ? ` (${formatPct(cell.change_pct)})` : '';
  return `${since}. Было ${formatMoney(cell.baseline_price)} с ${formatDate(cell.baseline_valid_from)}${pct}.`;
}

/** YYYY-MM-DD первого числа месяца (offset — сдвиг в месяцах) по локальному
 * времени: <input type="date"> работает в локальных датах. */
function startOfMonth(date: Date, offset = 0): string {
  const d = new Date(date.getFullYear(), date.getMonth() + offset, 1);
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  return `${d.getFullYear()}-${mm}-01`;
}
