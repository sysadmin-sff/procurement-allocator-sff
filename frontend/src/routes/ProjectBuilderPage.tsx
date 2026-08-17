import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { allocationApi } from '../api/allocation';
import { projectsApi } from '../api/projects';
import type { Material } from '../api/types';
import { Button } from '../components/Button';
import { ErrorBanner } from '../components/ErrorBanner';
import { MaterialCombobox } from './project-builder/MaterialCombobox';
import styles from './project-builder/ProjectBuilder.module.css';

interface Row {
  id: string;
  material: Material | null;
  query: string;
  quantity: string;
}

let rowSeq = 0;
function newRow(): Row {
  rowSeq += 1;
  return { id: `row-${rowSeq}`, material: null, query: '', quantity: '' };
}

function isFilled(row: Row): boolean {
  return row.material !== null && Number(row.quantity) > 0;
}

function pluralizePositions(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return 'позиция';
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'позиции';
  return 'позиций';
}

export function ProjectBuilderPage() {
  const navigate = useNavigate();
  const [title, setTitle] = useState('');
  const [rows, setRows] = useState<Row[]>([newRow(), newRow()]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const qtyInputRefs = useRef<Record<string, HTMLInputElement | null>>({});

  const filledRows = rows.filter(isFilled);
  const incompleteCount = rows.length - filledRows.length;
  const canCalculate = filledRows.length > 0 && !submitting;

  function updateRow(id: string, patch: Partial<Row>) {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  }

  function addRow() {
    setRows((prev) => [...prev, newRow()]);
  }

  function removeRow(id: string) {
    setRows((prev) => (prev.length > 1 ? prev.filter((r) => r.id !== id) : prev));
  }

  function focusQuantity(id: string) {
    requestAnimationFrame(() => {
      const el = qtyInputRefs.current[id];
      el?.focus();
      el?.select();
    });
  }

  function handleQuantityKeyDown(event: React.KeyboardEvent<HTMLInputElement>, isLastRow: boolean) {
    if (event.key === 'Enter') {
      event.preventDefault();
      if (isLastRow) {
        addRow();
      }
    }
  }

  async function handleCalculate() {
    if (!canCalculate) return;
    setError(null);
    setSubmitting(true);
    try {
      const project = await projectsApi.create({ title: title.trim() || 'Проект без названия' });
      for (const row of filledRows) {
        await projectsApi.addItem(project.id, {
          material_id: row.material!.id,
          quantity: Number(row.quantity),
        });
      }
      await allocationApi.run(project.id);
      navigate(`/projects/${project.id}/allocation`);
    } catch (err) {
      setError(err);
      setSubmitting(false);
    }
  }

  const totalQty = filledRows.reduce((sum, r) => sum + Number(r.quantity), 0);

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <div className={styles.header}>
          <h1 className={styles.title}>Создание проекта</h1>
        </div>

        <div className={styles.stack}>
          {error != null && <ErrorBanner error={error} />}

          <div className={`${styles.card} ${styles.detailsCard}`}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="project-title">
                Название проекта
              </label>
              <input
                id="project-title"
                className={styles.input}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Например: Pool cage — 4821 Bayshore Rd, Bradenton"
              />
            </div>
          </div>

          <div className={styles.card}>
            <div className={styles.sectionHeader}>
              <div className={styles.sectionTitle}>Спецификация материалов</div>
              <div className={styles.spacer} />
              <div className={styles.hintRow}>
                <span className={styles.hintChip}>Tab</span> между полями
                <span className={styles.hintChip}>Enter</span> новая строка
                <span className={styles.hintChip}>↑↓</span> выбор в списке
              </div>
            </div>

            {rows.length > 0 && (
              <>
                <div className={`${styles.grid} ${styles.gridHeader}`}>
                  <div>#</div>
                  <div>Материал</div>
                  <div className={styles.gridHeaderQty}>Количество</div>
                  <div>Ед.</div>
                  <div>Категория</div>
                  <div></div>
                </div>

                {rows.map((row, index) => {
                  const isLastRow = index === rows.length - 1;
                  const invalid = row.material === null && row.query.trim().length > 0;
                  return (
                    <div key={row.id} className={`${styles.grid} ${styles.row}`}>
                      <div className={styles.rowNum}>{index + 1}</div>

                      <div className={styles.rowMaterialCell}>
                        <MaterialCombobox
                          query={row.query}
                          selected={row.material}
                          invalid={invalid}
                          onQueryChange={(query) => updateRow(row.id, { query, material: null })}
                          onSelect={(material) =>
                            updateRow(row.id, { material, query: material.canonical_name })
                          }
                          onQuantityFocus={() => focusQuantity(row.id)}
                        />
                      </div>

                      <div className={styles.rowQtyCell}>
                        <input
                          ref={(el) => {
                            qtyInputRefs.current[row.id] = el;
                          }}
                          className={styles.rowQtyInput}
                          type="number"
                          min="0"
                          step="1"
                          value={row.quantity}
                          placeholder="0"
                          onChange={(e) => updateRow(row.id, { quantity: e.target.value })}
                          onKeyDown={(e) => handleQuantityKeyDown(e, isLastRow)}
                        />
                      </div>

                      <div className={styles.rowUnit}>{row.material?.unit ?? '—'}</div>

                      <div className={styles.rowCategory}>{row.material?.category ?? ''}</div>

                      <div className={styles.rowRemove}>
                        <button
                          type="button"
                          className={styles.removeButton}
                          title="Удалить строку"
                          onClick={() => removeRow(row.id)}
                        >
                          ×
                        </button>
                      </div>
                    </div>
                  );
                })}
              </>
            )}

            {rows.length === 0 && (
              <div className={styles.emptyState}>
                <div className={styles.emptyIcon}>+</div>
                <div className={styles.emptyTitle}>В проекте пока нет материалов</div>
                <div className={styles.emptyDescription}>
                  Добавьте первую позицию и продолжайте с клавиатуры: название или артикул → Tab →
                  количество → Enter добавит следующую строку.
                </div>
                <Button variant="primary" onClick={addRow}>
                  Добавить материал »
                </Button>
              </div>
            )}

            <div className={styles.footer}>
              <button type="button" className={styles.addButton} onClick={addRow}>
                + Добавить материал
              </button>
              <div className={styles.spacer} />
              {incompleteCount > 0 && (
                <div className={styles.incompleteFlag}>
                  <span className={styles.incompleteDot} />
                  Незаполненных строк: {incompleteCount}
                </div>
              )}
              <div className={styles.countLabel}>
                {filledRows.length} {pluralizePositions(filledRows.length)} добавлено
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className={styles.stickyFooter}>
        <div className={styles.stickyFooterInner}>
          <div>
            <div className={styles.stickyTitle}>{title.trim() || 'Проект без названия'}</div>
            <div className={styles.stickyMeta}>
              {filledRows.length} {pluralizePositions(filledRows.length)} добавлено · суммарно{' '}
              {totalQty} ед.
            </div>
          </div>
          <div className={styles.spacer} />
          <Button
            variant="primary"
            disabled={!canCalculate}
            title={!canCalculate ? 'Добавьте хотя бы одну позицию с количеством' : undefined}
            onClick={() => void handleCalculate()}
          >
            {submitting ? 'Считаем…' : 'Рассчитать закупку »'}
          </Button>
        </div>
      </div>
    </div>
  );
}
