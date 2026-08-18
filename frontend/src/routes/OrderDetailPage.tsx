import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { materialsApi } from '../api/materials';
import { ordersApi } from '../api/orders';
import { suppliersApi } from '../api/suppliers';
import type { Material, Order, OrderItem, Supplier } from '../api/types';
import { ErrorBanner } from '../components/ErrorBanner';
import styles from './order-detail/OrderDetail.module.css';

const SIGNIFICANT_PRICE_DELTA_PCT = 10;
/** Mirrors app/allocation/order_service.py SIGNIFICANT_PRICE_DELTA_PCT — the
 * server computes price_delta_pct, this only decides the highlight threshold
 * for display. See ADR-0007 п.4. */

interface LoadedData {
  order: Order;
  materials: Material[];
  suppliers: Supplier[];
}

export function OrderDetailPage() {
  const { orderId } = useParams<{ orderId: string }>();
  const [data, setData] = useState<LoadedData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [savingItemId, setSavingItemId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<unknown>(null);

  useEffect(() => {
    if (!orderId) return;
    let cancelled = false;

    setLoading(true);
    setLoadError(null);
    Promise.all([ordersApi.get(orderId), materialsApi.list(), suppliersApi.list()])
      .then(([order, materials, suppliers]) => {
        if (cancelled) return;
        setData({ order, materials, suppliers });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoadError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [orderId]);

  async function handleConfirmedPriceChange(item: OrderItem, value: number | null) {
    if (!data || value === item.confirmed_price) return;
    setSaveError(null);
    setSavingItemId(item.id);
    try {
      const updated = await ordersApi.setConfirmedPrice(data.order.id, item.id, value);
      setData((prev) =>
        prev
          ? {
              ...prev,
              order: {
                ...prev.order,
                items: prev.order.items.map((i) => (i.id === item.id ? updated : i)),
              },
            }
          : prev,
      );
    } catch (err) {
      setSaveError(err);
    } finally {
      setSavingItemId(null);
    }
  }

  if (!orderId) {
    return <ErrorBanner error="Не указан ордер." />;
  }

  if (loading) {
    return <div className={styles.centerWrap}>Загрузка…</div>;
  }

  if (loadError || !data) {
    return (
      <div className={styles.centerWrap}>
        <ErrorBanner error={loadError} />
      </div>
    );
  }

  const { order, materials, suppliers } = data;
  const materialById = new Map(materials.map((m) => [m.id, m]));
  const supplier = suppliers.find((s) => s.id === order.supplier_id);

  const discrepantCount = order.items.filter(
    (item) => item.price_delta_pct != null && Math.abs(item.price_delta_pct) > SIGNIFICANT_PRICE_DELTA_PCT,
  ).length;

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <Link to={`/projects/${order.project_id}`} className={styles.backLink}>
          « Назад к проекту
        </Link>

        <div className={styles.header}>
          <h1 className={styles.title}>{supplier?.name ?? order.supplier_id}</h1>
          <Link to={`/orders/${order.id}/print`} className={styles.printLink}>
            Печатная версия »
          </Link>
        </div>

        {saveError != null && <ErrorBanner error={saveError} />}

        {discrepantCount > 0 && (
          <div className={styles.discrepancyBanner} role="alert">
            ⚠ {discrepantCount} {pluralizePositions(discrepantCount)} с расхождением цены больше{' '}
            {SIGNIFICANT_PRICE_DELTA_PCT}%
          </div>
        )}

        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.materialColHeader}>Материал</th>
              <th className={styles.numCell}>Кол-во</th>
              <th className={styles.numCell}>Отправленная цена</th>
              <th className={styles.numCell}>Подтверждённая цена</th>
              <th className={styles.numCell}>Расхождение</th>
            </tr>
          </thead>
          <tbody>
            {order.items.map((item) => (
              <OrderItemRow
                key={item.id}
                item={item}
                material={materialById.get(item.material_id)}
                saving={savingItemId === item.id}
                onConfirmedPriceChange={(value) => void handleConfirmedPriceChange(item, value)}
              />
            ))}
          </tbody>
        </table>

        <div className={styles.footer}>
          <span className={styles.footerTotal}>
            Товары: {formatMoney(order.total_amount)} + доставка {formatMoney(order.delivery_fee)}
          </span>
        </div>
      </div>
    </div>
  );
}

function OrderItemRow({
  item,
  material,
  saving,
  onConfirmedPriceChange,
}: {
  item: OrderItem;
  material: Material | undefined;
  saving: boolean;
  onConfirmedPriceChange: (value: number | null) => void;
}) {
  const isDiscrepant =
    item.price_delta_pct != null && Math.abs(item.price_delta_pct) > SIGNIFICANT_PRICE_DELTA_PCT;

  return (
    <tr className={isDiscrepant ? styles.discrepantRow : undefined}>
      <td className={styles.materialColCell}>{material?.canonical_name ?? item.material_id}</td>
      <td className={styles.numCell}>
        {item.quantity} {material?.unit ?? ''}
      </td>
      <td className={styles.numCell}>{formatMoney(item.quoted_price)}</td>
      <td className={styles.numCell}>
        <input
          key={item.confirmed_price ?? 'empty'}
          className={styles.priceInput}
          type="number"
          min="0"
          step="0.01"
          placeholder="—"
          defaultValue={item.confirmed_price ?? ''}
          disabled={saving}
          onBlur={(e) => {
            const raw = e.target.value.trim();
            onConfirmedPriceChange(raw === '' ? null : Number(raw));
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') e.currentTarget.blur();
          }}
        />
      </td>
      <td className={styles.numCell}>
        {item.price_delta != null && item.price_delta_pct != null ? (
          <span className={isDiscrepant ? styles.deltaDiscrepant : styles.delta}>
            {item.price_delta >= 0 ? '+' : ''}
            {formatMoney(item.price_delta)} ({item.price_delta_pct >= 0 ? '+' : ''}
            {item.price_delta_pct.toFixed(1)}%)
          </span>
        ) : (
          <span className={styles.deltaEmpty}>—</span>
        )}
      </td>
    </tr>
  );
}

function formatMoney(value: number): string {
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pluralizePositions(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return 'позиция';
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'позиции';
  return 'позиций';
}
