import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { allocationApi } from '../api/allocation';
import { materialsApi } from '../api/materials';
import { projectsApi } from '../api/projects';
import type { Material, ProjectWithItems } from '../api/types';
import { Button } from '../components/Button';
import { ErrorBanner } from '../components/ErrorBanner';
import { useDebouncedCallback } from '../hooks/useDebouncedCallback';
import { usePerKeyDebounce } from '../hooks/usePerKeyDebounce';
import { MaterialCombobox } from './project-builder/MaterialCombobox';
import styles from './project-builder/ProjectBuilder.module.css';

const AUTOSAVE_DEBOUNCE_MS = 500;

interface Row {
  id: string;
  material: Material | null;
  query: string;
  quantity: string;
  /** ProjectItem id once this row has been saved to the backend. */
  remoteId: string | null;
  /** material_id last persisted for this row's remoteId — detects a material swap. */
  remoteMaterialId: string | null;
  /** quantity last persisted for this row's remoteId — avoids redundant PATCH calls. */
  remoteQuantity: number | null;
}

let rowSeq = 0;
function newRow(): Row {
  rowSeq += 1;
  return {
    id: `row-${rowSeq}`,
    material: null,
    query: '',
    quantity: '',
    remoteId: null,
    remoteMaterialId: null,
    remoteQuantity: null,
  };
}

function rowFromItem(item: ProjectWithItems['items'][number], materials: Material[]): Row {
  rowSeq += 1;
  const material = materials.find((m) => m.id === item.material_id) ?? null;
  return {
    id: `row-${rowSeq}`,
    material,
    query: material?.canonical_name ?? '',
    quantity: String(item.quantity),
    remoteId: item.id,
    remoteMaterialId: item.material_id,
    remoteQuantity: item.quantity,
  };
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

interface ProjectBuilderPageProps {
  /** Present when editing an existing draft at /projects/:projectId (see ADR-0004). */
  projectId?: string;
  initialProject?: ProjectWithItems;
}

export function ProjectBuilderPage({ projectId, initialProject }: ProjectBuilderPageProps = {}) {
  const navigate = useNavigate();
  const [title, setTitle] = useState(initialProject?.title ?? '');
  const [rows, setRows] = useState<Row[]>(initialProject ? [] : [newRow(), newRow()]);
  const [rowsLoading, setRowsLoading] = useState(initialProject != null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [pendingSaves, setPendingSaves] = useState(0);
  const [saveError, setSaveError] = useState<unknown>(null);
  const qtyInputRefs = useRef<Record<string, HTMLInputElement | null>>({});
  const projectIdRef = useRef<string | null>(projectId ?? initialProject?.id ?? null);
  const titleSavedRef = useRef(initialProject?.title ?? '');

  useEffect(() => {
    if (!initialProject) return;
    materialsApi.list().then((materials) => {
      setRows([...initialProject.items.map((item) => rowFromItem(item, materials)), newRow()]);
      setRowsLoading(false);
    });
  }, [initialProject]);

  const filledRows = rows.filter(isFilled);
  const incompleteCount = rows.length - filledRows.length;
  const canCalculate = filledRows.length > 0 && !submitting && pendingSaves === 0;

  const inFlightSavesRef = useRef(new Set<Promise<unknown>>());

  // Invariant required by waitForInFlightSaves below: any new save request
  // MUST be registered into inFlightSavesRef synchronously, before the first
  // await in the calling code — otherwise waitForInFlightSaves's no-race
  // guarantee no longer holds (it can observe an empty Set and return while a
  // save that was about to be registered is still unaccounted for). Every
  // call site that starts a save must wrap it in withSaveTracking() before
  // doing anything else async.
  function withSaveTracking<T>(promise: Promise<T>): Promise<T> {
    setPendingSaves((n) => n + 1);
    const tracked: Promise<T> = promise
      .then((result) => {
        setSaveError(null);
        return result;
      })
      .catch((err) => {
        setSaveError(err);
        throw err;
      })
      .finally(() => {
        setPendingSaves((n) => n - 1);
        inFlightSavesRef.current.delete(tracked);
      });
    inFlightSavesRef.current.add(tracked);
    return tracked;
  }

  /**
   * Waits for every save request in flight, including ones that only get
   * kicked off as a consequence of the ones currently pending — e.g.
   * `saveRow`'s `addItem`/`updateItem` call isn't registered until its
   * `ensureProjectCreated` await resolves, so a single snapshot-and-wait
   * would miss it. Loops until nothing is left in flight — re-reads
   * inFlightSavesRef.current.size after each wave settles, so a save that
   * gets registered mid-wave (see withSaveTracking's invariant above) is
   * caught by the next iteration instead of being missed.
   */
  async function waitForInFlightSaves() {
    while (inFlightSavesRef.current.size > 0) {
      await Promise.allSettled([...inFlightSavesRef.current]);
    }
  }

  const creationInFlightRef = useRef<Promise<string> | null>(null);

  function ensureProjectCreated(currentTitle: string): Promise<string> {
    if (projectIdRef.current) return Promise.resolve(projectIdRef.current);
    if (creationInFlightRef.current) return creationInFlightRef.current;

    const creation = withSaveTracking(
      projectsApi.create({ title: currentTitle.trim() || 'Проект без названия' })
    ).then((project) => {
      projectIdRef.current = project.id;
      titleSavedRef.current = project.title;
      navigate(`/projects/${project.id}`, { replace: true });
      return project.id;
    });

    creationInFlightRef.current = creation;
    creation.finally(() => {
      creationInFlightRef.current = null;
    });
    return creation;
  }

  const debouncedSaveTitle = useDebouncedCallback((nextTitle: string) => {
    if (projectIdRef.current) {
      if (nextTitle.trim() === titleSavedRef.current.trim()) return;
      const trimmed = nextTitle.trim() || 'Проект без названия';
      titleSavedRef.current = trimmed;
      void withSaveTracking(projectsApi.updateProject(projectIdRef.current, trimmed)).catch(() => {
        // surfaced via saveError banner; nothing else to do here
      });
      return;
    }
    if (nextTitle.trim().length > 0) {
      void ensureProjectCreated(nextTitle);
    }
  }, AUTOSAVE_DEBOUNCE_MS);

  async function saveRow(rowId: string) {
    const row = rows.find((r) => r.id === rowId);
    if (!row || !isFilled(row)) return;

    const id = await ensureProjectCreated(title);
    const quantity = Number(row.quantity);

    try {
      if (row.remoteId && row.remoteMaterialId === row.material!.id) {
        if (row.remoteQuantity !== quantity) {
          await withSaveTracking(projectsApi.updateItem(id, row.remoteId, quantity));
          updateRow(rowId, { remoteQuantity: quantity });
        }
        return;
      }

      if (row.remoteId && row.remoteMaterialId !== row.material!.id) {
        await withSaveTracking(projectsApi.removeItem(id, row.remoteId));
      }

      const created = await withSaveTracking(
        projectsApi.addItem(id, { material_id: row.material!.id, quantity })
      );
      updateRow(rowId, {
        remoteId: created.id,
        remoteMaterialId: row.material!.id,
        remoteQuantity: quantity,
      });
    } catch {
      // surfaced via saveError banner
    }
  }

  const rowSaveDebounce = usePerKeyDebounce((rowId: string) => {
    void saveRow(rowId);
  }, AUTOSAVE_DEBOUNCE_MS);

  function updateRow(id: string, patch: Partial<Row>) {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  }

  function handleTitleChange(nextTitle: string) {
    setTitle(nextTitle);
    debouncedSaveTitle(nextTitle);
  }

  function handleRowFieldChange(rowId: string, patch: Partial<Row>) {
    updateRow(rowId, patch);
    const nextRow = { ...rows.find((r) => r.id === rowId), ...patch } as Row;
    if (isFilled(nextRow)) {
      rowSaveDebounce.schedule(rowId);
    }
  }

  function addRow() {
    setRows((prev) => [...prev, newRow()]);
  }

  async function removeRow(id: string) {
    const row = rows.find((r) => r.id === id);
    if (!row || rows.length <= 1) return;
    rowSaveDebounce.cancel(id);
    setRows((prev) => prev.filter((r) => r.id !== id));
    if (row.remoteId && projectIdRef.current) {
      try {
        await withSaveTracking(projectsApi.removeItem(projectIdRef.current, row.remoteId));
      } catch (err) {
        setSaveError(err);
      }
    }
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
      // Force out whatever edit is still sitting in a debounce window — a
      // pending timer alone doesn't touch the backend, so without this the
      // very last keystroke before the click can be missing from the
      // calculation (see ADR-0004 "Условие приёмки" for debounced saves).
      // waitForInFlightSaves tracks the actual promises, not React state, so
      // it stays correct even though this closure's own `rows`/`filledRows`
      // snapshot goes stale the moment flush triggers a re-render.
      debouncedSaveTitle.flush();
      rowSaveDebounce.flushAll();
      await waitForInFlightSaves();

      const id = await ensureProjectCreated(title);
      await allocationApi.run(id);
      navigate(`/projects/${id}/allocation`);
    } catch (err) {
      setError(err);
      setSubmitting(false);
    }
  }

  const totalQty = filledRows.reduce((sum, r) => sum + Number(r.quantity), 0);
  const savingLabel =
    pendingSaves > 0 ? 'Сохранение…' : saveError ? 'Ошибка сохранения' : projectIdRef.current ? 'Сохранено' : null;

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <div className={styles.header}>
          <h1 className={styles.title}>
            {initialProject ? title.trim() || 'Проект без названия' : 'Создание проекта'}
          </h1>
          <span className={styles.headerMeta}>черновик · сохраняется автоматически</span>
        </div>

        <div className={styles.stack}>
          {error != null && <ErrorBanner error={error} />}
          {saveError != null && (
            <ErrorBanner error={saveError} conflictMessage="Не удалось сохранить изменения." />
          )}

          <div className={`${styles.card} ${styles.detailsCard}`}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="project-title">
                Название проекта
              </label>
              <input
                id="project-title"
                className={styles.input}
                value={title}
                onChange={(e) => handleTitleChange(e.target.value)}
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

            {rowsLoading && <div className={styles.loading}>Загрузка…</div>}

            {!rowsLoading && rows.length > 0 && (
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
                          onQueryChange={(query) =>
                            handleRowFieldChange(row.id, { query, material: null })
                          }
                          onSelect={(material) =>
                            handleRowFieldChange(row.id, { material, query: material.canonical_name })
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
                          onChange={(e) => handleRowFieldChange(row.id, { quantity: e.target.value })}
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
                          onClick={() => void removeRow(row.id)}
                        >
                          ×
                        </button>
                      </div>
                    </div>
                  );
                })}
              </>
            )}

            {!rowsLoading && rows.length === 0 && (
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
              <Button variant="secondary" onClick={addRow}>
                + Добавить материал
              </Button>
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
              {savingLabel && ` · ${savingLabel}`}
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
