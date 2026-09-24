import { Fragment, useMemo, useState } from 'react';
import type { Material, ProjectTemplate, ProjectTemplateItem } from '../../api/types';
import { Button } from '../../components/Button';
import { MaterialCombobox } from '../project-builder/MaterialCombobox';
import styles from '../../components/CrudScreen.module.css';

interface TemplateItemsPanelProps {
  template: ProjectTemplate;
  isAdmin: boolean;
  onAddItem: (materialId: string) => Promise<void>;
  onRemoveItem: (itemId: string) => Promise<void>;
}

interface CategoryGroup {
  category: string | null;
  items: ProjectTemplateItem[];
}

/**
 * Groups template items by category_name, preserving each category's
 * first-appearance order (not alphabetical) — same pattern as
 * ProjectDetailPage's groupItemsByCategory. Items with no category (empty
 * string) fall into a single "Без категории" group, always last regardless
 * of where they'd otherwise sort.
 */
function groupItemsByCategory(items: ProjectTemplateItem[]): CategoryGroup[] {
  const order: (string | null)[] = [];
  const byCategory = new Map<string | null, ProjectTemplateItem[]>();

  for (const item of items) {
    const category = item.category_name || null;
    if (!byCategory.has(category)) {
      byCategory.set(category, []);
      order.push(category);
    }
    byCategory.get(category)!.push(item);
  }

  const orderedCategories = [...order.filter((c) => c !== null), ...(byCategory.has(null) ? [null] : [])];

  return orderedCategories.map((category) => ({
    category,
    items: byCategory.get(category)!,
  }));
}

/** Counts occurrences of each material_id — used to flag duplicate rows
 * (same material added to the template more than once) without blocking
 * the add itself; see ADR-0032. */
function countByMaterialId(items: ProjectTemplateItem[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const item of items) {
    counts.set(item.material_id, (counts.get(item.material_id) ?? 0) + 1);
  }
  return counts;
}

export function TemplateItemsPanel({
  template,
  isAdmin,
  onAddItem,
  onRemoveItem,
}: TemplateItemsPanelProps) {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Material | null>(null);
  const [adding, setAdding] = useState(false);

  const duplicateCounts = useMemo(() => countByMaterialId(template.items), [template.items]);

  async function handleAdd() {
    if (!selected) return;
    setAdding(true);
    try {
      await onAddItem(selected.id);
      setSelected(null);
      setQuery('');
    } finally {
      setAdding(false);
    }
  }

  return (
    <div className={`${styles.cardPadded} ${styles.stack}`}>
      {template.items.length === 0 && (
        <div className={styles.muted}>В шаблоне пока нет материалов.</div>
      )}

      {template.items.length > 0 && (
        <div className={styles.tableScroll}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Материал</th>
                <th>Ед.</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {groupItemsByCategory(template.items).map((group) => (
                <Fragment key={group.category ?? '__none__'}>
                  <tr className={styles.categoryRow}>
                    <td colSpan={3} className={styles.categoryCell}>
                      {group.category ?? 'Без категории'}
                    </td>
                  </tr>
                  {group.items.map((item) => {
                    const isDuplicate = (duplicateCounts.get(item.material_id) ?? 0) > 1;
                    return (
                      <tr key={item.id} className={isDuplicate ? styles.duplicateRow : undefined}>
                        <td>
                          {item.canonical_name}
                          {isDuplicate && (
                            <span className={`${styles.badge} ${styles.badgeWarning}`} style={{ marginLeft: 'var(--space-3)' }}>
                              дубль
                            </span>
                          )}
                        </td>
                        <td>{item.unit}</td>
                        <td>
                          <div className={styles.actionsCell}>
                            <Button
                              variant="ghost"
                              disabled={!isAdmin}
                              onClick={() => void onRemoveItem(item.id)}
                            >
                              Убрать
                            </Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {isAdmin && (
        <div className={styles.formGrid}>
          <div className={`${styles.field} ${styles.fieldFull}`}>
            <label className={styles.label}>Добавить материал</label>
            <div style={{ display: 'flex', gap: 'var(--space-4)', alignItems: 'flex-start' }}>
              <div style={{ flex: 1 }}>
                <MaterialCombobox
                  query={query}
                  selected={selected}
                  invalid={false}
                  onQueryChange={(q) => {
                    setQuery(q);
                    setSelected(null);
                  }}
                  onSelect={(material) => {
                    setSelected(material);
                    setQuery(material.canonical_name);
                  }}
                  onQuantityFocus={() => {}}
                />
              </div>
              <Button
                type="button"
                variant="secondary"
                disabled={!selected || adding}
                onClick={() => void handleAdd()}
              >
                Добавить
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
