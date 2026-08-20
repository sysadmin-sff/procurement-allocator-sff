import { Fragment, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { materialsApi } from '../api/materials';
import { ordersApi } from '../api/orders';
import { projectsApi } from '../api/projects';
import { suppliersApi } from '../api/suppliers';
import type { Material, Order, ProjectItem, ProjectWithItems, Supplier } from '../api/types';
import { Button } from '../components/Button';
import { ConfirmButton } from '../components/ConfirmButton';
import { ErrorBanner } from '../components/ErrorBanner';
import { MaterialCombobox } from './project-builder/MaterialCombobox';
import styles from '../components/CrudScreen.module.css';

type Status = 'loading' | 'ready' | 'error';

interface ProjectDetailPageProps {
  /** Already-loaded project — skips the initial GET when the caller (ProjectRouterPage) has it. */
  initialProject?: ProjectWithItems;
}

export function ProjectDetailPage({ initialProject }: ProjectDetailPageProps = {}) {
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const projectId = initialProject?.id ?? routeProjectId;
  const navigate = useNavigate();
  const [project, setProject] = useState<ProjectWithItems | null>(initialProject ?? null);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [status, setStatus] = useState<Status>('loading');
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [newMaterialQuery, setNewMaterialQuery] = useState('');
  const [newMaterial, setNewMaterial] = useState<Material | null>(null);
  const [newQuantity, setNewQuantity] = useState('');
  const [addingItem, setAddingItem] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    if (initialProject) {
      void loadMaterialsOnly(projectId);
      return;
    }
    void load(projectId);
  }, [projectId, initialProject]);

  async function loadMaterialsOnly(id: string) {
    setStatus('loading');
    setLoadError(null);
    try {
      const [materialsData, suppliersData, ordersData] = await Promise.all([
        materialsApi.list(),
        suppliersApi.list(),
        ordersApi.listForProject(id),
      ]);
      setMaterials(materialsData);
      setSuppliers(suppliersData);
      setOrders(ordersData);
      setStatus('ready');
    } catch (err) {
      setLoadError(err);
      setStatus('error');
    }
  }

  async function load(id: string) {
    setStatus('loading');
    setLoadError(null);
    try {
      const [projectData, materialsData, suppliersData, ordersData] = await Promise.all([
        projectsApi.get(id),
        materialsApi.list(),
        suppliersApi.list(),
        ordersApi.listForProject(id),
      ]);
      setProject(projectData);
      setMaterials(materialsData);
      setSuppliers(suppliersData);
      setOrders(ordersData);
      setStatus('ready');
    } catch (err) {
      setLoadError(err);
      setStatus('error');
    }
  }

  async function handleQuantityChange(item: ProjectItem, quantity: number) {
    if (!projectId || !project || quantity === item.quantity) return;
    setActionError(null);
    setProject({
      ...project,
      items: project.items.map((i) => (i.id === item.id ? { ...i, quantity } : i)),
    });
    try {
      await projectsApi.updateItem(projectId, item.id, quantity);
    } catch (err) {
      setActionError(err);
      await load(projectId);
    }
  }

  async function handleRemoveItem(item: ProjectItem) {
    if (!projectId || !project) return;
    setActionError(null);
    try {
      await projectsApi.removeItem(projectId, item.id);
      setProject({ ...project, items: project.items.filter((i) => i.id !== item.id) });
    } catch (err) {
      setActionError(err);
    }
  }

  async function handleAddItem() {
    if (!projectId || !newMaterial || Number(newQuantity) <= 0) return;
    setActionError(null);
    setAddingItem(true);
    try {
      const item = await projectsApi.addItem(projectId, {
        material_id: newMaterial.id,
        quantity: Number(newQuantity),
      });
      setProject((prev) => (prev ? { ...prev, items: [...prev.items, item] } : prev));
      setNewMaterial(null);
      setNewMaterialQuery('');
      setNewQuantity('');
    } catch (err) {
      setActionError(err);
    } finally {
      setAddingItem(false);
    }
  }

  async function handleComplete() {
    if (!projectId) return;
    setActionError(null);
    try {
      const updated = await projectsApi.complete(projectId);
      setProject((prev) => (prev ? { ...prev, status: updated.status } : prev));
    } catch (err) {
      setActionError(err);
    }
  }

  if (!projectId) {
    return <ErrorBanner error="Не указан проект." />;
  }

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <div className={styles.header}>
          <h1 className={styles.title}>{project?.title ?? 'Проект'}</h1>
          {status === 'ready' && project && (
            <div className={styles.actionsCell}>
              {project.status === 'ordered' && (
                <Button variant="secondary" onClick={() => void handleComplete()}>
                  Завершить проект
                </Button>
              )}
              <Button
                variant="primary"
                onClick={() => navigate(`/projects/${projectId}/allocation`)}
              >
                {project.latest_allocation_run ? 'Пересчитать закупку »' : 'Рассчитать закупку »'}
              </Button>
            </div>
          )}
        </div>

        <div className={styles.stack}>
          {status === 'loading' && <div className={styles.loading}>Загрузка…</div>}

          {status === 'error' && <ErrorBanner error={loadError} />}

          {actionError != null && <ErrorBanner error={actionError} />}

          {status === 'ready' && project && (
            <>
              {project.latest_allocation_run && (
                <div className={`${styles.card} ${styles.cardPadded}`}>
                  Последний расчёт: {formatDateTime(project.latest_allocation_run.created_at)}
                </div>
              )}

              {orders.length > 0 && (
                <div className={styles.card}>
                  <div className={styles.sectionHeader}>
                    <div className={styles.sectionTitle}>Ордера</div>
                    <Link to={`/projects/${projectId}/purchases`}>Фактическая закупка »</Link>
                  </div>
                  <table className={`${styles.table} ${styles.rowClickable}`}>
                    <thead>
                      <tr>
                        <th>Поставщик</th>
                        <th>Статус</th>
                        <th>Товары</th>
                        <th>Доставка</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {orders.map((order) => {
                        const supplier = suppliers.find((s) => s.id === order.supplier_id);
                        return (
                          <tr key={order.id} onClick={() => navigate(`/orders/${order.id}`)}>
                            <td>{supplier?.name ?? order.supplier_id}</td>
                            <td>{order.status}</td>
                            <td>{formatMoney(order.total_amount)}</td>
                            <td>{formatMoney(order.delivery_fee)}</td>
                            <td onClick={(e) => e.stopPropagation()}>
                              <div className={styles.actionsCell}>
                                <Link to={`/orders/${order.id}`}>Открыть »</Link>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              <div className={styles.card}>
                <div className={styles.sectionHeader}>
                  <div className={styles.sectionTitle}>Спецификация материалов</div>
                </div>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th className={styles.numColHeader}>№</th>
                      <th>Материал</th>
                      <th>Количество</th>
                      <th>Ед.</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {groupItemsByCategory(project.items, materials).map((group) => (
                      <Fragment key={group.category ?? '__none__'}>
                        <tr className={styles.categoryRow}>
                          <td colSpan={5} className={styles.categoryCell}>
                            {group.category ?? 'Без категории'}
                          </td>
                        </tr>
                        {group.items.map(({ item, number }) => {
                          const material = materials.find((m) => m.id === item.material_id);
                          return (
                            <tr key={item.id}>
                              <td className={styles.numCell}>{number}</td>
                              <td>{material?.canonical_name ?? item.material_id}</td>
                              <td>
                                <input
                                  key={item.quantity}
                                  className={styles.input}
                                  style={{ width: '90px' }}
                                  type="number"
                                  min="1"
                                  step="1"
                                  defaultValue={item.quantity}
                                  onBlur={(e) => {
                                    const value = Number(e.target.value);
                                    if (value > 0) void handleQuantityChange(item, value);
                                    else e.target.value = String(item.quantity);
                                  }}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter') e.currentTarget.blur();
                                  }}
                                />
                              </td>
                              <td>{material?.unit ?? ''}</td>
                              <td>
                                <div className={styles.actionsCell}>
                                  <ConfirmButton
                                    label="Удалить"
                                    onConfirm={() => void handleRemoveItem(item)}
                                  />
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </Fragment>
                    ))}
                    <tr>
                      <td></td>
                      <td>
                        <MaterialCombobox
                          query={newMaterialQuery}
                          selected={newMaterial}
                          invalid={false}
                          onQueryChange={(query) => {
                            setNewMaterialQuery(query);
                            setNewMaterial(null);
                          }}
                          onSelect={(material) => {
                            setNewMaterial(material);
                            setNewMaterialQuery(material.canonical_name);
                          }}
                          onQuantityFocus={() => {}}
                        />
                      </td>
                      <td>
                        <input
                          className={styles.input}
                          style={{ width: '90px' }}
                          type="number"
                          min="1"
                          step="1"
                          placeholder="0"
                          value={newQuantity}
                          onChange={(e) => setNewQuantity(e.target.value)}
                        />
                      </td>
                      <td>{newMaterial?.unit ?? ''}</td>
                      <td>
                        <Button
                          variant="secondary"
                          disabled={!newMaterial || Number(newQuantity) <= 0 || addingItem}
                          onClick={() => void handleAddItem()}
                        >
                          + Добавить
                        </Button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

interface CategoryGroup {
  category: string | null;
  items: { item: ProjectItem; number: number }[];
}

/**
 * Groups project items by Material.category, preserving each category's
 * first-appearance order (not alphabetical — matches how the reference
 * layout ordered chapters by workflow, not name). Items whose material has
 * no category (or isn't loaded yet) fall into a single "Без категории"
 * group, always last regardless of where they'd otherwise sort — grouping
 * with the categorized items would bury the fact that they're missing one.
 * Numbering (`number`) is contiguous across all groups, 1-based.
 */
function groupItemsByCategory(items: ProjectItem[], materials: Material[]): CategoryGroup[] {
  const categoryById = new Map(materials.map((m) => [m.id, m.category]));
  const order: (string | null)[] = [];
  const byCategory = new Map<string | null, ProjectItem[]>();

  for (const item of items) {
    const category = categoryById.get(item.material_id) ?? null;
    if (!byCategory.has(category)) {
      byCategory.set(category, []);
      order.push(category);
    }
    byCategory.get(category)!.push(item);
  }

  const orderedCategories = [...order.filter((c) => c !== null), ...(byCategory.has(null) ? [null] : [])];

  let number = 0;
  return orderedCategories.map((category) => ({
    category,
    items: byCategory.get(category)!.map((item) => {
      number += 1;
      return { item, number };
    }),
  }));
}

function formatMoney(value: number): string {
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
