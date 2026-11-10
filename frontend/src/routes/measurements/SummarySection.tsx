import type { MeasurementsMetrics, MeasurementsMetricsBlock } from '../../api/measurements';
import { Badge } from '../../components/Badge';
import { blockOf, type Entity } from './entities';
import { MetricValue } from './MetricValue';
import { KIND_LABEL, formatRange, formatRatio } from './format';
import { visitsHref } from './links';
import styles from './Measurements.module.css';

interface Props {
  data: MeasurementsMetrics;
  entities: Entity[];
}

/** «Сводка за диапазон»: one card per entity, numbers from `total` only. */
export function SummarySection({ data, entities }: Props) {
  return (
    <section className={styles.section} aria-labelledby="measurements-summary">
      <div className={styles.sectionHeader}>
        <h2 id="measurements-summary" className={styles.sectionTitle}>
          Сводка за {formatRange(data.from, data.to)}
        </h2>
        {data.total.is_partial && <Badge variant="neutral">неполный период</Badge>}
      </div>
      <div className={styles.cards}>
        {entities.map((entity) => {
          const block = blockOf(data.total, entity);
          if (block == null) return null;
          return (
            <SummaryCard key={entity.id} entity={entity} block={block} from={data.from} to={data.to} />
          );
        })}
      </div>
    </section>
  );
}

function SummaryCard({
  entity,
  block,
  from,
  to,
}: {
  entity: Entity;
  block: MeasurementsMetricsBlock;
  from: string;
  to: string;
}) {
  const link = (kind?: 'primary' | 'additional' | 'legacy') =>
    entity.linkable
      ? visitsHref({ from, to, measurer: entity.measurer ?? undefined, kind })
      : undefined;

  return (
    <article
      className={entity.id === 'company' ? `${styles.card} ${styles.cardCompany}` : styles.card}
      aria-label={entity.label}
    >
      <div className={styles.cardLabel}>{entity.label}</div>
      <div className={styles.cardHeadline}>
        <MetricValue href={link()} testId="conducted-total" className={styles.bigNumber}>
          {block.conducted.total}
        </MetricValue>
        <span className={styles.cardHeadlineCaption}>проведено</span>
      </div>
      <div className={styles.breakdown}>
        {(['primary', 'additional', 'legacy'] as const).map((kind) => (
          <span key={kind} className={styles.breakdownItem}>
            {KIND_LABEL[kind]}{' '}
            <MetricValue href={link(kind)} testId={`conducted-${kind}`} className={styles.num}>
              {block.conducted[kind]}
            </MetricValue>
          </span>
        ))}
      </div>
      <dl className={styles.stats}>
        <div>
          <dt>Замерных дней</dt>
          <dd className={styles.num} data-testid="visit-days">
            {block.visit_days}
          </dd>
        </div>
        <div>
          <dt>На замерный день</dt>
          <dd className={styles.num} data-testid="per-visit-day">
            {formatRatio(block.per_visit_day)}
          </dd>
        </div>
        <div>
          <dt>В среднем в неделю</dt>
          <dd className={styles.num} data-testid="per-week-avg">
            {formatRatio(block.per_week_avg)}
          </dd>
        </div>
      </dl>
    </article>
  );
}
