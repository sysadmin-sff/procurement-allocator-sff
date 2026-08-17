import { useState } from 'react';
import { Button } from './Button';
import styles from './ConfirmButton.module.css';

interface ConfirmButtonProps {
  label: string;
  confirmLabel?: string;
  onConfirm: () => void;
  disabled?: boolean;
}

export function ConfirmButton({
  label,
  confirmLabel = 'Точно удалить?',
  onConfirm,
  disabled,
}: ConfirmButtonProps) {
  const [confirming, setConfirming] = useState(false);

  if (!confirming) {
    return (
      <Button variant="ghost" disabled={disabled} onClick={() => setConfirming(true)}>
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
      <Button variant="ghost" onClick={() => setConfirming(false)}>
        Отмена
      </Button>
    </span>
  );
}
