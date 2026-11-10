import type { MeasurementsMetrics } from '../../api/measurements';
import { blockOf, type Entity } from './entities';
import styles from './Measurements.module.css';

/** «Запланированные» (M2) for the range, from `total`. Not linked: the detail
 * endpoint cannot filter planned visits. */
export function PlannedSection({ data, entities }: { data: MeasurementsMetrics; entities: Entity[] }) {
  return (
    <section className={styles.section} aria-labelledby="measurements-planned">
      <div className={styles.sectionHeader}>
        <h2 id="measurements-planned" className={styles.sectionTitle}>
          Запланированные
        </h2>
      </div>
      <div className={styles.panel}>
        <table className={styles.table} aria-label="Запланированные">
          <thead>
            <tr>
              <th />
              <th className={styles.numHead}>Предстоящие</th>
              <th className={styles.numHead}>Просроченные</th>
            </tr>
          </thead>
          <tbody>
            {entities.map((entity) => {
              const block = blockOf(data.total, entity);
              if (block == null) return null;
              return (
                <tr key={entity.id}>
                  <th scope="row">{entity.label}</th>
                  <td className={styles.numCell} data-testid="upcoming">
                    {block.planned.upcoming}
                  </td>
                  <td className={styles.numCell} data-testid="overdue">
                    {block.planned.overdue}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
