import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProjectTemplatesPage } from './ProjectTemplatesPage';
import { templatesApi } from '../api/templates';
import { materialsApi } from '../api/materials';
import { ApiError } from '../api/client';
import { AuthContext } from '../auth/AuthContext';
import type { CurrentUser, ProjectTemplate } from '../api/types';

vi.mock('../api/templates', () => ({
  templatesApi: {
    list: vi.fn(),
    create: vi.fn(),
    rename: vi.fn(),
    remove: vi.fn(),
    addItem: vi.fn(),
    removeItem: vi.fn(),
  },
}));

vi.mock('../api/materials', () => ({
  materialsApi: { list: vi.fn() },
}));

const listMock = vi.mocked(templatesApi.list);
const createMock = vi.mocked(templatesApi.create);
const renameMock = vi.mocked(templatesApi.rename);
const removeMock = vi.mocked(templatesApi.remove);
const addItemMock = vi.mocked(templatesApi.addItem);
const removeItemMock = vi.mocked(templatesApi.removeItem);
const materialsListMock = vi.mocked(materialsApi.list);

const material = {
  id: 'mat-1',
  internal_sku: 'DOOR-STD',
  canonical_name: 'Дверная ручка',
  category_name: 'Двери',
  unit: 'шт',
  attributes: {},
};

const emptyTemplate: ProjectTemplate = {
  id: 't1',
  name: 'Стандартная дверь',
  created_at: '2026-01-10T12:00:00Z',
  items: [],
};

function renderAs(role: CurrentUser['role']) {
  return render(
    <MemoryRouter>
      <AuthContext.Provider value={{ id: 'u1', email: 'a@b.com', name: 'A', role }}>
        <ProjectTemplatesPage />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}

describe('ProjectTemplatesPage', () => {
  beforeEach(() => {
    listMock.mockReset();
    createMock.mockReset();
    renameMock.mockReset();
    removeMock.mockReset();
    addItemMock.mockReset();
    removeItemMock.mockReset();
    materialsListMock.mockReset();
    materialsListMock.mockResolvedValue([material]);
  });

  it('runs the full CRUD cycle: create, add material, rename, remove material, delete', async () => {
    const user = userEvent.setup();
    listMock.mockResolvedValueOnce([]);
    createMock.mockResolvedValue(emptyTemplate);
    listMock.mockResolvedValueOnce([emptyTemplate]);

    renderAs('admin');

    await screen.findByText('Шаблонов пока нет');

    // Create
    await user.click(screen.getByRole('button', { name: '+ Создать шаблон' }));
    await user.type(screen.getByLabelText(/название шаблона/i), 'Стандартная дверь');
    await user.click(screen.getByRole('button', { name: /^создать шаблон$/i }));

    expect(createMock).toHaveBeenCalledWith({ name: 'Стандартная дверь' });
    await screen.findByText('Стандартная дверь');

    // Add a material
    const withItem: ProjectTemplate = {
      ...emptyTemplate,
      items: [{ id: 'item-1', material_id: 'mat-1', canonical_name: material.canonical_name, unit: 'шт', category_name: 'Двери' }],
    };
    addItemMock.mockResolvedValue(withItem);

    await user.click(screen.getByText('Стандартная дверь'));
    await waitFor(() => expect(materialsListMock).toHaveBeenCalled());

    const comboInput = screen.getByPlaceholderText('Название или артикул…');
    await user.type(comboInput, 'ручка');
    const option = await screen.findByText(material.canonical_name);
    await user.click(option);
    await user.click(screen.getByRole('button', { name: /^добавить$/i }));

    await waitFor(() => expect(addItemMock).toHaveBeenCalledWith('t1', 'mat-1'));
    expect(await screen.findByText('1 материал')).toBeInTheDocument();

    // Rename
    renameMock.mockResolvedValue({ ...withItem, name: 'Стандартное патио' });
    listMock.mockResolvedValueOnce([{ ...withItem, name: 'Стандартное патио' }]);

    await user.click(screen.getByRole('button', { name: /переименовать/i }));
    const renameInput = screen.getByLabelText(/название шаблона/i);
    await user.clear(renameInput);
    await user.type(renameInput, 'Стандартное патио');
    await user.click(screen.getByRole('button', { name: /^сохранить$/i }));

    expect(renameMock).toHaveBeenCalledWith('t1', 'Стандартное патио');
    await screen.findByText('Стандартное патио');

    // Remove the material (panel is already expanded from the add-item step)
    removeItemMock.mockResolvedValue(emptyTemplate);
    await user.click(screen.getByRole('button', { name: /убрать/i }));
    expect(removeItemMock).toHaveBeenCalledWith('t1', 'item-1');

    // Delete the template
    removeMock.mockResolvedValue(undefined);
    listMock.mockResolvedValueOnce([]);
    await user.click(screen.getByRole('button', { name: /^удалить$/i }));
    await user.click(screen.getByRole('button', { name: /^да$/i }));

    expect(removeMock).toHaveBeenCalledWith('t1');
    await screen.findByText('Шаблонов пока нет');
  });

  it('disables create/rename/delete/material actions for employee role', async () => {
    listMock.mockResolvedValue([emptyTemplate]);
    renderAs('employee');

    await screen.findByText('Стандартная дверь');
    expect(screen.getByRole('button', { name: /создать шаблон/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /переименовать/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /^удалить$/i })).toBeDisabled();
  });

  it('shows an insufficient-permissions message on 403 instead of crashing', async () => {
    listMock.mockRejectedValue(new ApiError(403, { detail: 'Forbidden' }));
    renderAs('employee');

    expect(await screen.findByText('Недостаточно прав')).toBeInTheDocument();
  });

  // ADR-0038: the error banner's conflictMessage ("Шаблон с таким названием
  // уже существует.") must only appear for create/rename 409s — addItem's
  // 409 (or any future one) shows the backend's own error.detail instead.
  it('shows error.detail (not the template-name conflict text) on a 409 from addItem', async () => {
    const user = userEvent.setup();
    listMock.mockResolvedValue([emptyTemplate]);
    addItemMock.mockRejectedValue(new ApiError(409, { detail: 'Material already in this template' }));

    renderAs('admin');

    await user.click(await screen.findByText('Стандартная дверь'));
    await waitFor(() => expect(materialsListMock).toHaveBeenCalled());

    const comboInput = screen.getByPlaceholderText('Название или артикул…');
    await user.type(comboInput, 'ручка');
    const option = await screen.findByText(material.canonical_name);
    await user.click(option);
    await user.click(screen.getByRole('button', { name: /^добавить$/i }));

    expect(await screen.findByText('Material already in this template')).toBeInTheDocument();
    expect(screen.queryByText('Шаблон с таким названием уже существует.')).not.toBeInTheDocument();
  });

  it('still shows the template-name conflict text on a 409 from create', async () => {
    const user = userEvent.setup();
    listMock.mockResolvedValue([]);
    createMock.mockRejectedValue(
      new ApiError(409, { detail: 'Project template with this name already exists' }),
    );

    renderAs('admin');

    await screen.findByText('Шаблонов пока нет');
    await user.click(screen.getByRole('button', { name: '+ Создать шаблон' }));
    await user.type(screen.getByLabelText(/название шаблона/i), 'Стандартная дверь');
    await user.click(screen.getByRole('button', { name: /^создать шаблон$/i }));

    expect(
      await screen.findByText('Шаблон с таким названием уже существует.'),
    ).toBeInTheDocument();
  });
});
