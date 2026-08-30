import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { suppliersApi } from '../api/suppliers';
import type { Supplier, SupplierCreate } from '../api/types';
import { useCurrentUser } from '../auth/AuthContext';
import { Button } from '../components/Button';
import { ConfirmButton } from '../components/ConfirmButton';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import { SupplierForm } from './suppliers/SupplierForm';
import { summarizeDeliveryPolicy } from './suppliers/deliveryPolicySummary';
import styles from '../components/CrudScreen.module.css';

type Status = 'loading' | 'ready' | 'error';

export function SuppliersPage() {
  const navigate = useNavigate();
  /* UI convenience only, not a security boundary — real enforcement is
     require_role("admin") on the backend router (ADR-0024 §4/§5). */
  const isAdmin = useCurrentUser().role === 'admin';
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [status, setStatus] = useState<Status>('loading');
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [formOpen, setFormOpen] = useState(false);

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
    setActionError(null);
    setFormOpen(true);
  }

  function closeForm() {
    setFormOpen(false);
  }

  async function handleSubmit(payload: Required<SupplierCreate>) {
    setActionError(null);
    try {
      await suppliersApi.create(payload);
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
            <Button variant="primary" disabled={!isAdmin} onClick={openCreate}>
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
                <div className={styles.sectionTitle}>Новый поставщик</div>
              </div>
              <SupplierForm onCancel={closeForm} onSubmit={handleSubmit} />
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
                  <Button variant="primary" disabled={!isAdmin} onClick={openCreate}>
                    Добавить поставщика »
                  </Button>
                }
              />
            )}

            {status === 'ready' && suppliers.length > 0 && (
              <div className={styles.tableScroll}>
                <table className={`${styles.table} ${styles.rowClickable}`}>
                  <thead>
                    <tr>
                      <th>Название</th>
                      <th>Статус</th>
                      <th>Валюта</th>
                      <th>Доставка</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {suppliers.map((supplier) => (
                      <tr key={supplier.id} onClick={() => navigate(`/suppliers/${supplier.id}`)}>
                        <td>{supplier.name}</td>
                        <td>{supplier.status ?? <span className={styles.muted}>—</span>}</td>
                        <td>{supplier.currency}</td>
                        <td>{summarizeDeliveryPolicy(supplier.delivery_policy)}</td>
                        <td onClick={(e) => e.stopPropagation()}>
                          <div className={styles.actionsCell}>
                            <ConfirmButton
                              label="Удалить"
                              disabled={!isAdmin}
                              onConfirm={() => handleDelete(supplier)}
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
