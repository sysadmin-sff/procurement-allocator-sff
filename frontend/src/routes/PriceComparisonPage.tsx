import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { materialsApi } from '../api/materials';
import { priceComparisonApi } from '../api/priceComparison';
import { projectsApi } from '../api/projects';
import type {
  Material,
  MaterialComparisonRow,
  PlanCandidate,
  ProjectWithItems,
  SupplierResponse,
} from '../api/types';
import { ErrorBanner } from '../components/ErrorBanner';
import crudStyles from '../components/CrudScreen.module.css';
import styles from './price-comparison/PriceComparison.module.css';

interface LoadedData {
  project: ProjectWithItems;
  materials: Material[];
  rows: MaterialComparisonRow[];
}

interface SupplierColumn {
  supplier_id: string;
  supplier_name: string;
}

export function PriceComparisonPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [data, setData] = useState<LoadedData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;

    setLoading(true);
    setLoadError(null);
    Promise.all([projectsApi.get(projectId), materialsApi.list(), priceComparisonApi.get(projectId)])
      .then(([project, materials, comparison]) => {
        if (cancelled) return;
        setData({ project, materials, rows: comparison.rows });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoadError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (!projectId) {
    return <ErrorBanner error="Не указан проект." />;
  }

  if (loading) {
    return <div className={crudStyles.loading}>Загрузка…</div>;
  }

  if (loadError || !data) {
    return (
      <div className={crudStyles.page}>
        <div className={crudStyles.inner}>
          <ErrorBanner error={loadError} />
        </div>
      </div>
    );
  }

  const { project, materials, rows } = data;
  const materialById = new Map(materials.map((m) => [m.id, m]));

  const planColumns = collectSupplierColumns(rows, (row) => row.plan);
  const responseColumns = collectSupplierColumns(rows, (row) => row.supplier_responses);
  const hasAnyResponse = rows.some((row) => row.supplier_responses.length > 0);

  return (
    <div className={crudStyles.page}>
      <div className={crudStyles.inner}>
        <Link to={`/projects/${projectId}`} className={crudStyles.backLink}>
          « Назад к проекту
        </Link>

        <div className={crudStyles.header}>
          <h1 className={crudStyles.title}>Сравнение цен — {project.title}</h1>
        </div>

        <div className={crudStyles.stack}>
          <div className={crudStyles.card}>
            <div className={crudStyles.sectionHeader}>
              <div className={crudStyles.sectionTitle}>План</div>
            </div>
            {planColumns.length === 0 ? (
              <div className={styles.emptyState}>
                Ни у одного поставщика нет цены на материалы этого проекта.
              </div>
            ) : (
              <PlanMatrix
                rows={rows}
                columns={planColumns}
                materialById={materialById}
                project={project}
              />
            )}
          </div>

          <div className={crudStyles.card}>
            <div className={crudStyles.sectionHeader}>
              <div className={crudStyles.sectionTitle}>Ответы поставщиков</div>
            </div>
            {!hasAnyResponse ? (
              <div className={styles.emptyState}>
                Ордера ещё не созданы — сравнение по факту появится после отправки.
              </div>
            ) : (
              <ResponseMatrix rows={rows} columns={responseColumns} materialById={materialById} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function collectSupplierColumns<T extends { supplier_id: string; supplier_name: string }>(
  rows: MaterialComparisonRow[],
  select: (row: MaterialComparisonRow) => T[],
): SupplierColumn[] {
  const byId = new Map<string, SupplierColumn>();
  for (const row of rows) {
    for (const candidate of select(row)) {
      if (!byId.has(candidate.supplier_id)) {
        byId.set(candidate.supplier_id, {
          supplier_id: candidate.supplier_id,
          supplier_name: candidate.supplier_name,
        });
      }
    }
  }
  return [...byId.values()].sort((a, b) => a.supplier_name.localeCompare(b.supplier_name));
}

function PlanMatrix({
  rows,
  columns,
  materialById,
  project,
}: {
  rows: MaterialComparisonRow[];
  columns: SupplierColumn[];
  materialById: Map<string, Material>;
  project: ProjectWithItems;
}) {
  const quantityByItemId = new Map(project.items.map((item) => [item.id, item.quantity]));

  return (
    <div className={styles.matrixScroll}>
      <table className={styles.matrixTable}>
        <thead>
          <tr>
            <th className={styles.materialColHeader}>Материал</th>
            {columns.map((col) => (
              <th key={col.supplier_id}>{col.supplier_name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const material = materialById.get(row.material_id);
            const bySupplier = new Map(row.plan.map((c) => [c.supplier_id, c]));
            const quantity = quantityByItemId.get(row.project_item_id) ?? null;
            return (
              <tr key={row.project_item_id}>
                <td className={styles.materialColCell}>
                  <span className={styles.materialName}>
                    {material?.canonical_name ?? row.material_id}
                  </span>
                  {material?.unit && <span className={styles.materialUnit}>{material.unit}</span>}
                </td>
                {columns.map((col) => (
                  <PlanCell
                    key={col.supplier_id}
                    candidate={bySupplier.get(col.supplier_id)}
                    unit={material?.unit ?? ''}
                    quantity={quantity}
                  />
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PlanCell({
  candidate,
  unit,
  quantity,
}: {
  candidate: PlanCandidate | undefined;
  unit: string;
  quantity: number | null;
}) {
  if (!candidate) {
    return (
      <td className={`${styles.priceCell} ${styles.dashCell}`} title="Нет цены в справочнике">
        —
      </td>
    );
  }

  const showRisk =
    candidate.is_cheapest &&
    quantity != null &&
    candidate.availability != null &&
    candidate.availability < quantity;

  return (
    <td className={`${styles.priceCell} ${candidate.is_cheapest ? styles.cheapest : ''}`}>
      {formatMoney(candidate.price)}
      {showRisk && (
        <AvailabilityWarning availability={candidate.availability!} unit={unit} required={quantity!} />
      )}
    </td>
  );
}

function ResponseMatrix({
  rows,
  columns,
  materialById,
}: {
  rows: MaterialComparisonRow[];
  columns: SupplierColumn[];
  materialById: Map<string, Material>;
}) {
  return (
    <div className={styles.matrixScroll}>
      <table className={styles.matrixTable}>
        <thead>
          <tr>
            <th className={styles.materialColHeader}>Материал</th>
            {columns.map((col) => (
              <th key={col.supplier_id}>{col.supplier_name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const material = materialById.get(row.material_id);
            const bySupplier = new Map(row.supplier_responses.map((c) => [c.supplier_id, c]));
            return (
              <tr key={row.project_item_id}>
                <td className={styles.materialColCell}>
                  <span className={styles.materialName}>
                    {material?.canonical_name ?? row.material_id}
                  </span>
                  {material?.unit && <span className={styles.materialUnit}>{material.unit}</span>}
                </td>
                {columns.map((col) => (
                  <ResponseCell key={col.supplier_id} response={bySupplier.get(col.supplier_id)} />
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ResponseCell({ response }: { response: SupplierResponse | undefined }) {
  if (!response) {
    return <td className={styles.blankCell}>—</td>;
  }

  if (response.declined_at != null) {
    return (
      <td>
        <span className={styles.declinedLabel}>Отказался</span>
        {response.received_price != null && (
          <span className={styles.declinedPrice}>{formatMoney(response.received_price)}</span>
        )}
      </td>
    );
  }

  const effectivePrice = response.confirmed_price ?? response.received_price ?? response.quoted_price;

  return (
    <td className={`${styles.priceCell} ${response.is_cheapest ? styles.cheapest : ''}`}>
      {formatMoney(effectivePrice)}
    </td>
  );
}

function AvailabilityWarning({
  availability,
  unit,
  required,
}: {
  availability: number;
  unit: string;
  required: number;
}) {
  return (
    <span className={styles.availabilityRisk}>
      ⚠ у поставщика доступно {availability} {unit}, требуется {required}
    </span>
  );
}

function formatMoney(value: number): string {
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
