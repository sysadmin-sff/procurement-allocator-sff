import { Button } from './Button';
import styles from './ResponseAliasModal.module.css';

export interface ResponseAliasCandidateOption {
  /** OrderItem id — the radio value. */
  id: string;
  name: string;
  /** "8 × $62.10" — the numbers the employee compares against the extra line. */
  detail: string;
}

interface ResponseAliasModalProps {
  rawDescription: string;
  candidates: ResponseAliasCandidateOption[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Candidate preselected by suggestAliasPair, with its basis text
   * ("совпадает цена: $62.10") — null when there is no unique match. */
  suggestion: { id: string; basis: string } | null;
  /** 409 body's existing alias — switches the dialog to the replace step. */
  conflict: { canonical_name: string; created_at: string | null } | null;
  error: string | null;
  submitting: boolean;
  onConfirm: () => void;
  onForce: () => void;
  onCancel: () => void;
}

/** "Связать" dialog on the order-response review screen — see ADR-0046 §2.
 * Picks which "Отсутствует в ответе" item an "Лишнее" line really is; the
 * suggestion only preselects, nothing is written until "Связать"/"Заменить". */
export function ResponseAliasModal({
  rawDescription,
  candidates,
  selectedId,
  onSelect,
  suggestion,
  conflict,
  error,
  submitting,
  onConfirm,
  onForce,
  onCancel,
}: ResponseAliasModalProps) {
  return (
    <div className={styles.overlay} role="presentation">
      <div className={styles.modal} role="dialog" aria-modal="true" aria-labelledby="response-alias-title">
        <div id="response-alias-title" className={styles.title}>
          {conflict ? 'Связь уже существует' : 'Связать с позицией заказа'}
        </div>
        <div className={styles.rawDescription}>{rawDescription}</div>

        {conflict ? (
          <div className={styles.conflict}>
            Этот текст поставщика уже связан с: <strong>{conflict.canonical_name}</strong> (создано{' '}
            {conflict.created_at ? new Date(conflict.created_at).toLocaleDateString('ru-RU') : 'дата неизвестна'}).
            Заменить связь на выбранную позицию?
          </div>
        ) : candidates.length === 0 ? (
          <div className={styles.empty}>Нет позиций из каталога в «Отсутствует в ответе».</div>
        ) : (
          <ul className={styles.candidateList}>
            {candidates.map((candidate) => (
              <li key={candidate.id}>
                <label className={styles.candidate}>
                  <input
                    type="radio"
                    name="response-alias-candidate"
                    value={candidate.id}
                    checked={selectedId === candidate.id}
                    disabled={submitting}
                    onChange={() => onSelect(candidate.id)}
                  />
                  <span className={styles.candidateText}>
                    <span className={styles.candidateName}>{candidate.name}</span>
                    <span className={styles.candidateDetail}>{candidate.detail}</span>
                    {suggestion?.id === candidate.id && (
                      <span className={styles.suggestionBasis}>{suggestion.basis}</span>
                    )}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}

        {error != null && (
          <div className={styles.error} role="alert">
            {error}
          </div>
        )}

        <div className={styles.actions}>
          <Button variant="ghost" disabled={submitting} onClick={onCancel}>
            Отмена
          </Button>
          {conflict ? (
            <Button variant="danger" disabled={submitting} onClick={onForce}>
              Заменить
            </Button>
          ) : (
            <Button variant="primary" disabled={submitting || selectedId == null} onClick={onConfirm}>
              Связать
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
