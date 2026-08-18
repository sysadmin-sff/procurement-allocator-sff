import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { materialsApi } from '../api/materials';
import { projectsApi } from '../api/projects';
import type { Material, ProjectItem, ProjectWithItems } from '../api/types';
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
      loadMaterialsOnly();
      return;
    }
    void load(projectId);
  }, [projectId, initialProject]);

  async function loadMaterialsOnly() {
    setStatus('loading');
    setLoadError(null);
    try {
      const materialsData = await materialsApi.list();
      setMaterials(materialsData);
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
      const [projectData, materialsData] = await Promise.all([
        projectsApi.get(id),
        materialsApi.list(),
      ]);
      setProject(projectData);
      setMaterials(materialsData);
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

  if (!projectId) {
    return <ErrorBanner error="Не указан проект." />;
  }

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <div className={styles.header}>
          <h1 className={styles.title}>{project?.title ?? 'Проект'}</h1>
          {status === 'ready' && project && (
            <Button
              variant="primary"
              onClick={() => navigate(`/projects/${projectId}/allocation`)}
            >
              {project.latest_allocation_run ? 'Пересчитать закупку »' : 'Рассчитать закупку »'}
            </Button>
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

              <div className={styles.card}>
                <div className={styles.sectionHeader}>
                  <div className={styles.sectionTitle}>Спецификация материалов</div>
                </div>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Материал</th>
                      <th>Количество</th>
                      <th>Ед.</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {project.items.map((item) => {
                      const material = materials.find((m) => m.id === item.material_id);
                      return (
                        <tr key={item.id}>
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
                    <tr>
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

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
