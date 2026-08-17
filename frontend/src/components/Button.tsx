import type { ButtonHTMLAttributes } from 'react';
import styles from './Button.module.css';

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

const VARIANT_CLASS: Record<Variant, string> = {
  primary: styles.primary,
  secondary: styles.secondary,
  danger: styles.danger,
  ghost: styles.ghost,
};

export function Button({ variant = 'secondary', className, ...rest }: ButtonProps) {
  const classes = [styles.button, VARIANT_CLASS[variant], className].filter(Boolean).join(' ');
  return <button className={classes} {...rest} />;
}
