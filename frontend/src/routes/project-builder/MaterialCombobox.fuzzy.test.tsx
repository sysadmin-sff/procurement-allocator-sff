import { useState } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MaterialCombobox } from './MaterialCombobox';
import { materialsApi } from '../../api/materials';
import type { Material } from '../../api/types';

vi.mock('../../api/materials', () => ({
  materialsApi: { list: vi.fn(), search: vi.fn() },
}));

const listMock = vi.mocked(materialsApi.list);
const searchMock = vi.mocked(materialsApi.search);

// Real catalog entries (backend/data/import/materials.csv) used verbatim so
// fuzzy-match thresholds are tuned against actual data, not synthetic strings.
const materials: Material[] = [
  {
    id: 'mat-gutr-001',
    internal_sku: 'GUTR-001',
    canonical_name: `5" Super Gutter x 24' (White/Bronze)`,
    category_name: 'Gutter',
    unit: 'pcs',
    attributes: {},
  },
  {
    id: 'mat-gutr-003',
    internal_sku: 'GUTR-003',
    canonical_name: `5" Super Gutter x 36' (Bronze)`,
    category_name: 'Gutter',
    unit: 'pcs',
    attributes: {},
  },
  {
    id: 'mat-msh-fg-1814',
    internal_sku: 'MSH-FG-1814',
    canonical_name: 'Сетка Fiberglass 18x14',
    category_name: 'Сетка',
    unit: 'рулон',
    attributes: {},
  },
  {
    id: 'mat-door-panic',
    internal_sku: 'DOOR-PANIC-36',
    canonical_name: 'Panic Hardware Door 36"',
    category_name: 'Doors',
    unit: 'pcs',
    attributes: {},
  },
];

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

describe('MaterialCombobox client-side fuzzy search', () => {
  beforeEach(() => {
    listMock.mockReset();
    searchMock.mockReset();
    listMock.mockResolvedValue(materials);
  });

  it('loads the full catalog once via materialsApi.list on mount, never calls search', async () => {
    const user = userEvent.setup();
    renderCombobox();

    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(1));

    const input = screen.getByPlaceholderText('Название или артикул…');
    await user.type(input, 'gutter');
    await user.type(input, ' white');

    expect(searchMock).not.toHaveBeenCalled();
    expect(listMock).toHaveBeenCalledTimes(1);
  });

  it('finds a material by words in reversed order ("white gutter")', async () => {
    const user = userEvent.setup();
    renderCombobox();
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(1));

    const input = screen.getByPlaceholderText('Название или артикул…');
    await user.type(input, 'white gutter');

    await screen.findByText(`5" Super Gutter x 24' (White/Bronze)`);
  });

  it('tolerates a small typo ("guttter")', async () => {
    const user = userEvent.setup();
    renderCombobox();
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(1));

    const input = screen.getByPlaceholderText('Название или артикул…');
    await user.type(input, 'guttter');

    await screen.findByText(`5" Super Gutter x 24' (White/Bronze)`);
  });

  it('finds a material by internal_sku', async () => {
    const user = userEvent.setup();
    renderCombobox();
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(1));

    const input = screen.getByPlaceholderText('Название или артикул…');
    await user.type(input, 'GUTR-003');

    await screen.findByText(`5" Super Gutter x 36' (Bronze)`);
  });

  it('does not surface unrelated materials for an unrelated query', async () => {
    const user = userEvent.setup();
    renderCombobox();
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(1));

    const input = screen.getByPlaceholderText('Название или артикул…');
    await user.type(input, 'panic door');

    await screen.findByText('Panic Hardware Door 36"');
    expect(screen.queryByText(`5" Super Gutter x 24' (White/Bronze)`)).not.toBeInTheDocument();
    expect(screen.queryByText('Сетка Fiberglass 18x14')).not.toBeInTheDocument();
  });

  it('Enter picks the highlighted option after a fuzzy query (keyboard nav preserved)', async () => {
    const user = userEvent.setup();
    renderCombobox();
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(1));

    const input = screen.getByPlaceholderText('Название или артикул…');
    await user.type(input, 'panic door');
    await screen.findByText('Panic Hardware Door 36"');

    await user.keyboard('{Enter}');

    expect(input).toHaveValue('Panic Hardware Door 36"');
  });
});
