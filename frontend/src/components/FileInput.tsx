import { forwardRef, useState, type InputHTMLAttributes } from 'react';
import styles from './FileInput.module.css';

type FileInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'className'>;

/** Styled stand-in for the browser's default file input chrome — the native
 * "Выберите файл / Файл не выбран" button can't be restyled directly, so
 * this hides the real input and drives it via a label, mirroring its
 * selected-filename behavior in site styling.
 *
 * The input sits inside the label (implicit association) rather than being
 * pointed at via htmlFor: on macOS a click on a separate htmlFor-label did
 * not open the file picker for a visually hidden input, while the wrapping
 * form works in every browser. */
export const FileInput = forwardRef<HTMLInputElement, FileInputProps>(function FileInput(
  { disabled, onChange, ...rest },
  ref
) {
  const [fileName, setFileName] = useState<string | null>(null);

  return (
    <div className={styles.wrap}>
      <label className={`${styles.trigger} ${disabled ? styles.triggerDisabled : ''}`}>
        <input
          {...rest}
          ref={ref}
          type="file"
          disabled={disabled}
          className={styles.input}
          onChange={(e) => {
            setFileName(e.target.files?.[0]?.name ?? null);
            onChange?.(e);
          }}
        />
        Выбрать файл
      </label>
      <span className={styles.fileName}>{fileName ?? 'Файл не выбран'}</span>
    </div>
  );
});
