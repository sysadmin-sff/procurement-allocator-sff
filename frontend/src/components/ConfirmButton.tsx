import { useState } from 'react';
import { Button } from './Button';
import styles from './ConfirmButton.module.css';

interface ConfirmButtonProps {
  label: string;
  confirmLabel?: string;
  onConfirm: () => void;
  disabled?: boolean;
  /** Notified when the confirm prompt opens/closes — lets a cramped layout
   * (e.g. a fixed-width table cell) hide sibling controls while it's shown,
   * instead of squeezing everything onto one line. */
  onConfirmingChange?: (confirming: boolean) => void;
}

export function ConfirmButton({
  label,
  confirmLabel = 'Точно удалить?',
  onConfirm,
  disabled,
  onConfirmingChange,
}: ConfirmButtonProps) {
  const [confirming, setConfirming] = useState(false);

  function setConfirmingAndNotify(value: boolean) {
    setConfirming(value);
    onConfirmingChange?.(value);
  }

  if (!confirming) {
    return (
      <Button variant="ghost" disabled={disabled} onClick={() => setConfirmingAndNotify(true)}>
        {label}
      </Button>
    );
  }

  return (
    <span className={styles.confirmGroup}>
      <span className={styles.confirmLabel}>{confirmLabel}</span>
      <Button variant="danger" onClick={onConfirm}>
        Да
      </Button>
      <Button variant="ghost" onClick={() => setConfirmingAndNotify(false)}>
        Отмена
      </Button>
    </span>
  );
}
