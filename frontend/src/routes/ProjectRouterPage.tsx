import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { projectsApi } from '../api/projects';
import type { ProjectWithItems } from '../api/types';
import { ErrorBanner } from '../components/ErrorBanner';
import { ProjectBuilderPage } from './ProjectBuilderPage';
import { ProjectDetailPage } from './ProjectDetailPage';
import styles from '../components/CrudScreen.module.css';

type Status = 'loading' | 'ready' | 'error';

/**
 * `/projects/:projectId` renders one of two screens depending on whether the
 * project has ever been calculated (see ADR-0004): a project with no
 * `latest_allocation_run` is still a draft under construction — it gets the
 * keyboard-first builder grid (autosaving). Once allocation has run at least
 * once, it gets the read/edit detail screen with the run summary.
 */
export function ProjectRouterPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [project, setProject] = useState<ProjectWithItems | null>(null);
  const [status, setStatus] = useState<Status>('loading');
  const [loadError, setLoadError] = useState<unknown>(null);

  useEffect(() => {
    if (!projectId) return;
    setStatus('loading');
    setLoadError(null);
    projectsApi
      .get(projectId)
      .then((data) => {
        setProject(data);
        setStatus('ready');
      })
      .catch((err) => {
        setLoadError(err);
        setStatus('error');
      });
  }, [projectId]);

  if (!projectId) {
    return <ErrorBanner error="Не указан проект." />;
  }

  if (status === 'loading') {
    return <div className={styles.loading}>Загрузка…</div>;
  }

  if (status === 'error' || !project) {
    return (
      <div className={styles.page}>
        <div className={styles.inner}>
          <ErrorBanner error={loadError} />
        </div>
      </div>
    );
  }

  if (project.latest_allocation_run == null) {
    return <ProjectBuilderPage projectId={projectId} initialProject={project} />;
  }

  return <ProjectDetailPage initialProject={project} />;
}
