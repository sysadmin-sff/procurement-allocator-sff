import { useCallback, useEffect, useState } from 'react';
import { pricesApi } from '../../api/prices';
import type { Price, PriceCreate, PriceUpdate, Supplier } from '../../api/types';
import { Button } from '../../components/Button';
import { ConfirmButton } from '../../components/ConfirmButton';
import { EmptyState } from '../../components/EmptyState';
import { ErrorBanner } from '../../components/ErrorBanner';
import { PriceForm } from './PriceForm';
import styles from '../../components/CrudScreen.module.css';

type Status = 'loading' | 'ready' | 'error';

interface MaterialPricesPanelProps {
  materialId: string;
  suppliers: Supplier[];
}

const money = (value: number, currency: string) => `${currency} ${value.toFixed(2)}`;

export function MaterialPricesPanel({ materialId, suppliers }: MaterialPricesPanelProps) {
  const [prices, setPrices] = useState<Price[]>([]);
  const [status, setStatus] = useState<Status>('loading');
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Price | null>(null);

  const load = useCallback(async () => {
    setStatus('loading');
    setLoadError(null);
    try {
      const data = await pricesApi.list({ material_id: materialId });
      setPrices(data);
      setStatus('ready');
    } catch (err) {
      setLoadError(err);
      setStatus('error');
    }
  }, [materialId]);

  useEffect(() => {
    void load();
  }, [load]);

  function supplierName(supplierId: string): string {
    return suppliers.find((s) => s.id === supplierId)?.name ?? supplierId;
  }

  function openCreate() {
    setEditing(null);
    setActionError(null);
    setFormOpen(true);
  }

  function openEdit(p: Price) {
    setEditing(p);
    setActionError(null);
    setFormOpen(true);
  }

  function closeForm() {
    setFormOpen(false);
    setEditing(null);
  }

  async function handleCreate(payload: PriceCreate) {
    setActionError(null);
    try {
      await pricesApi.create(payload);
      closeForm();
      await load();
    } catch (err) {
      setActionError(err);
      throw err;
    }
  }

  async function handleUpdate(payload: PriceUpdate) {
    if (!editing) return;
    setActionError(null);
    try {
      // PriceForm always submits every field explicitly (it's a full edit view,
      // not a partial diff), so payload.price/availability/min_order_qty are
      // real values here, never omitted — safe to apply directly onto `after`.
      const after: Price = {
        ...editing,
        price: payload.price as number,
        availability: payload.availability ?? null,
        min_order_qty: payload.min_order_qty ?? null,
        valid_from: payload.valid_from,
      };
      await pricesApi.update(editing.id, editing, after);
      closeForm();
      await load();
    } catch (err) {
      setActionError(err);
      throw err;
    }
  }

  async function handleDelete(p: Price) {
    setActionError(null);
    try {
      await pricesApi.remove(p.id);
      await load();
    } catch (err) {
      setActionError(err);
    }
  }

  if (suppliers.length === 0) {
    return (
      <div className={styles.cardPadded}>
        <div className={styles.fieldHint}>
          Сначала добавьте хотя бы одного поставщика на странице «Поставщики», чтобы можно было
          привязать к нему цену.
        </div>
      </div>
    );
  }

  return (
    <div className={styles.stack}>
      {actionError != null && (
        <ErrorBanner
          error={actionError}
          conflictMessage="Эта цена — историческая (закрытая) запись или используется в других данных: изменить/удалить нельзя."
        />
      )}

      {formOpen && (
        <div className={styles.card}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionTitle}>
              {editing ? `Редактирование цены: ${supplierName(editing.supplier_id)}` : 'Новая цена'}
            </div>
          </div>
          <PriceForm
            materialId={materialId}
            suppliers={suppliers}
            initial={editing ?? undefined}
            onCancel={closeForm}
            onSubmitCreate={editing ? undefined : handleCreate}
            onSubmitUpdate={editing ? handleUpdate : undefined}
          />
        </div>
      )}

      {!formOpen && (
        <div>
          <Button variant="secondary" onClick={openCreate}>
            + Добавить цену
          </Button>
        </div>
      )}

      <div className={styles.card}>
        {status === 'loading' && <div className={styles.loading}>Загрузка цен…</div>}

        {status === 'error' && (
          <div className={`${styles.cardPadded} ${styles.stack}`}>
            <ErrorBanner error={loadError} />
            <Button variant="secondary" onClick={() => void load()}>
              Повторить
            </Button>
          </div>
        )}

        {status === 'ready' && prices.length === 0 && (
          <EmptyState
            title="Цен пока нет"
            description="Добавьте первую цену от поставщика для этого материала."
            action={
              <Button variant="primary" onClick={openCreate}>
                Добавить цену »
              </Button>
            }
          />
        )}

        {status === 'ready' && prices.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Поставщик</th>
                <th>Цена</th>
                <th>Наличие</th>
                <th>Мин. заказ</th>
                <th>Действует с</th>
                <th>Статус</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {prices.map((p) => {
                const isActive = p.valid_to === null;
                return (
                  <tr key={p.id}>
                    <td>{supplierName(p.supplier_id)}</td>
                    <td>{money(p.price, p.currency)}</td>
                    <td>{p.availability ?? <span className={styles.muted}>не ограничено</span>}</td>
                    <td>{p.min_order_qty ?? <span className={styles.muted}>—</span>}</td>
                    <td>{p.valid_from}</td>
                    <td>
                      <span
                        className={`${styles.badge} ${isActive ? styles.badgeActive : styles.badgeHistorical}`}
                      >
                        {isActive ? 'активна' : 'историческая'}
                      </span>
                    </td>
                    <td>
                      {isActive && (
                        <div className={styles.actionsCell}>
                          <Button variant="ghost" onClick={() => openEdit(p)}>
                            Изменить
                          </Button>
                          <ConfirmButton label="Удалить" onConfirm={() => handleDelete(p)} />
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
