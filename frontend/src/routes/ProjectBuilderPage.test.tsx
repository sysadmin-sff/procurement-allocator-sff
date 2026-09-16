import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProjectBuilderPage } from './ProjectBuilderPage';
import { allocationApi } from '../api/allocation';
import { materialsApi } from '../api/materials';
import { projectsApi } from '../api/projects';
import { templatesApi } from '../api/templates';

vi.mock('../api/materials', () => ({
  materialsApi: {
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

vi.mock('../api/templates', () => ({
  templatesApi: {
    list: vi.fn(),
  },
}));

const materialsListMock = vi.mocked(materialsApi.list);
const createMock = vi.mocked(projectsApi.create);
const updateProjectMock = vi.mocked(projectsApi.updateProject);
const addItemMock = vi.mocked(projectsApi.addItem);
const updateItemMock = vi.mocked(projectsApi.updateItem);
const removeItemMock = vi.mocked(projectsApi.removeItem);
const runAllocationMock = vi.mocked(allocationApi.run);
const templatesListMock = vi.mocked(templatesApi.list);

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
  category_name: 'Сетка',
  unit: 'рулон',
  attributes: {},
};

describe('ProjectBuilderPage', () => {
  beforeEach(() => {
    materialsListMock.mockReset();
    createMock.mockReset();
    updateProjectMock.mockReset();
    addItemMock.mockReset();
    updateItemMock.mockReset();
    removeItemMock.mockReset();
    runAllocationMock.mockReset();
    templatesListMock.mockReset();
    materialsListMock.mockResolvedValue([]);
    templatesListMock.mockResolvedValue([]);
  });

  it('disables "Рассчитать закупку" until a row has both material and quantity', async () => {
    const user = userEvent.setup();
    materialsListMock.mockResolvedValue([material]);

    renderPage();

    const calcButton = screen.getByRole('button', { name: /Рассчитать закупку/ });
    expect(calcButton).toBeDisabled();

    const [materialInput] = screen.getAllByPlaceholderText('Название или артикул…');
    await waitFor(() => expect(materialsListMock).toHaveBeenCalled());
    await user.type(materialInput, 'сетка');

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
    materialsListMock.mockResolvedValue([{ ...material, id: 'mat-1', canonical_name: 'Material One' }]);

    renderPage();
    await waitFor(() => expect(materialsListMock).toHaveBeenCalled());

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
      items: [],
      latest_allocation_run: null,
    });

    renderPage();

    const titleInput = screen.getByLabelText('Название проекта');
    await user.type(titleInput, 'Pool cage');

    expect(createMock).not.toHaveBeenCalled();

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1), { timeout: 2000 });
    expect(createMock).toHaveBeenCalledWith({ title: 'Pool cage', template_id: null });
  });

  it('creates a ProjectItem once a row becomes filled, then updates it instead of re-adding on further quantity changes', async () => {
    const user = userEvent.setup();
    materialsListMock.mockResolvedValue([material]);
    createMock.mockResolvedValue({
      id: 'proj-1',
      title: 'Проект без названия',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-18T00:00:00Z',
      items: [],
      latest_allocation_run: null,
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
    await waitFor(() => expect(materialsListMock).toHaveBeenCalled());

    const [materialInput] = screen.getAllByPlaceholderText('Название или артикул…');
    await user.type(materialInput, 'сетка');
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
    materialsListMock.mockResolvedValue([material]);
    createMock.mockResolvedValue({
      id: 'proj-1',
      title: 'Проект без названия',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-18T00:00:00Z',
      items: [],
      latest_allocation_run: null,
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
      split_categories: [],
    });

    renderPage();
    await waitFor(() => expect(materialsListMock).toHaveBeenCalled());

    const [materialInput] = screen.getAllByPlaceholderText('Название или артикул…');
    await user.type(materialInput, 'сетка');
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
    materialsListMock.mockResolvedValue([material, materialTwo]);
    createMock.mockResolvedValue({
      id: 'proj-1',
      title: 'Проект без названия',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-18T00:00:00Z',
      items: [],
      latest_allocation_run: null,
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
    await waitFor(() => expect(materialsListMock).toHaveBeenCalled());

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

  describe('project templates (ADR-0032 §3)', () => {
    const template = {
      id: 'tmpl-1',
      name: 'Стандартная дверь',
      created_at: '2026-01-01T00:00:00Z',
      items: [
        { id: 'ti-1', material_id: 'mat-1', canonical_name: material.canonical_name, unit: material.unit, category_name: material.category_name },
      ],
    };

    it('creates the project with the selected template_id and populates rows with quantity=1', async () => {
      const user = userEvent.setup();
      templatesListMock.mockResolvedValue([template]);
      materialsListMock.mockResolvedValue([material]);
      createMock.mockResolvedValue({
        id: 'proj-1',
        title: 'Проект без названия',
        created_by: null,
        status: 'draft',
        created_at: '2026-08-18T00:00:00Z',
        items: [{ id: 'item-1', project_id: 'proj-1', material_id: 'mat-1', quantity: 1 }],
        latest_allocation_run: null,
      });

      renderPage();
      await screen.findByLabelText('Шаблон');

      await user.selectOptions(screen.getByLabelText('Шаблон'), 'tmpl-1');

      const titleInput = screen.getByLabelText('Название проекта');
      await user.type(titleInput, 'Pool cage');

      await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1), { timeout: 2000 });
      expect(createMock).toHaveBeenCalledWith({ title: 'Pool cage', template_id: 'tmpl-1' });

      const qtyInputs = await screen.findAllByPlaceholderText('0');
      expect((qtyInputs[0] as HTMLInputElement).value).toBe('1');
      const materialInputs = screen.getAllByPlaceholderText('Название или артикул…');
      expect((materialInputs[0] as HTMLInputElement).value).toBe(material.canonical_name);
    });

    it('the template selector disappears once the project is created', async () => {
      const user = userEvent.setup();
      templatesListMock.mockResolvedValue([template]);
      createMock.mockResolvedValue({
        id: 'proj-1',
        title: 'Pool cage',
        created_by: null,
        status: 'draft',
        created_at: '2026-08-18T00:00:00Z',
        items: [],
        latest_allocation_run: null,
      });

      renderPage();
      await screen.findByLabelText('Шаблон');

      const titleInput = screen.getByLabelText('Название проекта');
      await user.type(titleInput, 'Pool cage');

      await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1), { timeout: 2000 });
      await waitFor(() => expect(screen.queryByLabelText('Шаблон')).not.toBeInTheDocument());
    });

    it('"без шаблона" (no selection) behaves exactly like current empty-project behavior', async () => {
      const user = userEvent.setup();
      templatesListMock.mockResolvedValue([template]);
      createMock.mockResolvedValue({
        id: 'proj-1',
        title: 'Pool cage',
        created_by: null,
        status: 'draft',
        created_at: '2026-08-18T00:00:00Z',
        items: [],
        latest_allocation_run: null,
      });

      renderPage();
      await screen.findByLabelText('Шаблон');

      const titleInput = screen.getByLabelText('Название проекта');
      await user.type(titleInput, 'Pool cage');

      await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1), { timeout: 2000 });
      expect(createMock).toHaveBeenCalledWith({ title: 'Pool cage', template_id: null });
      // Still just the two originally-empty rows — nothing was inserted from a template.
      expect(screen.getAllByPlaceholderText('Название или артикул…')).toHaveLength(2);
    });

    it('rows populated from a template are fully editable and removable like manually added rows', async () => {
      const user = userEvent.setup();
      templatesListMock.mockResolvedValue([template]);
      materialsListMock.mockResolvedValue([material]);
      createMock.mockResolvedValue({
        id: 'proj-1',
        title: 'Проект без названия',
        created_by: null,
        status: 'draft',
        created_at: '2026-08-18T00:00:00Z',
        items: [{ id: 'item-1', project_id: 'proj-1', material_id: 'mat-1', quantity: 1 }],
        latest_allocation_run: null,
      });
      updateItemMock.mockResolvedValue({
        id: 'item-1',
        project_id: 'proj-1',
        material_id: 'mat-1',
        quantity: 4,
      });
      removeItemMock.mockResolvedValue(undefined);

      renderPage();
      await screen.findByLabelText('Шаблон');
      await user.selectOptions(screen.getByLabelText('Шаблон'), 'tmpl-1');

      const titleInput = screen.getByLabelText('Название проекта');
      await user.type(titleInput, 'Pool cage');

      // Wait for the template-derived row to actually appear (material populated)
      // before touching its quantity — findAllByPlaceholderText('0') alone would
      // resolve against the still-empty starter rows.
      await waitFor(() => {
        const materialInputs = screen.getAllByPlaceholderText('Название или артикул…') as HTMLInputElement[];
        expect(materialInputs.some((el) => el.value === material.canonical_name)).toBe(true);
      });

      const qtyInputs = screen.getAllByPlaceholderText('0');
      await user.type(qtyInputs[0], '{Backspace}4');
      await waitFor(() => expect(updateItemMock).toHaveBeenCalledWith('proj-1', 'item-1', 4), {
        timeout: 2000,
      });

      const removeButtons = screen.getAllByTitle('Удалить строку');
      await user.click(removeButtons[0]);
      await waitFor(() => expect(removeItemMock).toHaveBeenCalledWith('proj-1', 'item-1'));
    });
  });
});
