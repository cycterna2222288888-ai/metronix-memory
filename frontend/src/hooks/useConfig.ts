import { useCallback, useEffect } from 'react';
import { getConfig } from '@/api/config';
import { useConfigStore } from '@/stores/config';

/**
 * Loads the public /api/v1/config response into useConfigStore on mount.
 * Safe to call from multiple components — state is shared, so only the
 * first mount's fetch matters in practice.
 */
export function useConfig() {
  const config = useConfigStore((s) => s.config);
  const loading = useConfigStore((s) => s.loading);
  const error = useConfigStore((s) => s.error);
  const setConfig = useConfigStore((s) => s.setConfig);
  const setLoading = useConfigStore((s) => s.setLoading);
  const setError = useConfigStore((s) => s.setError);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getConfig();
      setConfig(res);
      setLoading(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load config');
      setLoading(false);
    }
  }, [setConfig, setLoading, setError]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { config, loading, error, refresh };
}
