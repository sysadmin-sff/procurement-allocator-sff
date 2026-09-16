import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, KeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import Fuse from 'fuse.js';
import { materialsApi } from '../../api/materials';
import type { Material } from '../../api/types';
import styles from './ProjectBuilder.module.css';

const MIN_QUERY_LENGTH = 2;
const MAX_RESULTS = 20;

/**
 * canonical_name weighted above internal_sku: employees search by product
 * name far more often than by SKU (SKU is a fallback for when they happen
 * to remember it). useExtendedSearch splits the query on whitespace into
 * separate fuzzy terms that must ALL match (in any order) — plain Fuse
 * treats a multi-word query as one fuzzy pattern, which fails on reordered
 * words like "white gutter" against "...Super Gutter... (White/Bronze)".
 * threshold 0.35 tuned against the real catalog (see
 * MaterialCombobox.fuzzy.test.tsx) — catches word-order swaps and single-typo
 * queries (e.g. "guttter") without matching unrelated materials.
 */
const FUSE_OPTIONS: ConstructorParameters<typeof Fuse<Material>>[1] = {
  keys: [
    { name: 'canonical_name', weight: 0.7 },
    { name: 'internal_sku', weight: 0.3 },
  ],
  threshold: 0.35,
  ignoreLocation: true,
  useExtendedSearch: true,
};

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
  const [catalog, setCatalog] = useState<Material[]>([]);
  const [highlighted, setHighlighted] = useState(0);
  const [openUpward, setOpenUpward] = useState(false);
  /** Fixed-position coordinates for the portalled dropdown — computed fresh
   * each time the list opens (see openList) so it escapes any scrollable/
   * clipping ancestor (e.g. a table wrapper with overflow-x: auto, which per
   * the CSS spec also clips overflow-y) instead of being cut off by one. */
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    materialsApi.list().then(setCatalog).catch(() => setCatalog([]));
  }, []);

  const fuse = useMemo(() => new Fuse(catalog, FUSE_OPTIONS), [catalog]);

  const options = useMemo(() => {
    const trimmed = query.trim();
    if (trimmed.length < MIN_QUERY_LENGTH) return [];
    return fuse.search(trimmed, { limit: MAX_RESULTS }).map((r) => r.item);
  }, [fuse, query]);

  useEffect(() => {
    setHighlighted(0);
  }, [options]);

  function openList() {
    const wrap = wrapRef.current;
    if (wrap) {
      const rect = wrap.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom;
      setOpenUpward(spaceBelow < MIN_SPACE_BELOW_PX);
      setAnchorRect(rect);
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

  /** Fixed-position coordinates anchored to the input, computed from
   * anchorRect (captured on open — see openList). Portalled into
   * document.body below so the dropdown escapes any scrollable/clipping
   * ancestor between it and the viewport, rather than relying on being an
   * absolutely-positioned descendant of one. */
  const dropdownStyle: CSSProperties | undefined = anchorRect
    ? {
        position: 'fixed',
        left: anchorRect.left,
        width: anchorRect.width,
        ...(openUpward
          ? { bottom: window.innerHeight - anchorRect.top }
          : { top: anchorRect.bottom }),
      }
    : undefined;

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

      {open &&
        options.length > 0 &&
        dropdownStyle &&
        createPortal(
          <ul className={styles.comboboxListPortal} style={dropdownStyle} role="listbox">
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
                    {material.category_name} · {material.internal_sku}
                  </span>
                </button>
              </li>
            ))}
          </ul>,
          document.body,
        )}

      {showEmpty &&
        dropdownStyle &&
        createPortal(
          <div className={styles.comboboxEmptyPortal} style={dropdownStyle}>
            Ничего не найдено. Проверьте артикул или добавьте материал в базу.
          </div>,
          document.body,
        )}
    </div>
  );
}
