import { forwardRef, useId, useState, type InputHTMLAttributes } from 'react';
import styles from './FileInput.module.css';

type FileInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'className'>;

/** Styled stand-in for the browser's default file input chrome — the native
 * "Выберите файл / Файл не выбран" button can't be restyled directly, so
 * this hides the real input and drives it via a label, mirroring its
 * selected-filename behavior in site styling. */
export const FileInput = forwardRef<HTMLInputElement, FileInputProps>(function FileInput(
  { disabled, onChange, ...rest },
  ref
) {
  const inputId = useId();
  const [fileName, setFileName] = useState<string | null>(null);

  return (
    <div className={styles.wrap}>
      <input
        {...rest}
        ref={ref}
        id={inputId}
        type="file"
        disabled={disabled}
        className={styles.input}
        onChange={(e) => {
          setFileName(e.target.files?.[0]?.name ?? null);
          onChange?.(e);
        }}
      />
      <label htmlFor={inputId} className={`${styles.trigger} ${disabled ? styles.triggerDisabled : ''}`}>
        Выбрать файл
      </label>
      <span className={styles.fileName}>{fileName ?? 'Файл не выбран'}</span>
    </div>
  );
});
