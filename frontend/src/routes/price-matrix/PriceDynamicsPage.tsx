import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { pricesApi } from '../../api/prices';
import type { PriceDynamics, PriceDynamicsMonth, PriceDynamicsPoint } from '../../api/types';
import { ErrorBanner } from '../../components/ErrorBanner';
import crudStyles from '../../components/CrudScreen.module.css';
import { DynamicsLineChart, type ChartSeries } from './DynamicsLineChart';
import { PricesTabs } from './PricesTabs';
import { OVERALL_COLOR, SERIES_COLORS } from './dynamicsPalette';
import { formatDate, formatPct2, monthLabel } from './format';
import matrixStyles from './PriceMatrix.module.css';
import styles from './PriceDynamics.module.css';

const DEFAULT_SELECTED = 5;

/**
 * Динамика цен (ADR-0057): насколько в среднем изменились цены поставщика
 * за каждый месяц. Все проценты считает backend, здесь только выбор
 * поставщиков для графика и вёрстка.
 */
export function PriceDynamicsPage() {
  const [params, setParams] = useSearchParams();
  const today = new Date();
  const range = params.get('range') ?? 'last12';
  const { start, end } = rangeBounds(range, today);

  const [data, setData] = useState<PriceDynamics | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  /** Слот цвета → поставщик. Цвет закреплён за поставщиком, пока он выбран:
   * снятие одного не перекрашивает остальных. */
  const [slots, setSlots] = useState<(string | null)[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    pricesApi
      .dynamics(start, end)
      .then((result) => {
        if (!cancelled) setData(result);
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
  }, [start, end]);

  // По умолчанию — поставщики с наибольшим числом сравнимых позиций.
  const activeSlots = useMemo(() => {
    if (slots) return slots;
    if (!data) return Array<string | null>(SERIES_COLORS.length).fill(null);
    const weight = (points: PriceDynamicsPoint[]) => Math.max(0, ...points.map((p) => p.compared));
    const top = [...data.suppliers]
      .sort((a, b) => weight(b.points) - weight(a.points))
      .slice(0, DEFAULT_SELECTED)
      .map((s) => s.supplier_id);
    return SERIES_COLORS.map((_, i) => top[i] ?? null);
  }, [slots, data]);

  const slotOf = (supplierId: string) => activeSlots.indexOf(supplierId);
  const selectedCount = activeSlots.filter(Boolean).length;
  const [showOverall, setShowOverall] = useState(true);

  function toggleSupplier(supplierId: string) {
    const next = [...activeSlots];
    const slot = next.indexOf(supplierId);
    if (slot >= 0) next[slot] = null;
    else {
      const free = next.indexOf(null);
      if (free < 0) return;
      next[free] = supplierId;
    }
    setSlots(next);
  }

  const chartSeries: ChartSeries[] = useMemo(() => {
    if (!data) return [];
    const series: ChartSeries[] = [];
    if (showOverall) {
      series.push({ id: 'overall', label: 'В среднем по всем', color: OVERALL_COLOR, dashed: true, points: data.overall });
    }
    activeSlots.forEach((supplierId, slot) => {
      const supplier = supplierId && data.suppliers.find((s) => s.supplier_id === supplierId);
      if (supplier) {
        series.push({
          id: supplier.supplier_id,
          label: supplier.short_name || supplier.name,
          color: SERIES_COLORS[slot],
          points: supplier.points,
        });
      }
    });
    return series;
  }, [data, activeSlots, showOverall]);

  const yearOptions = [0, 1, 2].map((back) => String(today.getFullYear() - back));

  return (
    <div className={crudStyles.page}>
      <div className={`${crudStyles.inner} ${matrixStyles.wideInner}`}>
        <div className={crudStyles.header}>
          <h1 className={crudStyles.title}>Цены поставщиков</h1>
          {data && <span className={matrixStyles.asOf}>на {formatDate(data.as_of)}</span>}
        </div>
        <PricesTabs />

        <div className={crudStyles.stack}>
          <div className={`${crudStyles.card} ${crudStyles.cardPadded}`}>
            <div className={matrixStyles.toolbar}>
              <div className={matrixStyles.toolbarGroup}>
                <span className={matrixStyles.toolbarLabel}>Период</span>
                <div className={matrixStyles.segmented} role="group" aria-label="Период">
                  {[{ value: 'last12', label: 'последние 12 месяцев' }, ...yearOptions.map((y) => ({ value: y, label: y }))].map(
                    (option) => (
                      <button
                        key={option.value}
                        type="button"
                        className={range === option.value ? matrixStyles.segmentActive : matrixStyles.segment}
                        onClick={() =>
                          setParams(option.value === 'last12' ? {} : { range: option.value }, { replace: true })
                        }
                      >
                        {option.label}
                      </button>
                    ),
                  )}
                </div>
              </div>
              <p className={styles.explain}>
                Каждая точка — насколько в среднем изменились цены поставщика за месяц: цена на конец месяца против
                цены на конец предыдущего, по всем позициям, где цена есть в обеих точках (без изменений — 0%).
              </p>
            </div>
          </div>

          {loading && !data && <div className={crudStyles.loading}>Загрузка…</div>}
          {loadError != null && <ErrorBanner error={loadError} />}

          {data && (
            <div className={`${crudStyles.card} ${crudStyles.cardPadded} ${loading ? matrixStyles.reloading : ''}`}>
              <div className={styles.chartHeader}>
                <h2 className={styles.chartTitle}>Среднее изменение цен по месяцам, %</h2>
                <ul className={styles.legend} aria-label="Легенда">
                  {chartSeries.map((s) => (
                    <li key={s.id}>
                      <span
                        className={s.dashed ? `${styles.swatch} ${styles.swatchDashed}` : styles.swatch}
                        style={{ '--swatch': s.color } as CSSProperties}
                      />
                      {s.label}
                    </li>
                  ))}
                </ul>
              </div>
              {data.suppliers.length === 0 ? (
                <div className={matrixStyles.emptyState}>
                  За этот период нет цен, которые можно сравнить месяц к месяцу.
                </div>
              ) : (
                <DynamicsLineChart months={data.months} series={chartSeries} />
              )}
              <p className={styles.chartHint}>
                Выше нуля — подорожание, ниже — подешевление. Поставщиков для графика (до {SERIES_COLORS.length})
                выберите галочками в таблице.
              </p>
            </div>
          )}

          {data && data.suppliers.length > 0 && (
            <div className={crudStyles.card}>
              <DynamicsTable
                data={data}
                slotOf={slotOf}
                canAddMore={selectedCount < SERIES_COLORS.length}
                showOverall={showOverall}
                onToggleOverall={() => setShowOverall((v) => !v)}
                onToggle={toggleSupplier}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function DynamicsTable({
  data,
  slotOf,
  canAddMore,
  showOverall,
  onToggleOverall,
  onToggle,
}: {
  data: PriceDynamics;
  slotOf: (supplierId: string) => number;
  canAddMore: boolean;
  showOverall: boolean;
  onToggleOverall: () => void;
  onToggle: (supplierId: string) => void;
}) {
  return (
    <div className={styles.tableScroll}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th className={styles.nameHeader}>Поставщик</th>
            {data.months.map((m) => (
              <th key={m.month} className={styles.monthHeader} title={monthTitle(m)}>
                {monthLabel(m.month, data.months)}
                {m.is_partial && <span className={styles.partialMark}>*</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr className={styles.overallRow}>
            <td className={styles.nameCell}>
              <label className={styles.rowToggle}>
                <input type="checkbox" checked={showOverall} onChange={onToggleOverall} />
                <span
                  className={`${styles.swatch} ${styles.swatchDashed}`}
                  style={{ '--swatch': OVERALL_COLOR } as CSSProperties}
                />
                В среднем по всем
              </label>
            </td>
            {data.overall.map((point, i) => (
              <ValueCell key={point.month} point={point} month={data.months[i]} />
            ))}
          </tr>
          {data.suppliers.map((supplier) => {
            const slot = slotOf(supplier.supplier_id);
            const selected = slot >= 0;
            const label = supplier.short_name || supplier.name;
            return (
              <tr key={supplier.supplier_id}>
                <td className={styles.nameCell} title={supplier.name}>
                  <label className={styles.rowToggle}>
                    <input
                      type="checkbox"
                      aria-label={`Показать ${label} на графике`}
                      checked={selected}
                      disabled={!selected && !canAddMore}
                      onChange={() => onToggle(supplier.supplier_id)}
                    />
                    <span
                      className={styles.swatch}
                      style={{ '--swatch': selected ? SERIES_COLORS[slot] : 'transparent' } as CSSProperties}
                    />
                    {label}
                  </label>
                </td>
                {supplier.points.map((point, i) => (
                  <ValueCell key={point.month} point={point} month={data.months[i]} />
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className={styles.tableNote}>
        * текущий месяц — по {formatDate(data.as_of)}. Нажмите на значение, чтобы открыть таблицу цен с изменениями за
        этот месяц.
      </p>
    </div>
  );
}

function ValueCell({ point, month }: { point: PriceDynamicsPoint; month: PriceDynamicsMonth }) {
  if (point.avg_change_pct == null) {
    return (
      <td className={styles.valueCell}>
        <span className={styles.noValue} title="Нет позиций, которые можно сравнить с прошлым месяцем">
          —
        </span>
      </td>
    );
  }
  const pct = point.avg_change_pct;
  const tone = pct > 0 ? matrixStyles.cellUp : pct < 0 ? matrixStyles.cellDown : '';
  const title = `Сравнено позиций: ${point.compared}; подорожало: ${point.up}, подешевело: ${point.down}`;
  return (
    <td className={styles.valueCell}>
      <Link
        className={`${styles.valueLink} ${tone}`}
        title={title}
        to={`/prices?compare_to=${month.start}&period_end=${month.end}&changed=1`}
      >
        {formatPct2(pct)}
      </Link>
    </td>
  );
}

function monthTitle(m: PriceDynamicsMonth): string {
  return `${formatDate(m.start)} — ${formatDate(m.end)}${m.is_partial ? ' (месяц ещё идёт)' : ''}`;
}

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

/** range → YYYY-MM границы запроса; null — пусть backend возьмёт последние 12 мес. */
function rangeBounds(range: string, today: Date): { start: string | null; end: string | null } {
  if (!/^\d{4}$/.test(range)) return { start: null, end: null };
  const year = Number(range);
  const endMonth = year === today.getFullYear() ? today.getMonth() + 1 : 12;
  return { start: `${year}-01`, end: `${year}-${pad(endMonth)}` };
}
