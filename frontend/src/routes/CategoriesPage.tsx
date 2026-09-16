import { useEffect, useState } from 'react';
import { categoriesApi } from '../api/categories';
import type { Category, CategoryCreate } from '../api/types';
import { useCurrentUser } from '../auth/AuthContext';
import { Button } from '../components/Button';
import { ConfirmButton } from '../components/ConfirmButton';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import { CategoryForm } from './categories/CategoryForm';
import styles from '../components/CrudScreen.module.css';

type Status = 'loading' | 'ready' | 'error';

export function CategoriesPage() {
  /* UI convenience only, not a security boundary — real enforcement is
     require_role("admin") on the backend router (ADR-0024 §4/§5). */
  const isAdmin = useCurrentUser().role === 'admin';
  const [categories, setCategories] = useState<Category[]>([]);
  const [status, setStatus] = useState<Status>('loading');
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Category | null>(null);

  useEffect(() => {
    void load();
  }, []);

  async function load() {
    setStatus('loading');
    setLoadError(null);
    try {
      const data = await categoriesApi.list();
      setCategories(data);
      setStatus('ready');
    } catch (err) {
      setLoadError(err);
      setStatus('error');
    }
  }

  function openCreate() {
    setEditing(null);
    setActionError(null);
    setFormOpen(true);
  }

  function openEdit(category: Category) {
    setEditing(category);
    setActionError(null);
    setFormOpen(true);
  }

  function closeForm() {
    setFormOpen(false);
    setEditing(null);
  }

  async function handleSubmit(payload: Required<CategoryCreate>) {
    setActionError(null);
    try {
      if (editing) {
        await categoriesApi.update(editing.id, { name: payload.name });
      } else {
        await categoriesApi.create(payload);
      }
      closeForm();
      await load();
    } catch (err) {
      setActionError(err);
      throw err;
    }
  }

  async function handleToggleRequiresSingleSupplier(category: Category) {
    setActionError(null);
    try {
      await categoriesApi.update(category.id, {
        requires_single_supplier: !category.requires_single_supplier,
      });
      await load();
    } catch (err) {
      setActionError(err);
    }
  }

  async function handleDelete(category: Category) {
    setActionError(null);
    try {
      await categoriesApi.remove(category.id);
      await load();
    } catch (err) {
      setActionError(err);
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <div className={styles.header}>
          <h1 className={styles.title}>Категории</h1>
          {!formOpen && (
            <Button variant="primary" disabled={!isAdmin} onClick={openCreate}>
              + Добавить категорию
            </Button>
          )}
        </div>

        <div className={styles.stack}>
          {actionError != null && <ErrorBanner error={actionError} />}

          {formOpen && (
            <div className={styles.card}>
              <div className={styles.sectionHeader}>
                <div className={styles.sectionTitle}>
                  {editing ? `Переименование: ${editing.name}` : 'Новая категория'}
                </div>
              </div>
              <CategoryForm initial={editing ?? undefined} onCancel={closeForm} onSubmit={handleSubmit} />
            </div>
          )}

          <div className={styles.card}>
            {status === 'loading' && <div className={styles.loading}>Загрузка…</div>}

            {status === 'error' && (
              <div className={`${styles.cardPadded} ${styles.stack}`}>
                <ErrorBanner error={loadError} />
                <Button variant="secondary" onClick={() => void load()}>
                  Повторить
                </Button>
              </div>
            )}

            {status === 'ready' && categories.length === 0 && (
              <EmptyState
                title="Категорий пока нет"
                description="Добавьте первую категорию, чтобы можно было заводить материалы."
                action={
                  <Button variant="primary" disabled={!isAdmin} onClick={openCreate}>
                    Добавить категорию »
                  </Button>
                }
              />
            )}

            {status === 'ready' && categories.length > 0 && (
              <div className={styles.tableScroll}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Название</th>
                      <th>sku_prefix</th>
                      <th>Строгая категория</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {categories.map((category) => (
                      <tr key={category.id}>
                        <td>{category.name}</td>
                        <td>{category.sku_prefix}</td>
                        <td>
                          <input
                            type="checkbox"
                            checked={category.requires_single_supplier}
                            disabled={!isAdmin}
                            onChange={() => void handleToggleRequiresSingleSupplier(category)}
                          />
                        </td>
                        <td>
                          <div className={styles.actionsCell}>
                            <Button variant="ghost" disabled={!isAdmin} onClick={() => openEdit(category)}>
                              Переименовать
                            </Button>
                            <ConfirmButton
                              label="Удалить"
                              disabled={!isAdmin}
                              onConfirm={() => handleDelete(category)}
                            />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
