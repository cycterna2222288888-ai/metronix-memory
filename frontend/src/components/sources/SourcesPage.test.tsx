import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SourcesPage from './SourcesPage';
import { getConfig } from '@/api/config';
import { getSchemas, listConnections } from '@/api/connections';
import { useWorkspaceStore } from '@/shared';

vi.mock('@/api/config', () => ({
  getConfig: vi.fn(),
}));

vi.mock('@/api/connections', () => ({
  getSchemas: vi.fn(),
  listConnections: vi.fn(),
  createConnection: vi.fn(),
  updateConnection: vi.fn(),
  deleteConnection: vi.fn(),
  testConnection: vi.fn(),
  revealSecrets: vi.fn(),
  syncConnection: vi.fn(),
  listSyncLogs: vi.fn(),
  getLatestSyncLog: vi.fn(),
}));

vi.mock('@/api/upload', () => ({
  uploadFile: vi.fn(),
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SourcesPage />
    </QueryClientProvider>,
  );
}

describe('SourcesPage — public connector_types fallback (#300)', () => {
  beforeEach(() => {
    useWorkspaceStore.setState({
      active: {
        workspace_id: 'ws1',
        name: 'Workspace 1',
        created_at: '2026-01-01T00:00:00Z',
        user_id: 'u1',
        is_active: true,
      },
      workspaces: [],
      loading: false,
    });
    vi.mocked(listConnections).mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('enables Add Connection from the public connector_types list even when the authenticated schemas call fails, and step 2 shows an explicit error instead of an empty form', async () => {
    vi.mocked(getConfig).mockResolvedValue({
      plugins: [],
      connector_types: ['confluence', 'jira', 'notion'],
    });
    vi.mocked(getSchemas).mockRejectedValue(new Error('unauthorized'));

    const user = userEvent.setup();
    renderPage();

    const addButton = await screen.findByRole('button', { name: /add connection/i });
    await waitFor(() => expect(addButton).toBeEnabled());

    // Step 1: picker is populated from the public list despite the
    // authenticated schema call having failed.
    await user.click(addButton);
    const jiraOption = await screen.findByText('Jira');
    await user.click(jiraOption);

    // Step 2: must show a clear error, not a silently-empty form that
    // could be saved with no config.
    expect(
      await screen.findByText(/Couldn.t load configuration fields for Jira/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/schema request failed/i)).toBeInTheDocument();
    expect(screen.queryByText('Connection Name')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
  });

  it('recovers into the real form once schemas are retried successfully', async () => {
    vi.mocked(getConfig).mockResolvedValue({
      plugins: [],
      connector_types: ['jira'],
    });
    vi.mocked(getSchemas)
      .mockRejectedValueOnce(new Error('unauthorized'))
      .mockResolvedValueOnce({
        jira: {
          type: 'jira',
          label: 'Jira',
          category: 'connector',
          fields: [{ name: 'url', label: 'Jira URL', type: 'url', required: true }],
        },
      });

    const user = userEvent.setup();
    renderPage();

    const addButton = await screen.findByRole('button', { name: /add connection/i });
    await waitFor(() => expect(addButton).toBeEnabled());
    await user.click(addButton);
    await user.click(await screen.findByText('Jira'));

    // Two "Retry" buttons exist on screen at this point: the page-level
    // schema-error banner, and the dialog's step-2 error state. Click the
    // dialog's (rendered last in document order).
    const retryButtons = await screen.findAllByRole('button', { name: /retry/i });
    await user.click(retryButtons[retryButtons.length - 1]);

    expect(await screen.findByText('Connection Name')).toBeInTheDocument();
    expect(screen.getByText('Jira URL')).toBeInTheDocument();
  });

  it('keeps Add Channel disabled on schema failure — channels have no public fallback list', async () => {
    vi.mocked(getConfig).mockResolvedValue({ plugins: [], connector_types: ['jira'] });
    vi.mocked(getSchemas).mockRejectedValue(new Error('unauthorized'));

    renderPage();

    const addChannelButton = await screen.findByRole('button', { name: /add channel/i });
    await waitFor(() => expect(addChannelButton).toBeDisabled());
  });
});
