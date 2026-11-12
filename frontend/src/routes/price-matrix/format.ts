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
