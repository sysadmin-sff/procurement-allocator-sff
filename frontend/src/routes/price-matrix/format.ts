export function formatMoney(value: number): string {
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** YYYY-MM-DD → DD.MM.YYYY без участия Date (без сдвига часового пояса). */
export function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.slice(0, 10).split('-');
  return `${day}.${month}.${year}`;
}

export function formatPct(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

/** Проценты динамики (ADR-0057): два знака, как в отчётах руководства. */
export function formatPct2(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
}

const MONTHS_SHORT = ['янв.', 'февр.', 'март', 'апр.', 'май', 'июнь', 'июль', 'авг.', 'сент.', 'окт.', 'нояб.', 'дек.'];
const MONTHS_FULL = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
];

/** 'YYYY-MM' → «окт.»; год добавляется, если в ряду месяцы разных лет. */
export function monthLabel(month: string, all: { month: string }[], full = false): string {
  const [year, mm] = month.split('-');
  const index = Number(mm) - 1;
  if (full) return `${MONTHS_FULL[index]} ${year}`;
  const multiYear = new Set(all.map((m) => m.month.slice(0, 4))).size > 1;
  return multiYear ? `${MONTHS_SHORT[index]} ${year.slice(2)}` : MONTHS_SHORT[index];
}
