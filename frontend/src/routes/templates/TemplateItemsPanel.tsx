import { useState } from 'react';
import type { Material, ProjectTemplate } from '../../api/types';
import { Button } from '../../components/Button';
import { MaterialCombobox } from '../project-builder/MaterialCombobox';
import styles from '../../components/CrudScreen.module.css';

interface TemplateItemsPanelProps {
  template: ProjectTemplate;
  isAdmin: boolean;
  onAddItem: (materialId: string) => Promise<void>;
  onRemoveItem: (itemId: string) => Promise<void>;
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
                <th>Категория</th>
                <th>Ед.</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {template.items.map((item) => (
                <tr key={item.id}>
                  <td>{item.canonical_name}</td>
                  <td>{item.category ?? <span className={styles.muted}>—</span>}</td>
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
