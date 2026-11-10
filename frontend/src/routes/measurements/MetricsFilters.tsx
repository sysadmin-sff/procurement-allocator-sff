import { useEffect, useState, type FormEvent } from 'react';
import type { MeasurementsGroupBy, MeasurementsMetricsQuery } from '../../api/measurements';
import { Button } from '../../components/Button';
import styles from './Measurements.module.css';

interface Props {
  query: MeasurementsMetricsQuery;
  /** From the response: fills the date inputs when the URL has no dates. */
  requested?: { from: string; to: string };
  groupBy: MeasurementsGroupBy;
  measurerOptions: string[];
  onChange: (patch: Partial<Record<keyof MeasurementsMetricsQuery, string | undefined>>) => void;
}

const GROUPS: { value: MeasurementsGroupBy; label: string }[] = [
  { value: 'week', label: 'Неделя' },
  { value: 'month', label: 'Месяц' },
];

export function MetricsFilters({ query, requested, groupBy, measurerOptions, onChange }: Props) {
  const shownFrom = query.from ?? requested?.from ?? '';
  const shownTo = query.to ?? requested?.to ?? '';
  const [from, setFrom] = useState(shownFrom);
  const [to, setTo] = useState(shownTo);

  useEffect(() => {
    setFrom(shownFrom);
    setTo(shownTo);
  }, [shownFrom, shownTo]);

  function applyDates(event: FormEvent) {
    event.preventDefault();
    onChange({ from, to });
  }

  return (
    <form className={styles.filters} onSubmit={applyDates}>
      <label className={styles.field}>
        <span className={styles.fieldLabel}>С</span>
        <input
          type="date"
          className={styles.input}
          value={from}
          onChange={(event) => setFrom(event.target.value)}
        />
      </label>
      <label className={styles.field}>
        <span className={styles.fieldLabel}>По</span>
        <input
          type="date"
          className={styles.input}
          value={to}
          onChange={(event) => setTo(event.target.value)}
        />
      </label>
      <Button type="submit" variant="primary">
        Показать
      </Button>

      <div className={styles.segmented} role="group" aria-label="Группировка">
        {GROUPS.map((group) => (
          <button
            key={group.value}
            type="button"
            aria-pressed={groupBy === group.value}
            className={groupBy === group.value ? styles.segmentOn : styles.segmentOff}
            onClick={() => onChange({ group_by: group.value })}
          >
            {group.label}
          </button>
        ))}
      </div>

      <label className={styles.field}>
        <span className={styles.fieldLabel}>Замерщик</span>
        <select
          className={styles.input}
          value={query.measurer ?? ''}
          onChange={(event) => onChange({ measurer: event.target.value })}
        >
          <option value="">Все замерщики</option>
          {measurerOptions.map((key) => (
            <option key={key} value={key}>
              {key}
            </option>
          ))}
        </select>
      </label>
    </form>
  );
}
