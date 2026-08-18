import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { materialsApi } from '../api/materials';
import { ordersApi } from '../api/orders';
import { suppliersApi } from '../api/suppliers';
import type { Material, Order, Supplier } from '../api/types';
import { ErrorBanner } from '../components/ErrorBanner';
import styles from './order-print/OrderPrint.module.css';

interface LoadedData {
  order: Order;
  materials: Material[];
  supplier: Supplier | undefined;
}

/**
 * Document sent to the supplier — separate route from OrderDetailPage
 * (ADR-0007 п.6): different reader (supplier, not staff), different moment
 * in the Order lifecycle (generated at creation, not during reconciliation).
 * Shows quoted_price only — confirmed_price/price_delta don't exist yet at
 * this point and are internal to reconciliation regardless.
 */
export function OrderPrintPage() {
  const { orderId } = useParams<{ orderId: string }>();
  const [data, setData] = useState<LoadedData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);

  useEffect(() => {
    if (!orderId) return;
    let cancelled = false;

    setLoading(true);
    setLoadError(null);
    Promise.all([ordersApi.get(orderId), materialsApi.list(), suppliersApi.list()])
      .then(([order, materials, suppliers]) => {
        if (cancelled) return;
        setData({ order, materials, supplier: suppliers.find((s) => s.id === order.supplier_id) });
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

  const { order, materials, supplier } = data;
  const materialById = new Map(materials.map((m) => [m.id, m]));
  const goodsTotal = order.total_amount;
  const grandTotal = goodsTotal + order.delivery_fee;

  return (
    <div className={styles.page}>
      <div className={styles.sheet}>
        <div className={styles.header}>
          <div className={styles.brand}>SCREEN FACTORY FLORIDA</div>
          <div className={styles.orderMeta}>Заказ №{order.id.slice(0, 8)}</div>
        </div>

        <div className={styles.supplierBlock}>
          <div className={styles.supplierLabel}>Поставщику</div>
          <div className={styles.supplierName}>{supplier?.name ?? order.supplier_id}</div>
          {supplier?.contacts && <div className={styles.supplierContacts}>{supplier.contacts}</div>}
        </div>

        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.materialColHeader}>Материал</th>
              <th className={styles.numCell}>Кол-во</th>
              <th className={styles.numCell}>Цена за ед.</th>
              <th className={styles.numCell}>Сумма</th>
            </tr>
          </thead>
          <tbody>
            {order.items.map((item) => {
              const material = materialById.get(item.material_id);
              return (
                <tr key={item.id}>
                  <td className={styles.materialColCell}>
                    {material?.canonical_name ?? item.material_id}
                  </td>
                  <td className={styles.numCell}>
                    {item.quantity} {material?.unit ?? ''}
                  </td>
                  <td className={styles.numCell}>{formatMoney(item.quoted_price)}</td>
                  <td className={styles.numCell}>{formatMoney(item.quoted_price * item.quantity)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>

        <div className={styles.totals}>
          <div className={styles.totalsRow}>
            <span>Товары</span>
            <span>{formatMoney(goodsTotal)}</span>
          </div>
          <div className={styles.totalsRow}>
            <span>Доставка</span>
            <span>{formatMoney(order.delivery_fee)}</span>
          </div>
          <div className={styles.totalsRowGrand}>
            <span>Итого</span>
            <span>{formatMoney(grandTotal)}</span>
          </div>
        </div>

        <button type="button" className={styles.printButton} onClick={() => window.print()}>
          Печать / Сохранить как PDF
        </button>
      </div>
    </div>
  );
}

function formatMoney(value: number): string {
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
