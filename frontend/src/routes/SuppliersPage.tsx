import { useEffect, useState } from 'react';
import { suppliersApi } from '../api/suppliers';
import type { Supplier, SupplierCreate } from '../api/types';
import { Button } from '../components/Button';
import { ConfirmButton } from '../components/ConfirmButton';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import { SupplierForm } from './suppliers/SupplierForm';
import { summarizeDeliveryPolicy } from './suppliers/deliveryPolicySummary';
import styles from '../components/CrudScreen.module.css';

type Status = 'loading' | 'ready' | 'error';

export function SuppliersPage() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [status, setStatus] = useState<Status>('loading');
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Supplier | null>(null);

  useEffect(() => {
    void load();
  }, []);

  async function load() {
    setStatus('loading');
    setLoadError(null);
    try {
      const data = await suppliersApi.list();
      setSuppliers(data);
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

  function openEdit(supplier: Supplier) {
    setEditing(supplier);
    setActionError(null);
    setFormOpen(true);
  }

  function closeForm() {
    setFormOpen(false);
    setEditing(null);
  }

  async function handleSubmit(payload: Required<SupplierCreate>) {
    setActionError(null);
    try {
      if (editing) {
        const after: Supplier = { ...editing, ...payload };
        await suppliersApi.update(editing.id, editing, after);
      } else {
        await suppliersApi.create(payload);
      }
      closeForm();
      await load();
    } catch (err) {
      setActionError(err);
      throw err;
    }
  }

  async function handleDelete(supplier: Supplier) {
    setActionError(null);
    try {
      await suppliersApi.remove(supplier.id);
      await load();
    } catch (err) {
      setActionError(err);
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <div className={styles.header}>
          <h1 className={styles.title}>Поставщики</h1>
          {!formOpen && (
            <Button variant="primary" onClick={openCreate}>
              + Добавить поставщика
            </Button>
          )}
        </div>

        <div className={styles.stack}>
          {actionError != null && (
            <ErrorBanner
              error={actionError}
              conflictMessage="Поставщик используется в других данных (цены, ордера) — удаление невозможно."
            />
          )}

          {formOpen && (
            <div className={styles.card}>
              <div className={styles.sectionHeader}>
                <div className={styles.sectionTitle}>
                  {editing ? `Редактирование: ${editing.name}` : 'Новый поставщик'}
                </div>
              </div>
              <SupplierForm initial={editing ?? undefined} onCancel={closeForm} onSubmit={handleSubmit} />
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

            {status === 'ready' && suppliers.length === 0 && (
              <EmptyState
                title="Поставщиков пока нет"
                description="Добавьте первого поставщика, чтобы начать заносить цены и распределять закупки."
                action={
                  <Button variant="primary" onClick={openCreate}>
                    Добавить поставщика »
                  </Button>
                }
              />
            )}

            {status === 'ready' && suppliers.length > 0 && (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Название</th>
                    <th>Валюта</th>
                    <th>Доставка</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {suppliers.map((supplier) => (
                    <tr key={supplier.id}>
                      <td>{supplier.name}</td>
                      <td>{supplier.currency}</td>
                      <td>{summarizeDeliveryPolicy(supplier.delivery_policy)}</td>
                      <td>
                        <div className={styles.actionsCell}>
                          <Button variant="ghost" onClick={() => openEdit(supplier)}>
                            Изменить
                          </Button>
                          <ConfirmButton label="Удалить" onConfirm={() => handleDelete(supplier)} />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
