import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProjectBuilderPage } from './ProjectBuilderPage';
import { allocationApi } from '../api/allocation';
import { materialsApi } from '../api/materials';
import { projectsApi } from '../api/projects';

vi.mock('../api/materials', () => ({
  materialsApi: {
    search: vi.fn(),
    list: vi.fn(),
  },
}));

vi.mock('../api/projects', () => ({
  projectsApi: {
    create: vi.fn(),
    updateProject: vi.fn(),
    addItem: vi.fn(),
    updateItem: vi.fn(),
    removeItem: vi.fn(),
  },
}));

vi.mock('../api/allocation', () => ({
  allocationApi: {
    run: vi.fn(),
  },
}));

const searchMock = vi.mocked(materialsApi.search);
const materialsListMock = vi.mocked(materialsApi.list);
const createMock = vi.mocked(projectsApi.create);
const updateProjectMock = vi.mocked(projectsApi.updateProject);
const addItemMock = vi.mocked(projectsApi.addItem);
const updateItemMock = vi.mocked(projectsApi.updateItem);
const removeItemMock = vi.mocked(projectsApi.removeItem);
const runAllocationMock = vi.mocked(allocationApi.run);

function renderPage() {
  return render(
    <MemoryRouter>
      <ProjectBuilderPage />
    </MemoryRouter>,
  );
}

const material = {
  id: 'mat-1',
  internal_sku: 'MSH-FG-1814',
  canonical_name: 'Сетка Fiberglass 18x14',
  category: 'Сетка',
  unit: 'рулон',
  attributes: {},
};

describe('ProjectBuilderPage', () => {
  beforeEach(() => {
    searchMock.mockReset();
    materialsListMock.mockReset();
    createMock.mockReset();
    updateProjectMock.mockReset();
    addItemMock.mockReset();
    updateItemMock.mockReset();
    removeItemMock.mockReset();
    runAllocationMock.mockReset();
    materialsListMock.mockResolvedValue([]);
  });

  it('disables "Рассчитать закупку" until a row has both material and quantity', async () => {
    const user = userEvent.setup();
    searchMock.mockResolvedValue([material]);

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
    searchMock.mockResolvedValue([{ ...material, id: 'mat-1', canonical_name: 'Material One' }]);

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

  it('creates the project after a debounced pause once the title is typed', async () => {
    const user = userEvent.setup();
    createMock.mockResolvedValue({
      id: 'proj-1',
      title: 'Pool cage',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-18T00:00:00Z',
    });

    renderPage();

    const titleInput = screen.getByLabelText('Название проекта');
    await user.type(titleInput, 'Pool cage');

    expect(createMock).not.toHaveBeenCalled();

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1), { timeout: 2000 });
    expect(createMock).toHaveBeenCalledWith({ title: 'Pool cage' });
  });

  it('creates a ProjectItem once a row becomes filled, then updates it instead of re-adding on further quantity changes', async () => {
    const user = userEvent.setup();
    searchMock.mockResolvedValue([material]);
    createMock.mockResolvedValue({
      id: 'proj-1',
      title: 'Проект без названия',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-18T00:00:00Z',
    });
    addItemMock.mockResolvedValue({
      id: 'item-1',
      project_id: 'proj-1',
      material_id: 'mat-1',
      quantity: 5,
    });
    updateItemMock.mockResolvedValue({
      id: 'item-1',
      project_id: 'proj-1',
      material_id: 'mat-1',
      quantity: 8,
    });

    renderPage();

    const [materialInput] = screen.getAllByPlaceholderText('Название или артикул…');
    await user.type(materialInput, 'сетка');
    await waitFor(() => expect(searchMock).toHaveBeenCalled());
    const option = await screen.findByText(material.canonical_name);
    await user.click(option);

    const [qtyInput] = screen.getAllByPlaceholderText('0');
    await user.type(qtyInput, '5');

    await waitFor(() => expect(addItemMock).toHaveBeenCalledTimes(1), { timeout: 2000 });
    expect(createMock).toHaveBeenCalledTimes(1);
    expect(addItemMock).toHaveBeenCalledWith('proj-1', { material_id: 'mat-1', quantity: 5 });

    await user.type(qtyInput, '{Backspace}8');

    await waitFor(() => expect(updateItemMock).toHaveBeenCalledTimes(1), { timeout: 2000 });
    expect(updateItemMock).toHaveBeenCalledWith('proj-1', 'item-1', 8);
    expect(addItemMock).toHaveBeenCalledTimes(1);
  });

  it('flushes a still-pending quantity edit immediately on "Рассчитать закупку", instead of only waiting for already-started saves', async () => {
    const user = userEvent.setup();
    searchMock.mockResolvedValue([material]);
    createMock.mockResolvedValue({
      id: 'proj-1',
      title: 'Проект без названия',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-18T00:00:00Z',
    });
    addItemMock.mockResolvedValue({
      id: 'item-1',
      project_id: 'proj-1',
      material_id: 'mat-1',
      quantity: 5,
    });
    updateItemMock.mockResolvedValue({
      id: 'item-1',
      project_id: 'proj-1',
      material_id: 'mat-1',
      quantity: 9,
    });
    runAllocationMock.mockResolvedValue({
      id: 'run-1',
      project_id: 'proj-1',
      created_at: '2026-08-18T00:00:00Z',
      algorithm_version: null,
      status: 'ok',
      lines: [],
      orphaned_materials: [],
      supplier_summaries: [],
    });

    renderPage();

    const [materialInput] = screen.getAllByPlaceholderText('Название или артикул…');
    await user.type(materialInput, 'сетка');
    await waitFor(() => expect(searchMock).toHaveBeenCalled());
    const option = await screen.findByText(material.canonical_name);
    await user.click(option);

    const [qtyInput] = screen.getAllByPlaceholderText('0');
    await user.type(qtyInput, '5');
    await waitFor(() => expect(addItemMock).toHaveBeenCalledTimes(1), { timeout: 2000 });

    // This edit is still sitting in its debounce window — nothing has been
    // sent to the backend for it yet — when the user clicks Calculate.
    await user.type(qtyInput, '{Backspace}9');
    expect(updateItemMock).not.toHaveBeenCalled();

    const calcButton = await screen.findByRole('button', { name: /Рассчитать закупку/ });
    await user.click(calcButton);

    await waitFor(() => expect(updateItemMock).toHaveBeenCalledTimes(1), { timeout: 2000 });
    expect(updateItemMock).toHaveBeenCalledWith('proj-1', 'item-1', 9);
    await waitFor(() => expect(runAllocationMock).toHaveBeenCalledWith('proj-1'));
  });

  it('does not drop an earlier row\'s pending save when a second row is edited within the same debounce window', async () => {
    const user = userEvent.setup();
    const materialTwo = { ...material, id: 'mat-2', canonical_name: 'Rivet Box' };
    searchMock.mockImplementation((q: string) =>
      Promise.resolve(
        q.toLowerCase().includes('rivet') ? [materialTwo] : [material],
      ),
    );
    createMock.mockResolvedValue({
      id: 'proj-1',
      title: 'Проект без названия',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-18T00:00:00Z',
    });
    addItemMock.mockImplementation((_projectId, payload) =>
      Promise.resolve({
        id: payload.material_id === 'mat-1' ? 'item-1' : 'item-2',
        project_id: 'proj-1',
        material_id: payload.material_id,
        quantity: payload.quantity,
      }),
    );

    renderPage();

    const materialInputs = screen.getAllByPlaceholderText('Название или артикул…');
    const qtyInputs = screen.getAllByPlaceholderText('0');

    // Row 1: pick a material and set quantity — this schedules row 1's save.
    await user.type(materialInputs[0], 'сетка');
    const optionOne = await screen.findByText(material.canonical_name);
    await user.click(optionOne);
    await user.type(qtyInputs[0], '5');

    // Before row 1's debounce fires, edit row 2 too — a single shared debounce
    // timer would cancel row 1's pending save at this point.
    await user.type(materialInputs[1], 'rivet');
    const optionTwo = await screen.findByText(materialTwo.canonical_name);
    await user.click(optionTwo);
    await user.type(qtyInputs[1], '3');

    await waitFor(() => expect(addItemMock).toHaveBeenCalledTimes(2), { timeout: 2000 });
    expect(addItemMock).toHaveBeenCalledWith('proj-1', { material_id: 'mat-1', quantity: 5 });
    expect(addItemMock).toHaveBeenCalledWith('proj-1', { material_id: 'mat-2', quantity: 3 });
  });
});
