import { Fragment, useEffect, useState } from 'react';
import { materialsApi } from '../api/materials';
import { suppliersApi } from '../api/suppliers';
import type { Material, MaterialCreate, Supplier } from '../api/types';
import { Button } from '../components/Button';
import { ConfirmButton } from '../components/ConfirmButton';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import { MaterialForm } from './materials/MaterialForm';
import { MaterialPricesPanel } from './materials/MaterialPricesPanel';
import styles from '../components/CrudScreen.module.css';

type Status = 'loading' | 'ready' | 'error';

export function MaterialsPage() {
  const [materials, setMaterials] = useState<Material[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [status, setStatus] = useState<Status>('loading');
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Material | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    void load();
  }, []);

  async function load() {
    setStatus('loading');
    setLoadError(null);
    try {
      const [materialsData, suppliersData] = await Promise.all([
        materialsApi.list(),
        suppliersApi.list(),
      ]);
      setMaterials(materialsData);
      setSuppliers(suppliersData);
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

  function openEdit(material: Material) {
    setEditing(material);
    setActionError(null);
    setFormOpen(true);
  }

  function closeForm() {
    setFormOpen(false);
    setEditing(null);
  }

  async function handleSubmit(payload: MaterialCreate) {
    setActionError(null);
    try {
      if (editing) {
        const after: Material = { ...editing, ...payload, attributes: payload.attributes ?? {} };
        await materialsApi.update(editing.id, editing, after);
      } else {
        await materialsApi.create(payload);
      }
      closeForm();
      await load();
    } catch (err) {
      setActionError(err);
      throw err;
    }
  }

  async function handleDelete(material: Material) {
    setActionError(null);
    try {
      await materialsApi.remove(material.id);
      if (expandedId === material.id) setExpandedId(null);
      await load();
    } catch (err) {
      setActionError(err);
    }
  }

  function toggleExpanded(materialId: string) {
    setExpandedId((current) => (current === materialId ? null : materialId));
  }

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <div className={styles.header}>
          <h1 className={styles.title}>Материалы</h1>
          {!formOpen && (
            <Button variant="primary" onClick={openCreate}>
              + Добавить материал
            </Button>
          )}
        </div>

        <div className={styles.stack}>
          {actionError != null && (
            <ErrorBanner
              error={actionError}
              conflictMessage="Материал используется в других данных (цены, позиции проектов) — удаление невозможно."
            />
          )}

          {formOpen && (
            <div className={styles.card}>
              <div className={styles.sectionHeader}>
                <div className={styles.sectionTitle}>
                  {editing ? `Редактирование: ${editing.canonical_name}` : 'Новый материал'}
                </div>
              </div>
              <MaterialForm initial={editing ?? undefined} onCancel={closeForm} onSubmit={handleSubmit} />
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

            {status === 'ready' && materials.length === 0 && (
              <EmptyState
                title="Материалов пока нет"
                description="Добавьте первый материал в каталог, чтобы можно было заносить цены и включать его в проекты."
                action={
                  <Button variant="primary" onClick={openCreate}>
                    Добавить материал »
                  </Button>
                }
              />
            )}

            {status === 'ready' && materials.length > 0 && (
              <table className={`${styles.table} ${styles.rowClickable}`}>
                <thead>
                  <tr>
                    <th className={styles.expandHeaderCell}></th>
                    <th>internal_sku</th>
                    <th>Название</th>
                    <th>Категория</th>
                    <th>Ед.</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {materials.map((material) => {
                    const expanded = expandedId === material.id;
                    return (
                      <Fragment key={material.id}>
                        <tr onClick={() => toggleExpanded(material.id)}>
                          <td className={styles.expandCell}>
                            <span
                              className={`${styles.chevron} ${expanded ? styles.chevronExpanded : ''}`}
                              aria-hidden="true"
                            >
                              ▸
                            </span>
                          </td>
                          <td>{material.internal_sku}</td>
                          <td>{material.canonical_name}</td>
                          <td>{material.category ?? <span className={styles.muted}>—</span>}</td>
                          <td>{material.unit}</td>
                          <td>
                            <div
                              className={styles.actionsCell}
                              onClick={(e) => e.stopPropagation()}
                            >
                              <Button variant="ghost" onClick={() => openEdit(material)}>
                                Изменить
                              </Button>
                              <ConfirmButton label="Удалить" onConfirm={() => handleDelete(material)} />
                            </div>
                          </td>
                        </tr>
                        {expanded && (
                          <tr>
                            <td colSpan={6}>
                              <MaterialPricesPanel materialId={material.id} suppliers={suppliers} />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
