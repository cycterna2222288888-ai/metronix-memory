import { create } from 'zustand';
import type { AppConfig } from '@/api/config';

interface ConfigState {
  config: AppConfig | null;
  loading: boolean;
  error: string | null;
  setConfig: (config: AppConfig) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

/**
 * Global store for the public /api/v1/config response (plugins,
 * connector_types). Mirrors the useWorkspaceStore pattern: state lives
 * here, fetching/refetching is driven by the useConfig hook.
 */
export const useConfigStore = create<ConfigState>((set) => ({
  config: null,
  loading: true,
  error: null,
  setConfig: (config) => set({ config, error: null }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
}));
