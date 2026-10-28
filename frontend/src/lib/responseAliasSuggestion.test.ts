import { describe, expect, it } from 'vitest';
import { aliasCandidates, suggestAliasPair } from './responseAliasSuggestion';

function candidate(overrides: Partial<{ id: string; material_id: string | null; quantity: number; quoted_price: number }> = {}) {
  return { id: 'item-1', material_id: 'mat-1', quantity: 8, quoted_price: 62.1, ...overrides };
}

describe('aliasCandidates (ADR-0046 §2)', () => {
  it('excludes missing items without a catalog material_id', () => {
    const withMaterial = candidate({ id: 'item-1' });
    const lightweight = candidate({ id: 'item-2', material_id: null });

    expect(aliasCandidates([withMaterial, lightweight])).toEqual([withMaterial]);
  });
});

describe('suggestAliasPair (ADR-0046 §2)', () => {
  it('suggests the single candidate matching price and quantity', () => {
    const match = candidate({ id: 'item-1' });
    const other = candidate({ id: 'item-2', material_id: 'mat-2', quoted_price: 40 });

    expect(suggestAliasPair({ price: 62.1, quantity: 8 }, [match, other])).toEqual({
      item: match,
      by: 'price_and_quantity',
    });
  });

  it('matches on price alone when the extra line has no quantity', () => {
    const match = candidate({ id: 'item-1', quantity: 3 });

    expect(suggestAliasPair({ price: 62.1, quantity: null }, [match])).toEqual({ item: match, by: 'price' });
  });

  it('does not suggest when the price matches but the quantity differs', () => {
    expect(suggestAliasPair({ price: 62.1, quantity: 7 }, [candidate()])).toBeNull();
  });

  it('does not suggest when several candidates match', () => {
    const a = candidate({ id: 'item-1' });
    const b = candidate({ id: 'item-2', material_id: 'mat-2' });

    expect(suggestAliasPair({ price: 62.1, quantity: 8 }, [a, b])).toBeNull();
  });

  it('does not suggest when no candidate matches', () => {
    expect(suggestAliasPair({ price: 99, quantity: 8 }, [candidate()])).toBeNull();
  });

  it('ignores candidates without material_id even if they match the numbers', () => {
    const match = candidate({ id: 'item-1' });
    const lightweight = candidate({ id: 'item-2', material_id: null });

    expect(suggestAliasPair({ price: 62.1, quantity: 8 }, [match, lightweight])).toEqual({
      item: match,
      by: 'price_and_quantity',
    });
  });

  it('compares prices exactly at thousandths, not with float ===', () => {
    // 0.1 + 0.2 === 0.30000000000000004 in IEEE-754 — a plain === would miss this.
    const match = candidate({ quoted_price: 0.3 });

    expect(suggestAliasPair({ price: 0.1 + 0.2, quantity: 8 }, [match])).toEqual({
      item: match,
      by: 'price_and_quantity',
    });
  });

  it('treats prices differing by one thousandth as different (no tolerance)', () => {
    expect(suggestAliasPair({ price: 62.101, quantity: 8 }, [candidate({ quoted_price: 62.1 })])).toBeNull();
  });
});
