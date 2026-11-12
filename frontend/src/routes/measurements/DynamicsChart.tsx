import type { MeasurementsMetrics } from '../../api/measurements';
import { blockOf, segmentClass, type Entity } from './entities';
import { formatPeriod } from './format';
import styles from './Measurements.module.css';

/** «Динамика»: conducted visits per period, a CSS bar per period.
 *
 * The only arithmetic on the client is pixel scaling: bar height =
 * company.conducted.total / max over the visible periods (agreed for this
 * screen, docs/ui-reference.md «Замеры»). Segment proportions are left to CSS
 * flex-grow with the API values; the number above a bar is the company value
 * from the API, never the sum of segments. */
export function DynamicsChart({
  data,
  measurers,
}: {
  data: MeasurementsMetrics;
  measurers: Entity[];
}) {
  const max = Math.max(0, ...data.periods.map((p) => p.company.conducted.total));

  return (
    <section className={styles.section} aria-labelledby="measurements-dynamics">
      <div className={styles.sectionHeader}>
        <h2 id="measurements-dynamics" className={styles.sectionTitle}>
          Динамика
        </h2>
        <ul className={styles.legend} aria-label="Легенда">
          {measurers.map((entity) => (
            <li key={entity.id}>
              <span className={`${styles.legendSwatch} ${segmentClass(entity.colorIndex)}`} />
              {entity.label}
            </li>
          ))}
        </ul>
      </div>
      <ol className={styles.chart} aria-label="Динамика проведённых замеров">
        {data.periods.map((period) => {
          const label = formatPeriod(period.period_start, period.period_end, data.group_by);
          const total = period.company.conducted.total;
          const height = max > 0 ? (total / max) * 100 : 0;
          return (
            <li
              key={period.period_start}
              className={styles.chartColumn}
              data-partial={String(period.is_partial)}
              aria-label={`${label}: ${total}${period.is_partial ? ' (неполный период)' : ''}`}
            >
              <span className={styles.chartValue}>{total}</span>
              <div className={styles.chartTrack}>
                <div
                  className={period.is_partial ? `${styles.bar} ${styles.barPartial}` : styles.bar}
                  style={{ height: `${height}%` }}
                >
                  {measurers.map((entity) => {
                    const value = blockOf(period, entity)?.conducted.total ?? 0;
                    if (value === 0) return null;
                    return (
                      <div
                        key={entity.id}
                        className={`${styles.segment} ${segmentClass(entity.colorIndex)}`}
                        style={{ flexGrow: value }}
                        title={`${entity.label}: ${value}`}
                      />
                    );
                  })}
                </div>
              </div>
              <span className={styles.chartLabel}>
                {label}
                {period.is_partial && <span className={styles.partialMark}> · неполный</span>}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
