import { describe, expect, it } from 'vitest';
import { hasColorChoiceMaterial, resolveMaterialName, retitleWithColor } from './colors';
import type { Material } from '../api/types';

function materialFixture(overrides: Partial<Material> = {}): Material {
  return {
    id: 'mat-1',
    internal_sku: 'GTR-EC-5',
    canonical_name: 'Super Gutter End Cap 5" (White/Bronze)',
    category_name: 'Gutter',
    unit: 'шт',
    attributes: {},
    color_options: ['White', 'Bronze'],
    color_fragment: '(White/Bronze)',
    ...overrides,
  };
}

describe('resolveMaterialName', () => {
  it('returns canonical_name as-is when color_options is empty/null', () => {
    const material = materialFixture({ color_options: null, color_fragment: null });
    expect(resolveMaterialName(material, 'White')).toBe(material.canonical_name);
  });

  it('returns canonical_name as-is when color_options is an empty array', () => {
    const material = materialFixture({ color_options: [], color_fragment: null });
    expect(resolveMaterialName(material, 'White')).toBe(material.canonical_name);
  });

  it('returns canonical_name as-is when color_options is non-empty but color is null/undefined', () => {
    const material = materialFixture();
    expect(resolveMaterialName(material, null)).toBe(material.canonical_name);
    expect(resolveMaterialName(material, undefined)).toBe(material.canonical_name);
  });

  it('replaces the parenthetical color fragment with the chosen color, stripping the second option', () => {
    const material = materialFixture();
    expect(resolveMaterialName(material, 'White')).toBe('Super Gutter End Cap 5" (White)');
    expect(resolveMaterialName(material, 'Bronze')).toBe('Super Gutter End Cap 5" (Bronze)');
  });

  it('replaces a bare (no-parens) color fragment without adding parens', () => {
    const material = materialFixture({
      canonical_name: '12 x 3/4" Bronze/White Stainless steel',
      color_options: ['Bronze', 'White'],
      color_fragment: 'Bronze/White',
    });
    expect(resolveMaterialName(material, 'White')).toBe('12 x 3/4" White Stainless steel');
  });

  it('returns canonical_name as-is when color is not in color_options', () => {
    const material = materialFixture();
    expect(resolveMaterialName(material, 'Green')).toBe(material.canonical_name);
  });

  it('does not throw for a material with no color_fragment even if color_options is set', () => {
    const material = materialFixture({ color_fragment: null });
    expect(resolveMaterialName(material, 'White')).toBe(material.canonical_name);
  });
});

describe('hasColorChoiceMaterial', () => {
  it('is false for an empty list', () => {
    expect(hasColorChoiceMaterial([])).toBe(false);
  });

  it('is false when no material has color_options', () => {
    expect(
      hasColorChoiceMaterial([materialFixture({ color_options: null }), materialFixture({ color_options: [] })]),
    ).toBe(false);
  });

  it('is true when at least one material has non-empty color_options', () => {
    expect(
      hasColorChoiceMaterial([materialFixture({ color_options: null }), materialFixture()]),
    ).toBe(true);
  });

  it('ignores undefined entries (material not yet loaded)', () => {
    expect(hasColorChoiceMaterial([undefined, materialFixture({ color_options: null })])).toBe(false);
  });
});

describe('retitleWithColor', () => {
  it('replaces the color word in the project title with the newly chosen color, keeping its case', () => {
    expect(retitleWithColor('3284 bronze - 1146 27th Ave S', 'White')).toBe('3284 white - 1146 27th Ave S');
    expect(retitleWithColor('3284 Bronze - 1146 27th Ave S', 'White')).toBe('3284 White - 1146 27th Ave S');
    expect(retitleWithColor('3284 BRONZE - 1146 27th Ave S', 'White')).toBe('3284 WHITE - 1146 27th Ave S');
  });

  it('leaves a title without a color word unchanged', () => {
    expect(retitleWithColor('3284 - 1146 27th Ave S', 'White')).toBe('3284 - 1146 27th Ave S');
  });

  it('matches whole words only', () => {
    expect(retitleWithColor('Whitehall Rd bronze', 'White')).toBe('Whitehall Rd white');
  });

  it('leaves the title unchanged when the color is cleared', () => {
    expect(retitleWithColor('3284 bronze', null)).toBe('3284 bronze');
  });
});
