import type { MeasurementsGroupBy, MeasurementsVisitKind } from '../../api/measurements';

/* Display only: string formatting and label dictionaries. No metric is
   computed here (ADR-0053 «Последствия»: metrics are never computed on the
   frontend). Dates from the API are NY calendar dates as YYYY-MM-DD — they
   are split as strings, never passed through Date, so the browser zone cannot
   shift a day. */

const MONTHS = [
  'Январь',
  'Февраль',
  'Март',
  'Апрель',
  'Май',
  'Июнь',
  'Июль',
  'Август',
  'Сентябрь',
  'Октябрь',
  'Ноябрь',
  'Декабрь',
];

function parts(iso: string): [string, string, string] {
  const [year, month, day] = iso.split('-');
  return [year, month, day];
}

/** 2026-10-05 → 05.10.2026 */
export function formatDate(iso: string): string {
  const [year, month, day] = parts(iso);
  return `${day}.${month}.${year}`;
}

/** 28.09–01.11 within one year, full dates across years. */
export function formatRange(from: string, to: string): string {
  const [fromYear, fromMonth, fromDay] = parts(from);
  const [toYear, toMonth, toDay] = parts(to);
  if (fromYear !== toYear) return `${formatDate(from)}–${formatDate(to)}`;
  return `${fromDay}.${fromMonth}–${toDay}.${toMonth}`;
}

export function formatPeriod(start: string, end: string, groupBy: MeasurementsGroupBy): string {
  if (groupBy === 'month') {
    const [year, month] = parts(start);
    return `${MONTHS[Number(month) - 1]} ${year}`;
  }
  return formatRange(start, end);
}

export const ALIGNMENT_LABEL: Record<MeasurementsGroupBy, string> = {
  week: 'целые недели',
  month: 'целые месяцы',
};

/** data_as_of is UTC; it is shown in the module zone the API names. */
export function formatDataAsOf(utc: string, timeZone: string): string {
  const text = new Intl.DateTimeFormat('ru-RU', {
    timeZone,
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(new Date(utc));
  return `${text} (${timeZone})`;
}

/** Decimal strings are shown verbatim; null → «—». */
export function formatRatio(value: string | null): string {
  return value ?? '—';
}

export function measurerLabel(key: string | null): string {
  return key ?? 'Без замерщика';
}

export const KIND_LABEL: Record<MeasurementsVisitKind, string> = {
  primary: 'Замер',
  additional: 'Доп. замер',
  legacy: 'Встреча',
};

export const RESULT_SOURCE_LABEL: Record<string, string> = {
  funnel: 'Воронка',
  site_visit: 'Site Visit Result',
};

/** Funnel outcomes (ADR-0053 §3) and Site Visit Result types (ADR-0051 §3). */
export const OUTCOME_LABEL: Record<string, string> = {
  produced: 'Передан в продажу',
  closed: 'Закрыт',
  not_held: 'Не состоялся',
  no_data: 'Нет данных',
  sold: 'Продано на месте',
  completed: 'Проведён, передан в продажу',
  not_sold: 'Не продано на месте',
  declined: 'Отказ до замера',
};

export function outcomeLabel(outcome: string | null): string {
  if (outcome == null) return '—';
  return OUTCOME_LABEL[outcome] ?? outcome;
}
