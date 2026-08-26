import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApiError } from '../../api/client';
import { materialsApi } from '../../api/materials';
import { priceListImportsApi } from '../../api/priceListImports';
import type { Material, PriceListEntry, PriceListImport } from '../../api/types';
import { ErrorBanner } from '../../components/ErrorBanner';
import { MaterialCombobox } from '../project-builder/MaterialCombobox';
import styles from './PriceListImportReview.module.css';

/** Thresholds mirror docs/ui-reference.md §1 (carried over from the
 * originally-planned Claude Design screen — this one reuses ADR-0018's
 * component vocabulary instead, per ADR-0019 §4, but the confidence bands
 * are a content decision, not a visual-language one, so they still apply). */
const CONFIDENCE_HIGH = 0.9;
const CONFIDENCE_MEDIUM = 0.7;

interface LoadedData {
  priceListImport: PriceListImport;
  materials: Material[];
}

export function PriceListImportReviewPage() {
  const { importId } = useParams<{ importId: string }>();
  const [data, setData] = useState<LoadedData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);

  // Per-row inclusion in the bulk-apply set (default checked, ADR-0018 §4
  // pattern) and per-row draft edits (material override / new-material SKU
  // & name), keyed by entry id — same "editable before commit" shape as
  // OrderDetailPage's ParseResponseSection.
  const [included, setIncluded] = useState<Record<string, boolean>>({});
  const [matchOverride, setMatchOverride] = useState<Record<string, Material | null>>({});
  const [matchQuery, setMatchQuery] = useState<Record<string, string>>({});
  const [newSku, setNewSku] = useState<Record<string, string>>({});
  const [newName, setNewName] = useState<Record<string, string>>({});

  const [applying, setApplying] = useState(false);
  const [applySummary, setApplySummary] = useState<string | null>(null);
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [skippingId, setSkippingId] = useState<string | null>(null);

  useEffect(() => {
    if (!importId) return;
    void load(importId);
  }, [importId]);

  async function load(id: string) {
    setLoading(true);
    setLoadError(null);
    try {
      const [priceListImport, materials] = await Promise.all([
        priceListImportsApi.get(id),
        materialsApi.list(),
      ]);
      seedDrafts(priceListImport.entries);
      setData({ priceListImport, materials });
    } catch (err) {
      setLoadError(err);
    } finally {
      setLoading(false);
    }
  }

  function seedDrafts(entries: PriceListEntry[]) {
    const nextIncluded: Record<string, boolean> = {};
    const nextSku: Record<string, string> = {};
    const nextName: Record<string, string> = {};
    for (const entry of entries) {
      if (entry.action != null) continue; // already resolved — not part of the pending set
      nextIncluded[entry.id] = true;
      nextSku[entry.id] = entry.suggested_internal_sku ?? '';
      nextName[entry.id] = entry.supplier_raw_name;
    }
    setIncluded(nextIncluded);
    setNewSku(nextSku);
    setNewName(nextName);
  }

  async function refresh() {
    if (!importId) return;
    const priceListImport = await priceListImportsApi.get(importId);
    setData((prev) => (prev ? { ...prev, priceListImport } : prev));
  }

  async function handleApplySelected() {
    if (!data || !importId) return;
    const pending = data.priceListImport.entries.filter(
      (e) => e.action == null && included[e.id],
    );
    if (pending.length === 0) return;

    setApplying(true);
    setApplySummary(null);
    setRowErrors({});
    let succeeded = 0;
    const errors: Record<string, string> = {};

    for (const entry of pending) {
      const isProposedMatch = entry.matched_material_id != null;
      try {
        if (isProposedMatch) {
          const material = matchOverride[entry.id];
          const materialId = material?.id ?? entry.matched_material_id;
          if (!materialId) throw new Error('Не выбран материал');
          await priceListImportsApi.applyEntry(importId, entry.id, {
            action: 'match',
            material_id: materialId,
          });
        } else {
          const sku = (newSku[entry.id] ?? '').trim();
          const name = (newName[entry.id] ?? '').trim();
          if (!sku || !name) throw new Error('Заполните SKU и название');
          await priceListImportsApi.applyEntry(importId, entry.id, {
            action: 'new',
            internal_sku: sku,
            canonical_name: name,
          });
        }
        succeeded += 1;
      } catch (err) {
        errors[entry.id] =
          err instanceof ApiError ? err.message : 'Не удалось применить строку.';
      }
    }

    setRowErrors(errors);
    setApplying(false);
    setApplySummary(`Применено ${succeeded} из ${pending.length}`);
    await refresh();
  }

  async function handleSkip(entry: PriceListEntry) {
    if (!importId) return;
    setSkippingId(entry.id);
    setRowErrors((prev) => {
      const next = { ...prev };
      delete next[entry.id];
      return next;
    });
    try {
      await priceListImportsApi.applyEntry(importId, entry.id, { action: 'skip' });
      await refresh();
    } catch (err) {
      setRowErrors((prev) => ({
        ...prev,
        [entry.id]: err instanceof ApiError ? err.message : 'Не удалось пропустить строку.',
      }));
    } finally {
      setSkippingId(null);
    }
  }

  if (!importId) {
    return <ErrorBanner error="Не указан импорт прайс-листа." />;
  }

  if (loading) {
    return <div className={styles.centerWrap}>Загрузка…</div>;
  }

  if (loadError || !data) {
    return (
      <div className={styles.centerWrap}>
        <ErrorBanner error={loadError} />
      </div>
    );
  }

  const { priceListImport, materials } = data;
  const materialById = new Map(materials.map((m) => [m.id, m]));
  const sortedEntries = sortByConfidenceThenDuplicateGroup(priceListImport.entries);
  const pendingCount = priceListImport.entries.filter(
    (e) => e.action == null && included[e.id],
  ).length;

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <Link to="/suppliers" className={styles.backLink}>
          « Назад к поставщикам
        </Link>

        <div className={styles.header}>
          <h1 className={styles.title}>Ревью прайс-листа</h1>
          <span
            className={
              priceListImport.status === 'approved'
                ? `${styles.statusBadge} ${styles.statusBadgeApproved}`
                : styles.statusBadge
            }
          >
            {statusLabel(priceListImport.status)}
          </span>
        </div>

        <div className={styles.toolbar}>
          <span className={styles.toolbarInfo}>
            {priceListImport.entries.length} строк · выбрано к применению: {pendingCount}
          </span>
          <button
            type="button"
            className={styles.applyButton}
            disabled={applying || pendingCount === 0}
            onClick={() => void handleApplySelected()}
          >
            {applying ? 'Применяем…' : 'Применить выбранные'}
          </button>
        </div>

        {applySummary != null && <div className={styles.applySummary}>{applySummary}</div>}

        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.checkboxCell} />
              <th>Строка прайса</th>
              <th className={styles.numCell}>Цена</th>
              <th>Уверенность</th>
              <th className={styles.actionColCell}>Действие</th>
              <th className={styles.statusColCell} />
            </tr>
          </thead>
          <tbody>
            {sortedEntries.map((entry, index) => {
              const prevEntry = sortedEntries[index - 1];
              const startsNewDuplicateGroup =
                entry.possible_duplicate_of.length > 0 &&
                prevEntry != null &&
                !prevEntry.possible_duplicate_of.includes(entry.id) &&
                !entry.possible_duplicate_of.includes(prevEntry.id);

              return (
                <EntryRow
                  key={entry.id}
                  entry={entry}
                  entriesById={new Map(priceListImport.entries.map((e) => [e.id, e]))}
                  proposedMaterial={
                    entry.matched_material_id != null
                      ? materialById.get(entry.matched_material_id)
                      : undefined
                  }
                  separateFromPrevious={startsNewDuplicateGroup}
                  included={included[entry.id] ?? false}
                  onToggleIncluded={(value) =>
                    setIncluded((prev) => ({ ...prev, [entry.id]: value }))
                  }
                  matchOverride={matchOverride[entry.id] ?? null}
                  matchQuery={matchQuery[entry.id] ?? ''}
                  onMatchQueryChange={(q) =>
                    setMatchQuery((prev) => ({ ...prev, [entry.id]: q }))
                  }
                  onMatchSelect={(material) =>
                    setMatchOverride((prev) => ({ ...prev, [entry.id]: material }))
                  }
                  newSku={newSku[entry.id] ?? ''}
                  onNewSkuChange={(v) => setNewSku((prev) => ({ ...prev, [entry.id]: v }))}
                  newName={newName[entry.id] ?? ''}
                  onNewNameChange={(v) => setNewName((prev) => ({ ...prev, [entry.id]: v }))}
                  onSkip={() => void handleSkip(entry)}
                  skipping={skippingId === entry.id}
                  rowError={rowErrors[entry.id]}
                />
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function statusLabel(status: PriceListImport['status']): string {
  if (status === 'approved') return 'Применено';
  if (status === 'rejected') return 'Отклонено';
  return 'На ревью';
}

/** Ascending by confidence (low first, per docs/ui-reference.md §1), null
 * last. Rows flagged as possible duplicates of each other are additionally
 * grouped adjacent within that ordering — ADR-0019 §4 asks for visual
 * grouping in addition to the badge, not instead of it. */
function sortByConfidenceThenDuplicateGroup(entries: PriceListEntry[]): PriceListEntry[] {
  const sorted = entries
    .slice()
    .sort((a, b) => (a.confidence ?? 2) - (b.confidence ?? 2));

  const placed = new Set<string>();
  const result: PriceListEntry[] = [];
  const byId = new Map(entries.map((e) => [e.id, e]));

  for (const entry of sorted) {
    if (placed.has(entry.id)) continue;
    result.push(entry);
    placed.add(entry.id);
    for (const dupId of entry.possible_duplicate_of) {
      if (placed.has(dupId)) continue;
      const dup = byId.get(dupId);
      if (!dup) continue;
      result.push(dup);
      placed.add(dupId);
    }
  }

  return result;
}

function confidenceClass(confidence: number | null): string {
  if (confidence == null) return '';
  if (confidence >= CONFIDENCE_HIGH) return styles.confidenceHigh;
  if (confidence >= CONFIDENCE_MEDIUM) return styles.confidenceMedium;
  return styles.confidenceLow;
}

function EntryRow({
  entry,
  entriesById,
  proposedMaterial,
  separateFromPrevious,
  included,
  onToggleIncluded,
  matchOverride,
  matchQuery,
  onMatchQueryChange,
  onMatchSelect,
  newSku,
  onNewSkuChange,
  newName,
  onNewNameChange,
  onSkip,
  skipping,
  rowError,
}: {
  entry: PriceListEntry;
  entriesById: Map<string, PriceListEntry>;
  proposedMaterial: Material | undefined;
  separateFromPrevious: boolean;
  included: boolean;
  onToggleIncluded: (value: boolean) => void;
  matchOverride: Material | null;
  matchQuery: string;
  onMatchQueryChange: (query: string) => void;
  onMatchSelect: (material: Material) => void;
  newSku: string;
  onNewSkuChange: (value: string) => void;
  newName: string;
  onNewNameChange: (value: string) => void;
  onSkip: () => void;
  skipping: boolean;
  rowError: string | undefined;
}) {
  const resolved = entry.action != null;
  const isProposedMatch = entry.matched_material_id != null;
  const lowConfidence = entry.confidence != null && entry.confidence < CONFIDENCE_MEDIUM;

  const rowClassNames = [
    resolved ? styles.rowResolved : lowConfidence ? styles.rowLowConfidence : '',
    separateFromPrevious ? styles.duplicateGroupSeparator : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <tr className={rowClassNames || undefined}>
      <td className={styles.checkboxCell}>
        {!resolved && (
          <input type="checkbox" checked={included} onChange={(e) => onToggleIncluded(e.target.checked)} />
        )}
      </td>
      <td>
        <span className={styles.rawName}>{entry.supplier_raw_name}</span>
        {entry.supplier_sku && <span className={styles.rawSku}>Артикул поставщика: {entry.supplier_sku}</span>}
        {entry.reasoning && <span className={styles.reasoning}>{entry.reasoning}</span>}
        {entry.possible_duplicate_of.length > 0 && (
          <span className={styles.duplicateBadge}>
            ⚠ похоже на другую новую позицию:{' '}
            {entry.possible_duplicate_of
              .map((id) => entriesById.get(id)?.supplier_raw_name ?? id)
              .join(', ')}
          </span>
        )}
      </td>
      <td className={styles.numCell}>{formatMoney(entry.price)}</td>
      <td>
        <span className={confidenceClass(entry.confidence)}>
          {entry.confidence != null ? `${Math.round(entry.confidence * 100)}%` : '—'}
        </span>
      </td>
      <td className={styles.actionColCell}>
        {resolved ? (
          <span className={styles.resolvedLabel}>{resolvedActionLabel(entry)}</span>
        ) : isProposedMatch ? (
          <div>
            <span className={styles.actionLabel}>Совпадение с материалом</span>
            <MaterialCombobox
              query={matchQuery || matchOverride?.canonical_name || proposedMaterial?.canonical_name || ''}
              selected={matchOverride ?? proposedMaterial ?? null}
              invalid={false}
              onQueryChange={onMatchQueryChange}
              onSelect={onMatchSelect}
              onQuantityFocus={() => {}}
            />
          </div>
        ) : (
          <div>
            <span className={styles.actionLabel}>Новый материал</span>
            <div className={styles.field}>
              <span className={styles.fieldLabel}>internal_sku</span>
              <input
                className={styles.input}
                value={newSku}
                onChange={(e) => onNewSkuChange(e.target.value)}
              />
            </div>
            <div className={styles.field}>
              <span className={styles.fieldLabel}>canonical_name</span>
              <input
                className={styles.input}
                value={newName}
                onChange={(e) => onNewNameChange(e.target.value)}
              />
            </div>
          </div>
        )}
        {rowError != null && <span className={styles.rowError}>{rowError}</span>}
      </td>
      <td className={styles.statusColCell}>
        {!resolved && (
          <button
            type="button"
            className={styles.skipButton}
            disabled={skipping}
            onClick={onSkip}
          >
            {skipping ? 'Пропускаем…' : 'Пропустить'}
          </button>
        )}
      </td>
    </tr>
  );
}

function resolvedActionLabel(entry: PriceListEntry): string {
  if (entry.action === 'match') return '✓ Применено (совпадение)';
  if (entry.action === 'new') return '✓ Применено (новый материал)';
  return 'Пропущено';
}

function formatMoney(value: number): string {
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
