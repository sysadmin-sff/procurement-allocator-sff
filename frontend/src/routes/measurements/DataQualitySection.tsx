import type { MeasurementsMetrics } from '../../api/measurements';
import { blockOf, type Entity } from './entities';
import { MetricValue } from './MetricValue';
import styles from './Measurements.module.css';

export type DataQualityMetric =
  | 'without_result_completed'
  | 'without_result_not_completed'
  | 'no_outcome'
  | 'duplicates';

/** Builds the detail link for one number, or undefined to keep it plain.
 * Not passed today: GET /measurements/metrics/visits cannot filter by
 * duplicate, outcome, result source or completion (docs/known-issues.md), so
 * every number here stays non-clickable. Enabling links is passing this prop. */
export type DataQualityLinkBuilder = (
  metric: DataQualityMetric,
  entity: Entity,
  range: { from: string; to: string },
) => string | undefined;

const COLUMNS: { metric: DataQualityMetric; label: string; testId: string }[] = [
  { metric: 'without_result_completed', label: 'Без Site Visit Result, выполненные', testId: 'without-result-completed' },
  { metric: 'without_result_not_completed', label: 'Без Site Visit Result, невыполненные', testId: 'without-result-not-completed' },
  { metric: 'no_outcome', label: 'Без исхода', testId: 'no-outcome' },
  { metric: 'duplicates', label: 'Дубли', testId: 'duplicates' },
];

export function DataQualitySection({
  data,
  entities,
  linkFor,
}: {
  data: MeasurementsMetrics;
  entities: Entity[];
  linkFor?: DataQualityLinkBuilder;
}) {
  const range = { from: data.from, to: data.to };
  return (
    <section className={styles.section} aria-labelledby="measurements-quality">
      <div className={styles.sectionHeader}>
        <h2 id="measurements-quality" className={styles.sectionTitle}>
          Качество данных
        </h2>
        {linkFor == null && (
          <span className={styles.sectionNote}>Детализация по этим числам пока недоступна</span>
        )}
      </div>
      <div className={styles.panel}>
        <table className={styles.table} aria-label="Качество данных">
          <thead>
            <tr>
              <th />
              {COLUMNS.map((column) => (
                <th key={column.metric} className={styles.numHead}>
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entities.map((entity) => {
              const block = blockOf(data.total, entity);
              if (block == null) return null;
              const quality = block.data_quality;
              const values: Record<DataQualityMetric, number> = {
                without_result_completed: quality.without_site_visit_result.completed,
                without_result_not_completed: quality.without_site_visit_result.not_completed,
                no_outcome: quality.no_outcome,
                duplicates: quality.duplicates,
              };
              return (
                <tr key={entity.id}>
                  <th scope="row">{entity.label}</th>
                  {COLUMNS.map((column) => (
                    <td key={column.metric} className={styles.numCell}>
                      <MetricValue
                        href={linkFor?.(column.metric, entity, range)}
                        testId={column.testId}
                      >
                        {values[column.metric]}
                      </MetricValue>
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
