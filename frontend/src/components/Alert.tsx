import type { ReactNode } from 'react';
import styles from './Alert.module.css';

type Variant = 'success' | 'warning' | 'danger' | 'info';

interface AlertProps {
  variant: Variant;
  title?: ReactNode;
  children: ReactNode;
  /** Button(s) rendered on the right — e.g. Button variant="secondary"/"danger". */
  action?: ReactNode;
  /** Smaller padding, no icon — for a one-line notice inside a card
   * (e.g. below a section header), not a page-level block. */
  compact?: boolean;
}

const VARIANT_CLASS: Record<Variant, string> = {
  success: styles.success,
  warning: styles.warning,
  danger: styles.danger,
  info: styles.info,
};

const VARIANT_ICON: Record<Variant, string> = {
  success: '✓',
  warning: '',
  danger: '!',
  info: '',
};

export function Alert({ variant, title, children, action, compact = false }: AlertProps) {
  const classes = [styles.alert, VARIANT_CLASS[variant], compact ? styles.compact : '']
    .filter(Boolean)
    .join(' ');
  const icon = VARIANT_ICON[variant];

  return (
    <div className={classes} role="alert">
      {!compact && icon && <span className={styles.icon}>{icon}</span>}
      {!compact && !icon && <span className={styles.dot} />}
      {compact && <span className={styles.dot} />}
      <div className={styles.body}>
        {title && <div className={styles.title}>{title}</div>}
        <div className={styles.text}>{children}</div>
      </div>
      {action && <div className={styles.action}>{action}</div>}
    </div>
  );
}
