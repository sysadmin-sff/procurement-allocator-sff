import { useState } from 'react';
import styles from './Measurements.module.css';

/** An identifier shown as text with a copy button. */
export function CopyableId({ value }: { value: number | string }) {
  const [copied, setCopied] = useState(false);
  const text = String(value);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      /* clipboard unavailable (insecure context): the id stays selectable */
    }
  }

  return (
    <span className={styles.copyable}>
      {text}
      <button type="button" className={styles.copyButton} onClick={() => void copy()}>
        {copied ? 'Скопировано' : 'Копировать'}
      </button>
    </span>
  );
}
