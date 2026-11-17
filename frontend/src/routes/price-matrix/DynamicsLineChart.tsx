import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import type { PriceDynamicsMonth, PriceDynamicsPoint } from '../../api/types';
import { formatPct2, monthLabel } from './format';
import styles from './PriceDynamics.module.css';

export interface ChartSeries {
  id: string;
  label: string;
  color: string;
  dashed?: boolean;
  points: PriceDynamicsPoint[];
}

const HEIGHT = 320;
const MARGIN = { top: 16, right: 16, bottom: 32, left: 56 };
const NICE_STEPS = [0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100];

/** Линейный график на SVG без библиотек: один y (проценты), ноль выделен,
 * пропуски (null) рвут линию, наведение на месяц — вертикальная линия и
 * подсказка со значениями всех показанных серий. */
export function DynamicsLineChart({
  months,
  series,
}: {
  months: PriceDynamicsMonth[];
  series: ChartSeries[];
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(960);
  const [hover, setHover] = useState<number | null>(null);

  useLayoutEffect(() => {
    const node = wrapRef.current;
    if (!node) return;
    const measure = () => setWidth(Math.max(320, node.clientWidth));
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const values = series.flatMap((s) =>
    s.points.map((p) => p.avg_change_pct).filter((v): v is number => v != null),
  );
  const { lo, hi, step } = niceDomain(values);
  const plotW = width - MARGIN.left - MARGIN.right;
  const plotH = HEIGHT - MARGIN.top - MARGIN.bottom;
  const band = plotW / Math.max(1, months.length);
  const x = (i: number) => MARGIN.left + band * (i + 0.5);
  // На узком экране подписываем не каждый месяц, последний — всегда.
  const labelEvery = Math.max(1, Math.ceil(64 / band));
  const y = (v: number) => MARGIN.top + ((hi - v) / (hi - lo)) * plotH;
  const ticks: number[] = [];
  for (let t = lo; t <= hi + step / 2; t += step) ticks.push(Number(t.toFixed(4)));

  const hovered =
    hover == null
      ? []
      : series
          .map((s) => ({ s, value: s.points[hover]?.avg_change_pct ?? null }))
          .sort((a, b) => (b.value ?? -Infinity) - (a.value ?? -Infinity));
  const tooltipLeft = hover == null ? 0 : x(hover);

  return (
    <div ref={wrapRef} className={styles.chartWrap} onMouseLeave={() => setHover(null)}>
      <svg
        width={width}
        height={HEIGHT}
        role="img"
        aria-label="Среднее изменение цен поставщиков по месяцам, %"
        className={styles.chartSvg}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={MARGIN.left}
              x2={width - MARGIN.right}
              y1={y(t)}
              y2={y(t)}
              className={t === 0 ? styles.zeroLine : styles.gridLine}
            />
            <text x={MARGIN.left - 8} y={y(t)} className={styles.axisText} textAnchor="end" dominantBaseline="middle">
              {formatTick(t, step)}
            </text>
          </g>
        ))}
        {months.map((m, i) =>
          i % labelEvery === (months.length - 1) % labelEvery ? (
            <text
              key={m.month}
              x={i === months.length - 1 && labelEvery > 1 ? width - MARGIN.right : x(i)}
              y={HEIGHT - 10}
              className={styles.axisText}
              textAnchor={i === months.length - 1 && labelEvery > 1 ? 'end' : 'middle'}
            >
              {monthLabel(m.month, months)}
              {m.is_partial ? '*' : ''}
            </text>
          ) : null,
        )}

        {hover != null && (
          <line x1={x(hover)} x2={x(hover)} y1={MARGIN.top} y2={MARGIN.top + plotH} className={styles.crosshair} />
        )}

        {series.map((s) => (
          <g key={s.id}>
            {segments(s.points).map((segment, index) => (
              <path
                key={index}
                d={segment.map(([i, v], k) => `${k === 0 ? 'M' : 'L'}${x(i)},${y(v)}`).join(' ')}
                fill="none"
                stroke={s.color}
                strokeWidth={2}
                strokeDasharray={s.dashed ? '6 4' : undefined}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ))}
            {s.points.map((p, i) =>
              p.avg_change_pct == null ? null : (
                <circle
                  key={p.month}
                  cx={x(i)}
                  cy={y(p.avg_change_pct)}
                  r={hover === i ? 5 : 4}
                  fill={s.color}
                  stroke="var(--color-surface)"
                  strokeWidth={2}
                />
              ),
            )}
          </g>
        ))}

        {months.map((m, i) => (
          <rect
            key={m.month}
            x={MARGIN.left + band * i}
            y={MARGIN.top}
            width={band}
            height={plotH}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
            data-testid={`chart-hover-${m.month}`}
          />
        ))}
      </svg>

      {hover != null && (
        <div
          className={styles.tooltip}
          style={{
            left: tooltipLeft,
            transform: tooltipLeft > width / 2 ? 'translateX(calc(-100% - 12px))' : 'translateX(12px)',
          }}
          role="tooltip"
        >
          <div className={styles.tooltipTitle}>
            {monthLabel(months[hover].month, months, true)}
            {months[hover].is_partial && ' (месяц ещё идёт)'}
          </div>
          {hovered.map(({ s, value }) => (
            <div key={s.id} className={styles.tooltipRow}>
              <span
                className={s.dashed ? `${styles.swatch} ${styles.swatchDashed}` : styles.swatch}
                style={{ '--swatch': s.color } as CSSProperties}
              />
              <span className={styles.tooltipLabel}>{s.label}</span>
              <span className={styles.tooltipValue}>{value == null ? '—' : formatPct2(value)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Непрерывные куски серии: null рвёт линию. */
function segments(points: PriceDynamicsPoint[]): [number, number][][] {
  const result: [number, number][][] = [];
  let current: [number, number][] = [];
  points.forEach((p, i) => {
    if (p.avg_change_pct == null) {
      if (current.length) result.push(current);
      current = [];
    } else {
      current.push([i, p.avg_change_pct]);
    }
  });
  if (current.length) result.push(current);
  return result;
}

/** Домен y, всегда включающий 0, с «круглым» шагом сетки (~4–6 делений). */
function niceDomain(values: number[]): { lo: number; hi: number; step: number } {
  let lo = Math.min(0, ...values);
  let hi = Math.max(0, ...values);
  if (hi - lo < 1e-9) {
    lo = -1;
    hi = 1;
  }
  const rough = (hi - lo) / 5;
  const step = NICE_STEPS.find((s) => s >= rough) ?? Math.ceil(rough / 100) * 100;
  return { lo: Math.floor(lo / step) * step, hi: Math.ceil(hi / step) * step, step };
}

function formatTick(value: number, step: number): string {
  // Столько знаков, сколько нужно шагу: 0.5 → «+1.5%», 0.25 → «+0.75%».
  const digits = Number.isInteger(step) ? 0 : Number.isInteger(step * 10) ? 1 : 2;
  const text = value.toFixed(digits);
  return `${value > 0 ? '+' : ''}${text}%`;
}
