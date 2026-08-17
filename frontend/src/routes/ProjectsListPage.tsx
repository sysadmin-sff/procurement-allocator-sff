import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { projectsApi } from '../api/projects';
import type { Project } from '../api/types';
import { Button } from '../components/Button';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import styles from '../components/CrudScreen.module.css';

type Status = 'loading' | 'ready' | 'error';

export function ProjectsListPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [status, setStatus] = useState<Status>('loading');
  const [loadError, setLoadError] = useState<unknown>(null);

  useEffect(() => {
    void load();
  }, []);

  async function load() {
    setStatus('loading');
    setLoadError(null);
    try {
      const data = await projectsApi.list();
      setProjects(data);
      setStatus('ready');
    } catch (err) {
      setLoadError(err);
      setStatus('error');
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <div className={styles.header}>
          <h1 className={styles.title}>Проекты</h1>
          <Button variant="primary" onClick={() => navigate('/projects/new')}>
            + Новый проект
          </Button>
        </div>

        <div className={styles.stack}>
          <div className={styles.card}>
            {status === 'loading' && <div className={styles.loading}>Загрузка…</div>}

            {status === 'error' && (
              <div className={`${styles.cardPadded} ${styles.stack}`}>
                <ErrorBanner error={loadError} />
                <Button variant="secondary" onClick={() => void load()}>
                  Повторить
                </Button>
              </div>
            )}

            {status === 'ready' && projects.length === 0 && (
              <EmptyState
                title="Проектов пока нет"
                description="Создайте первый проект, чтобы собрать спецификацию материалов и рассчитать закупку."
                action={
                  <Button variant="primary" onClick={() => navigate('/projects/new')}>
                    Создать проект »
                  </Button>
                }
              />
            )}

            {status === 'ready' && projects.length > 0 && (
              <table className={`${styles.table} ${styles.rowClickable}`}>
                <thead>
                  <tr>
                    <th>Название</th>
                    <th>Статус</th>
                    <th>Создан</th>
                  </tr>
                </thead>
                <tbody>
                  {projects.map((project) => (
                    <tr key={project.id} onClick={() => navigate(`/projects/${project.id}`)}>
                      <td>{project.title}</td>
                      <td>{project.status}</td>
                      <td>{formatDate(project.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });
}
