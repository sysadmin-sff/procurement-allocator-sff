import { Fragment, useEffect, useState } from 'react';
import { templatesApi } from '../api/templates';
import type { ProjectTemplate } from '../api/types';
import { ApiError } from '../api/client';
import { useCurrentUser } from '../auth/AuthContext';
import { Button } from '../components/Button';
import { ConfirmButton } from '../components/ConfirmButton';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import { TemplateForm } from './templates/TemplateForm';
import { TemplateItemsPanel } from './templates/TemplateItemsPanel';
import styles from '../components/CrudScreen.module.css';

type Status = 'loading' | 'ready' | 'error' | 'forbidden';

function pluralizeItems(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return 'материал';
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'материала';
  return 'материалов';
}

export function ProjectTemplatesPage() {
  /* UI convenience only, not a security boundary — real enforcement is
     require_role("admin") on the backend router (ADR-0032 §2, ADR-0024 §4/§5). */
  const isAdmin = useCurrentUser().role === 'admin';
  const [templates, setTemplates] = useState<ProjectTemplate[]>([]);
  const [status, setStatus] = useState<Status>('loading');
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);

  useEffect(() => {
    void load();
  }, []);

  async function load() {
    setStatus('loading');
    setLoadError(null);
    try {
      const data = await templatesApi.list();
      setTemplates(data);
      setStatus('ready');
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setStatus('forbidden');
        return;
      }
      setLoadError(err);
      setStatus('error');
    }
  }

  function openCreate() {
    setActionError(null);
    setCreateOpen(true);
  }

  function closeCreate() {
    setCreateOpen(false);
  }

  async function handleCreate(payload: { name: string }) {
    setActionError(null);
    try {
      await templatesApi.create(payload);
      closeCreate();
      await load();
    } catch (err) {
      setActionError(err);
      throw err;
    }
  }

  async function handleRename(id: string, name: string) {
    setActionError(null);
    try {
      await templatesApi.rename(id, name);
      setRenamingId(null);
      await load();
    } catch (err) {
      setActionError(err);
      throw err;
    }
  }

  async function handleDelete(template: ProjectTemplate) {
    setActionError(null);
    try {
      await templatesApi.remove(template.id);
      if (expandedId === template.id) setExpandedId(null);
      await load();
    } catch (err) {
      setActionError(err);
    }
  }

  async function handleAddItem(templateId: string, materialId: string) {
    setActionError(null);
    try {
      const updated = await templatesApi.addItem(templateId, materialId);
      setTemplates((prev) => prev.map((t) => (t.id === templateId ? updated : t)));
    } catch (err) {
      setActionError(err);
      throw err;
    }
  }

  async function handleRemoveItem(templateId: string, itemId: string) {
    setActionError(null);
    try {
      const updated = await templatesApi.removeItem(templateId, itemId);
      setTemplates((prev) => prev.map((t) => (t.id === templateId ? updated : t)));
    } catch (err) {
      setActionError(err);
    }
  }

  function toggleExpanded(templateId: string) {
    setRenamingId(null);
    setExpandedId((current) => (current === templateId ? null : templateId));
  }

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <div className={styles.header}>
          <h1 className={styles.title}>Шаблоны проектов</h1>
          {status === 'ready' && !createOpen && (
            <Button variant="primary" disabled={!isAdmin} onClick={openCreate}>
              + Создать шаблон
            </Button>
          )}
        </div>

        <div className={styles.stack}>
          {actionError != null && (
            <ErrorBanner
              error={actionError}
              conflictMessage="Шаблон с таким названием уже существует."
            />
          )}

          {createOpen && (
            <div className={styles.card}>
              <div className={styles.sectionHeader}>
                <div className={styles.sectionTitle}>Новый шаблон</div>
              </div>
              <TemplateForm
                submitLabel="Создать шаблон"
                onCancel={closeCreate}
                onSubmit={handleCreate}
              />
            </div>
          )}

          <div className={styles.card}>
            {status === 'loading' && <div className={styles.loading}>Загрузка…</div>}

            {status === 'forbidden' && (
              <div className={styles.cardPadded}>
                <EmptyState
                  title="Недостаточно прав"
                  description="Этот раздел доступен только администраторам."
                />
              </div>
            )}

            {status === 'error' && (
              <div className={`${styles.cardPadded} ${styles.stack}`}>
                <ErrorBanner error={loadError} />
                <Button variant="secondary" onClick={() => void load()}>
                  Повторить
                </Button>
              </div>
            )}

            {status === 'ready' && templates.length === 0 && (
              <EmptyState
                title="Шаблонов пока нет"
                description="Создайте первый шаблон, чтобы сотрудники могли быстро подставлять стандартный набор материалов при создании проекта."
                action={
                  <Button variant="primary" disabled={!isAdmin} onClick={openCreate}>
                    Создать шаблон »
                  </Button>
                }
              />
            )}

            {status === 'ready' && templates.length > 0 && (
              <div className={styles.tableScroll}>
                <table className={`${styles.table} ${styles.rowClickable}`}>
                  <thead>
                    <tr>
                      <th className={styles.expandHeaderCell}></th>
                      <th>Название</th>
                      <th>Материалов</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {templates.map((template) => {
                      const expanded = expandedId === template.id;
                      const renaming = renamingId === template.id;
                      return (
                        <Fragment key={template.id}>
                          <tr onClick={() => toggleExpanded(template.id)}>
                            <td className={styles.expandCell}>
                              <span
                                className={`${styles.chevron} ${expanded ? styles.chevronExpanded : ''}`}
                                aria-hidden="true"
                              >
                                ▸
                              </span>
                            </td>
                            <td>
                              {renaming ? (
                                <div onClick={(e) => e.stopPropagation()}>
                                  <TemplateForm
                                    initialName={template.name}
                                    submitLabel="Сохранить"
                                    onCancel={() => setRenamingId(null)}
                                    onSubmit={(payload) => handleRename(template.id, payload.name)}
                                  />
                                </div>
                              ) : (
                                template.name
                              )}
                            </td>
                            <td>
                              {template.items.length} {pluralizeItems(template.items.length)}
                            </td>
                            <td>
                              <div
                                className={styles.actionsCell}
                                onClick={(e) => e.stopPropagation()}
                              >
                                {!renaming && (
                                  <Button
                                    variant="ghost"
                                    disabled={!isAdmin}
                                    onClick={() => setRenamingId(template.id)}
                                  >
                                    Переименовать
                                  </Button>
                                )}
                                <ConfirmButton
                                  label="Удалить"
                                  disabled={!isAdmin}
                                  onConfirm={() => handleDelete(template)}
                                />
                              </div>
                            </td>
                          </tr>
                          {expanded && (
                            <tr>
                              <td colSpan={4}>
                                <TemplateItemsPanel
                                  template={template}
                                  isAdmin={isAdmin}
                                  onAddItem={(materialId) => handleAddItem(template.id, materialId)}
                                  onRemoveItem={(itemId) => handleRemoveItem(template.id, itemId)}
                                />
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
