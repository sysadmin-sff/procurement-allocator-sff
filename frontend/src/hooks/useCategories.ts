import { useEffect, useState } from 'react';
import { categoriesApi } from '../api/categories';
import type { Category } from '../api/types';

/** Shared data source for the category <select> on MaterialForm and
 * PriceListImportReviewPage's "new material" row — both must offer the same
 * list, not two independently-fetched copies (ADR-0034 задача, п.2/п.3). */
export function useCategories() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    categoriesApi
      .list()
      .then((data) => {
        if (!cancelled) setCategories(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { categories, loading, error };
}
