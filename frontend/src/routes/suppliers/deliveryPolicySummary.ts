import type { DeliveryPolicy } from '../../api/types';

const money = (value: number) => `$${value.toFixed(2)}`;

/**
 * `free_shipping_threshold === null` ("не задан") and `=== 0` ("порог $0,
 * т.е. всегда бесплатно") are different business states per ADR-0002 and
 * must never collapse into the same summary text.
 */
export function summarizeDeliveryPolicy(policy: DeliveryPolicy): string {
  const parts = [`flat ${money(policy.flat_fee)}`];

  parts.push(
    policy.free_shipping_threshold === null
      ? 'порог не задан'
      : `порог ${money(policy.free_shipping_threshold)}`,
  );

  if (policy.per_order_min_amount > 0) {
    parts.push(`мин. заказ ${money(policy.per_order_min_amount)}`);
  }

  return parts.join(', ');
}
