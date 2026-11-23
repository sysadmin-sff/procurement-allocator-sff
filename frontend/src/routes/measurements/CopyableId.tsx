import { useEffect, useState } from 'react';
import styles from './Measurements.module.css';

const COPIED_MS = 1500;

/** An identifier that copies itself on click; a small icon marks it as copyable. */
export function CopyableId({ value }: { value: number | string }) {
  const [copied, setCopied] = useState(false);
  const text = String(value);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), COPIED_MS);
    return () => clearTimeout(timer);
  }, [copied]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      /* clipboard unavailable (insecure context): the id stays selectable */
    }
  }

  const label = copied ? 'Скопировано' : 'Копировать';
  return (
    <button
      type="button"
      className={styles.copyable}
      onClick={() => void copy()}
      title={label}
      aria-label={`${label} ${text}`}
    >
      {text}
      <svg
        className={copied ? styles.copyIconDone : styles.copyIcon}
        viewBox="0 0 16 16"
        width="12"
        height="12"
        aria-hidden="true"
      >
        {copied ? (
          <path
            d="M3 8.5l3 3 7-7"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : (
          <>
            <rect
              x="5"
              y="5"
              width="8.5"
              height="8.5"
              rx="1.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.4"
            />
            <path
              d="M10.5 3.5V3a1.5 1.5 0 0 0-1.5-1.5H3.5A1.5 1.5 0 0 0 2 3v5.5A1.5 1.5 0 0 0 3.5 10H4"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.4"
            />
          </>
        )}
      </svg>
    </button>
  );
}
