import type { ReactNode } from 'react';
import styles from './Badge.module.css';

type Variant = 'success' | 'warning' | 'danger' | 'accent' | 'neutral';

interface BadgeProps {
  variant: Variant;
  children: ReactNode;
}

const VARIANT_CLASS: Record<Variant, string> = {
  success: styles.success,
  warning: styles.warning,
  danger: styles.danger,
  accent: styles.accent,
  neutral: styles.neutral,
};

export function Badge({ variant, children }: BadgeProps) {
  return <span className={`${styles.badge} ${VARIANT_CLASS[variant]}`}>{children}</span>;
}
