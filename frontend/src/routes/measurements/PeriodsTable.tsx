import type { MeasurementsMetrics, MeasurementsMetricsBlock } from '../../api/measurements';
import { Badge } from '../../components/Badge';
import { blockOf, type Entity } from './entities';
import { formatPeriod, formatRatio } from './format';
import { visitsHref } from './links';
import { MetricValue } from './MetricValue';
import styles from './Measurements.module.css';

const COLUMNS = [
  { code: 'm1', label: 'Проведено', title: 'M1 — проведённые замеры' },
  { code: 'm2u', label: 'Предст.', title: 'M2 — запланированные, предстоящие' },
  { code: 'm2o', label: 'Просроч.', title: 'M2 — запланированные, просроченные' },
  { code: 'm3', label: 'Зам. дни', title: 'M3 — замерные дни' },
  { code: 'm4', label: 'На день', title: 'M4 — замеров на замерный день' },
  { code: 'm5', label: 'В неделю', title: 'M5 — среднее в неделю' },
] as const;

/** «По периодам»: rows are periods plus «Итого» from `total`; column groups
 * are the company and each measurer; every cell is one API value. */
export function PeriodsTable({ data, entities }: { data: MeasurementsMetrics; entities: Entity[] }) {
  return (
    <section className={styles.section} aria-labelledby="measurements-periods">
      <div className={styles.sectionHeader}>
        <h2 id="measurements-periods" className={styles.sectionTitle}>
          По периодам
        </h2>
      </div>
      <div className={`${styles.panel} ${styles.tableScroll}`}>
        <table className={styles.table} aria-label="По периодам">
          <thead>
            <tr>
              <th rowSpan={2} className={styles.stickyCol}>
                Период
              </th>
              {entities.map((entity) => (
                <th key={entity.id} colSpan={COLUMNS.length} className={styles.groupHead}>
                  {entity.label}
                </th>
              ))}
            </tr>
            <tr>
              {entities.flatMap((entity) =>
                COLUMNS.map((column, index) => (
                  <th
                    key={`${entity.id}-${column.code}`}
                    title={column.title}
                    className={index === 0 ? `${styles.numHead} ${styles.groupStart}` : styles.numHead}
                  >
                    {column.label}
                  </th>
                )),
              )}
            </tr>
          </thead>
          <tbody>
            {data.periods.map((period) => (
              <tr
                key={period.period_start}
                data-period={period.period_start}
                data-partial={String(period.is_partial)}
                className={period.is_partial ? styles.partialRow : undefined}
              >
                <th scope="row" className={styles.stickyCol}>
                  {formatPeriod(period.period_start, period.period_end, data.group_by)}
                  {period.is_partial && (
                    <>
                      {' '}
                      <Badge variant="neutral">неполный</Badge>
                    </>
                  )}
                </th>
                {entities.map((entity) => (
                  <EntityCells
                    key={entity.id}
                    entity={entity}
                    block={blockOf(period, entity)}
                    from={period.period_start}
                    to={period.period_end}
                  />
                ))}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" className={styles.stickyCol}>
                Итого
              </th>
              {entities.map((entity) => (
                <EntityCells
                  key={entity.id}
                  entity={entity}
                  block={blockOf(data.total, entity)}
                  from={data.from}
                  to={data.to}
                />
              ))}
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  );
}

function EntityCells({
  entity,
  block,
  from,
  to,
}: {
  entity: Entity;
  block: MeasurementsMetricsBlock | undefined;
  from: string;
  to: string;
}) {
  const id = entity.id;
  if (block == null) {
    return COLUMNS.map((column, index) => (
      <td key={column.code} className={index === 0 ? `${styles.numCell} ${styles.groupStart}` : styles.numCell}>
        —
      </td>
    ));
  }
  const href = entity.linkable
    ? visitsHref({ from, to, measurer: entity.measurer ?? undefined })
    : undefined;
  return (
    <>
      <td className={`${styles.numCell} ${styles.groupStart}`}>
        <MetricValue href={href} testId={`${id}-m1`}>
          {block.conducted.total}
        </MetricValue>
      </td>
      <td className={styles.numCell} data-testid={`${id}-m2-upcoming`}>
        {block.planned.upcoming}
      </td>
      <td className={styles.numCell} data-testid={`${id}-m2-overdue`}>
        {block.planned.overdue}
      </td>
      <td className={styles.numCell} data-testid={`${id}-m3`}>
        {block.visit_days}
      </td>
      <td className={styles.numCell} data-testid={`${id}-m4`}>
        {formatRatio(block.per_visit_day)}
      </td>
      <td className={styles.numCell} data-testid={`${id}-m5`}>
        {formatRatio(block.per_week_avg)}
      </td>
    </>
  );
}
