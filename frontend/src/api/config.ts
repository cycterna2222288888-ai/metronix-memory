import { apiFetch } from '@/shared';

export interface AppConfig {
  plugins: string[];
  /**
   * String keys of category="connector" entries from CONNECTOR_SCHEMAS.
   * Public (no auth), so no labels/fields here — pair with
   * `/api/v1/connections/schemas/` for the full form schema. Channel
   * types are not included; that list requires authentication.
   */
  connector_types: string[];
}

export async function getConfig(): Promise<AppConfig> {
  return apiFetch<AppConfig>('/api/v1/config');
}
