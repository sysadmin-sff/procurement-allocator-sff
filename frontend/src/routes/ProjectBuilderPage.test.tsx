import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProjectBuilderPage } from './ProjectBuilderPage';
import { materialsApi } from '../api/materials';

vi.mock('../api/materials', () => ({
  materialsApi: {
    search: vi.fn(),
  },
}));

const searchMock = vi.mocked(materialsApi.search);

function renderPage() {
  return render(
    <MemoryRouter>
      <ProjectBuilderPage />
    </MemoryRouter>,
  );
}

describe('ProjectBuilderPage', () => {
  beforeEach(() => {
    searchMock.mockReset();
  });

  it('disables "Рассчитать закупку" until a row has both material and quantity', async () => {
    const user = userEvent.setup();
    searchMock.mockResolvedValue([
      {
        id: 'mat-1',
        internal_sku: 'MSH-FG-1814',
        canonical_name: 'Сетка Fiberglass 18x14',
        category: 'Сетка',
        unit: 'рулон',
        attributes: {},
      },
    ]);

    renderPage();

    const calcButton = screen.getByRole('button', { name: /Рассчитать закупку/ });
    expect(calcButton).toBeDisabled();

    const [materialInput] = screen.getAllByPlaceholderText('Название или артикул…');
    await user.type(materialInput, 'сетка');

    await waitFor(() => expect(searchMock).toHaveBeenCalledWith('сетка'));

    const option = await screen.findByText('Сетка Fiberglass 18x14');
    await user.click(option);

    expect(calcButton).toBeDisabled();

    const [qtyInput] = screen.getAllByPlaceholderText('0');
    await user.type(qtyInput, '5');

    await waitFor(() => expect(calcButton).not.toBeDisabled());
  });

  it('shows an incomplete-row indicator and a filled-row counter', async () => {
    renderPage();

    expect(screen.getByText(/Незаполненных строк: 2/)).toBeInTheDocument();
    expect(screen.getByText(/^0 позиций добавлено$/)).toBeInTheDocument();
  });

  it('adds a new row on Enter in the quantity field', async () => {
    const user = userEvent.setup();
    searchMock.mockResolvedValue([
      {
        id: 'mat-1',
        internal_sku: 'SKU-1',
        canonical_name: 'Material One',
        category: null,
        unit: 'шт',
        attributes: {},
      },
    ]);

    renderPage();

    const initialRows = screen.getAllByPlaceholderText('Название или артикул…');
    expect(initialRows).toHaveLength(2);

    const materialInputs = screen.getAllByPlaceholderText('Название или артикул…');
    await user.type(materialInputs[1], 'mat');
    const option = await screen.findByText('Material One');
    await user.click(option);

    const qtyInputs = screen.getAllByPlaceholderText('0');
    await user.type(qtyInputs[1], '3{Enter}');

    await waitFor(() => {
      expect(screen.getAllByPlaceholderText('Название или артикул…')).toHaveLength(3);
    });
  });
});
