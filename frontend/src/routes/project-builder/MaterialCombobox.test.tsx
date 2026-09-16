import { useState } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MaterialCombobox } from './MaterialCombobox';
import styles from './ProjectBuilder.module.css';
import { materialsApi } from '../../api/materials';
import type { Material } from '../../api/types';

vi.mock('../../api/materials', () => ({
  materialsApi: { list: vi.fn() },
}));

const listMock = vi.mocked(materialsApi.list);

const material = {
  id: 'mat-1',
  internal_sku: 'MSH-FG-1814',
  canonical_name: 'Сетка Fiberglass 18x14',
  category_name: 'Сетка',
  unit: 'рулон',
  attributes: {},
};

function ControlledCombobox() {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Material | null>(null);
  return (
    <MaterialCombobox
      query={query}
      selected={selected}
      invalid={false}
      onQueryChange={(q) => {
        setQuery(q);
        setSelected(null);
      }}
      onSelect={(m) => {
        setSelected(m);
        setQuery(m.canonical_name);
      }}
      onQuantityFocus={() => {}}
    />
  );
}

function renderCombobox() {
  return render(<ControlledCombobox />);
}

describe('MaterialCombobox positioning', () => {
  beforeEach(() => {
    listMock.mockReset();
    listMock.mockResolvedValue([material]);
  });

  it('opens the list downward when there is enough room below the input', async () => {
    const user = userEvent.setup();
    renderCombobox();

    const input = screen.getByPlaceholderText('Название или артикул…');
    const wrap = input.parentElement as HTMLElement;
    vi.spyOn(wrap, 'getBoundingClientRect').mockReturnValue({
      bottom: 100,
      top: 60,
      left: 0,
      right: 400,
      width: 400,
      height: 40,
      x: 0,
      y: 60,
      toJSON: () => {},
    } as DOMRect);
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });

    await waitFor(() => expect(listMock).toHaveBeenCalled());
    await user.type(input, 'сетка');
    await screen.findByText(material.canonical_name);

    // Portalled into document.body — position: fixed, anchored to the
    // input's bottom edge (top set, no bottom) when opening downward.
    const list = document.querySelector(`.${styles.comboboxListPortal}`) as HTMLElement | null;
    expect(list).not.toBeNull();
    expect(list?.style.top).toBe('100px');
    expect(list?.style.bottom).toBe('');
  });

  it('opens the list upward when the input is near the bottom of the viewport', async () => {
    const user = userEvent.setup();
    renderCombobox();

    const input = screen.getByPlaceholderText('Название или артикул…');
    const wrap = input.parentElement as HTMLElement;
    vi.spyOn(wrap, 'getBoundingClientRect').mockReturnValue({
      bottom: 780,
      top: 740,
      left: 0,
      right: 400,
      width: 400,
      height: 40,
      x: 0,
      y: 740,
      toJSON: () => {},
    } as DOMRect);
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });

    await waitFor(() => expect(listMock).toHaveBeenCalled());
    await user.type(input, 'сетка');
    await screen.findByText(material.canonical_name);

    // Opening upward: bottom is set (anchored to the input's top edge,
    // window.innerHeight(800) - anchorRect.top(740) = 60), top is unset.
    const list = document.querySelector(`.${styles.comboboxListPortal}`) as HTMLElement | null;
    expect(list).not.toBeNull();
    expect(list?.style.bottom).toBe('60px');
    expect(list?.style.top).toBe('');
  });

  it('escapes a scrollable/clipping ancestor by portalling into document.body', async () => {
    const user = userEvent.setup();
    render(
      <div style={{ overflow: 'hidden', height: '50px' }}>
        <ControlledCombobox />
      </div>,
    );

    const input = screen.getByPlaceholderText('Название или артикул…');
    await waitFor(() => expect(listMock).toHaveBeenCalled());
    await user.type(input, 'сетка');
    await screen.findByText(material.canonical_name);

    const clippingAncestor = input.closest('div[style*="overflow: hidden"]') as HTMLElement;
    const list = document.querySelector(`.${styles.comboboxListPortal}`) as HTMLElement | null;
    expect(list).not.toBeNull();
    expect(clippingAncestor.contains(list)).toBe(false);
    expect(document.body.contains(list)).toBe(true);
  });
});
