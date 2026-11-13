import { forwardRef, useRef, useState, type DragEvent, type InputHTMLAttributes } from 'react';
import styles from './FileInput.module.css';
import { fileMatchesAccept } from './fileAccept';

type FileInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'className'>;

/** Styled stand-in for the browser's default file input chrome — the native
 * "Выберите файл / Файл не выбран" button can't be restyled directly, so
 * this hides the real input and drives it via a label, mirroring its
 * selected-filename behavior in site styling.
 *
 * The input sits inside the label (implicit association) rather than being
 * pointed at via htmlFor: on macOS a click on a separate htmlFor-label did
 * not open the file picker for a visually hidden input.
 *
 * A file can also be dropped onto the whole block — a fallback for machines
 * where the system file picker does not open at all. The dropped file is put
 * into the real input's `files`, so callers keep reading
 * `ref.current.files[0]` exactly as after a picker selection. */
export const FileInput = forwardRef<HTMLInputElement, FileInputProps>(function FileInput(
  { disabled, onChange, accept, ...rest },
  ref
) {
  const [fileName, setFileName] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [rejected, setRejected] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  function setRefs(node: HTMLInputElement | null) {
    inputRef.current = node;
    if (typeof ref === 'function') ref(node);
    else if (ref) ref.current = node;
  }

  function handleDragOver(e: DragEvent<HTMLDivElement>) {
    if (disabled || !e.dataTransfer.types.includes('Files')) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    setDragging(true);
  }

  function handleDragLeave(e: DragEvent<HTMLDivElement>) {
    if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
    setDragging(false);
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    if (disabled) return;
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    const input = inputRef.current;
    if (!file || !input) return;
    if (!fileMatchesAccept(file, accept)) {
      setRejected(true);
      return;
    }
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    // React listens to the native change event — fires the same onChange
    // path as a picker selection (updates the filename label too).
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  const wrapClass = [styles.wrap, dragging ? styles.wrapDragging : ''].join(' ');

  return (
    <div
      className={wrapClass}
      onDragOver={handleDragOver}
      onDragEnter={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      data-testid="file-drop-zone"
    >
      <label className={`${styles.trigger} ${disabled ? styles.triggerDisabled : ''}`}>
        <input
          {...rest}
          ref={setRefs}
          type="file"
          accept={accept}
          disabled={disabled}
          className={styles.input}
          onChange={(e) => {
            setRejected(false);
            setFileName(e.target.files?.[0]?.name ?? null);
            onChange?.(e);
          }}
        />
        Выбрать файл
      </label>
      <span className={rejected ? styles.fileNameError : styles.fileName}>
        {rejected
          ? 'Этот тип файла не подходит'
          : (fileName ?? (dragging ? 'Отпустите файл здесь' : 'Файл не выбран · можно перетащить сюда'))}
      </span>
    </div>
  );
});
