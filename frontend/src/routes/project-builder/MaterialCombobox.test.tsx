import { useState } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MaterialCombobox } from './MaterialCombobox';
import styles from './ProjectBuilder.module.css';
import { materialsApi } from '../../api/materials';
import type { Material } from '../../api/types';

vi.mock('../../api/materials', () => ({
  materialsApi: { search: vi.fn() },
}));

const searchMock = vi.mocked(materialsApi.search);

const material = {
  id: 'mat-1',
  internal_sku: 'MSH-FG-1814',
  canonical_name: 'Сетка Fiberglass 18x14',
  category: 'Сетка',
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
    searchMock.mockReset();
    searchMock.mockResolvedValue([material]);
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

    await user.type(input, 'сетка');
    await waitFor(() => expect(searchMock).toHaveBeenCalled());
    await screen.findByText(material.canonical_name);

    const list = document.querySelector(`.${styles.comboboxList}`);
    expect(list).not.toBeNull();
    expect(list?.className).not.toContain(styles.comboboxListUp);
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

    await user.type(input, 'сетка');
    await waitFor(() => expect(searchMock).toHaveBeenCalled());
    await screen.findByText(material.canonical_name);

    const list = document.querySelector(`.${styles.comboboxList}`);
    expect(list).not.toBeNull();
    expect(list?.className).toContain(styles.comboboxListUp);
  });
});
