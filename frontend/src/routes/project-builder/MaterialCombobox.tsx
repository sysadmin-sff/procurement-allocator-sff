import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { materialsApi } from '../../api/materials';
import type { Material } from '../../api/types';
import styles from './ProjectBuilder.module.css';

const MIN_QUERY_LENGTH = 2;
const SEARCH_DEBOUNCE_MS = 200;

interface MaterialComboboxProps {
  query: string;
  selected: Material | null;
  invalid: boolean;
  onQueryChange: (query: string) => void;
  onSelect: (material: Material) => void;
  inputRef?: React.Ref<HTMLInputElement>;
  onQuantityFocus: () => void;
}

/** Below this many pixels of room underneath the input, the list opens upward instead. */
const MIN_SPACE_BELOW_PX = 200;

export function MaterialCombobox({
  query,
  selected,
  invalid,
  onQueryChange,
  onSelect,
  inputRef,
  onQuantityFocus,
}: MaterialComboboxProps) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<Material[]>([]);
  const [highlighted, setHighlighted] = useState(0);
  const [openUpward, setOpenUpward] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (query.trim().length < MIN_QUERY_LENGTH) {
      setOptions([]);
      return;
    }

    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      materialsApi
        .search(query.trim())
        .then((results) => {
          setOptions(results);
          setHighlighted(0);
        })
        .catch(() => setOptions([]));
    }, SEARCH_DEBOUNCE_MS);

    return () => clearTimeout(debounceRef.current);
  }, [query]);

  function openList() {
    const wrap = wrapRef.current;
    if (wrap) {
      const spaceBelow = window.innerHeight - wrap.getBoundingClientRect().bottom;
      setOpenUpward(spaceBelow < MIN_SPACE_BELOW_PX);
    }
    setOpen(true);
  }

  function pick(material: Material) {
    onSelect(material);
    setOpen(false);
    onQuantityFocus();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      openList();
      setHighlighted((i) => Math.min(i + 1, options.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setHighlighted((i) => Math.max(i - 1, 0));
    } else if (event.key === 'Enter') {
      const option = options[highlighted];
      if (option) {
        event.preventDefault();
        pick(option);
      }
    } else if (event.key === 'Escape') {
      setOpen(false);
    }
  }

  const showEmpty = open && query.trim().length >= MIN_QUERY_LENGTH && options.length === 0;

  return (
    <div className={styles.comboboxWrap} ref={wrapRef}>
      <input
        ref={inputRef}
        className={`${styles.input} ${invalid ? styles.inputInvalid : ''}`}
        value={query}
        placeholder="Название или артикул…"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        onChange={(e) => onQueryChange(e.target.value)}
        onFocus={openList}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={handleKeyDown}
      />
      {selected && <div className={styles.comboboxUnit}>{selected.unit}</div>}

      {open && options.length > 0 && (
        <ul
          className={`${styles.comboboxList} ${openUpward ? styles.comboboxListUp : ''}`}
          role="listbox"
        >
          {options.map((material, index) => (
            <li key={material.id} role="option" aria-selected={index === highlighted}>
              <button
                type="button"
                className={`${styles.comboboxOption} ${index === highlighted ? styles.comboboxOptionActive : ''}`}
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => setHighlighted(index)}
                onClick={() => pick(material)}
              >
                <span className={styles.comboboxOptionName}>{material.canonical_name}</span>
                <span className={styles.comboboxOptionMeta}>
                  {material.category ?? '—'} · {material.internal_sku}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {showEmpty && (
        <div
          className={`${styles.comboboxEmpty} ${openUpward ? styles.comboboxListUp : ''}`}
        >
          Ничего не найдено. Проверьте артикул или добавьте материал в базу.
        </div>
      )}
    </div>
  );
}
