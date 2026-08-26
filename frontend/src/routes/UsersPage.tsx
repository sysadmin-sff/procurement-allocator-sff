import { useEffect, useState } from 'react';
import { usersApi } from '../api/users';
import { ApiError } from '../api/client';
import type { User, UserRole } from '../api/types';
import { useCurrentUser } from '../auth/AuthContext';
import { Button } from '../components/Button';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import { UserForm } from './users/UserForm';
import styles from '../components/CrudScreen.module.css';

type Status = 'loading' | 'ready' | 'error' | 'forbidden';

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function UsersPage() {
  /* UI convenience only, not a security boundary — real enforcement is
     require_role("admin") on the backend router (ADR-0024 §4/§5). */
  const isAdmin = useCurrentUser().role === 'admin';
  const [users, setUsers] = useState<User[]>([]);
  const [status, setStatus] = useState<Status>('loading');
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  useEffect(() => {
    void load();
  }, []);

  async function load() {
    setStatus('loading');
    setLoadError(null);
    try {
      const data = await usersApi.list();
      setUsers(data);
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
    setFormOpen(true);
  }

  function closeForm() {
    setFormOpen(false);
  }

  async function handleCreate(payload: Parameters<typeof usersApi.create>[0]) {
    setActionError(null);
    try {
      await usersApi.create(payload);
      closeForm();
      await load();
    } catch (err) {
      setActionError(err);
      throw err;
    }
  }

  async function handleUpdate(user: User, changes: Partial<Pick<User, 'role' | 'is_active'>>) {
    setActionError(null);
    const after: User = { ...user, ...changes };
    try {
      await usersApi.update(user.id, user, after);
      setEditingId(null);
      await load();
    } catch (err) {
      setActionError(err);
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <div className={styles.header}>
          <h1 className={styles.title}>Пользователи</h1>
          {status === 'ready' && !formOpen && (
            <Button variant="primary" disabled={!isAdmin} onClick={openCreate}>
              + Добавить пользователя
            </Button>
          )}
        </div>

        <div className={styles.stack}>
          {actionError != null && (
            <ErrorBanner
              error={actionError}
              conflictMessage="Нельзя деактивировать единственного администратора."
            />
          )}

          {formOpen && (
            <div className={styles.card}>
              <div className={styles.sectionHeader}>
                <div className={styles.sectionTitle}>Новый пользователь</div>
              </div>
              <UserForm onCancel={closeForm} onSubmit={handleCreate} />
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

            {status === 'ready' && users.length === 0 && (
              <EmptyState
                title="Пользователей пока нет"
                description="Добавьте первого пользователя, чтобы он мог войти в систему."
                action={
                  <Button variant="primary" disabled={!isAdmin} onClick={openCreate}>
                    Добавить пользователя »
                  </Button>
                }
              />
            )}

            {status === 'ready' && users.length > 0 && (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Email</th>
                    <th>Имя</th>
                    <th>Роль</th>
                    <th>Статус</th>
                    <th>Последний вход</th>
                    <th>Создан</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => {
                    const editing = editingId === user.id;
                    return (
                      <tr key={user.id}>
                        <td>{user.email}</td>
                        <td>{user.name ?? <span className={styles.muted}>—</span>}</td>
                        <td>
                          {editing ? (
                            <select
                              className={styles.select}
                              value={user.role}
                              onChange={(e) =>
                                void handleUpdate(user, { role: e.target.value as UserRole })
                              }
                            >
                              <option value="employee">Сотрудник</option>
                              <option value="admin">Администратор</option>
                            </select>
                          ) : user.role === 'admin' ? (
                            'Администратор'
                          ) : (
                            'Сотрудник'
                          )}
                        </td>
                        <td>
                          <span
                            className={`${styles.badge} ${
                              user.is_active ? styles.badgeActive : styles.badgeHistorical
                            }`}
                          >
                            {user.is_active ? 'Активен' : 'Отключён'}
                          </span>
                        </td>
                        <td>
                          {user.last_login_at ? (
                            formatDateTime(user.last_login_at)
                          ) : (
                            <span className={styles.muted}>Ещё не входил</span>
                          )}
                        </td>
                        <td>{formatDateTime(user.created_at)}</td>
                        <td>
                          <div className={styles.actionsCell}>
                            {editing ? (
                              <Button variant="ghost" onClick={() => setEditingId(null)}>
                                Готово
                              </Button>
                            ) : (
                              <>
                                <Button
                                  variant="ghost"
                                  disabled={!isAdmin}
                                  onClick={() => setEditingId(user.id)}
                                >
                                  Изменить роль
                                </Button>
                                <Button
                                  variant="ghost"
                                  disabled={!isAdmin}
                                  onClick={() =>
                                    void handleUpdate(user, { is_active: !user.is_active })
                                  }
                                >
                                  {user.is_active ? 'Отключить' : 'Активировать'}
                                </Button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
