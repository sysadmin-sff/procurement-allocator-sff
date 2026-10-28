/** "Связать" pair suggestion for the order-response review screen — see
 * ADR-0046 §2. Pure, deterministic: a suggestion only preselects the choice
 * in the dialog, nothing is written until the employee clicks. */

export interface AliasCandidateLike {
  material_id: string | null;
  quantity: number;
  quoted_price: number;
}

export interface AliasSuggestion<T> {
  item: T;
  /** Which numbers matched — drives the basis text next to the suggestion. */
  by: 'price' | 'price_and_quantity';
}

/** Only "Отсутствует в ответе" items with a catalog material can be linked —
 * an alias points at material_id, a lightweight OrderItem (ADR-0033) has
 * none. */
export function aliasCandidates<T extends AliasCandidateLike>(items: T[]): T[] {
  return items.filter((item) => item.material_id != null);
}

/** Integer thousandths — prices are Numeric(12,3) server-side, so this is an
 * exact comparison at the stored precision, not a float === (0.1 + 0.2 !==
 * 0.3) and not a tolerance. */
function toThousandths(value: number): number {
  return Math.round(value * 1000);
}

/** Exactly one candidate matching the extra line's price (and its quantity,
 * when the line has one) → that candidate; zero or several → null, the
 * employee picks manually. */
export function suggestAliasPair<T extends AliasCandidateLike>(
  extra: { price: number; quantity: number | null },
  candidates: T[],
): AliasSuggestion<T> | null {
  const price = toThousandths(extra.price);
  const matches = aliasCandidates(candidates).filter(
    (item) =>
      toThousandths(item.quoted_price) === price && (extra.quantity == null || item.quantity === extra.quantity),
  );
  if (matches.length !== 1) return null;
  return { item: matches[0], by: extra.quantity == null ? 'price' : 'price_and_quantity' };
}
