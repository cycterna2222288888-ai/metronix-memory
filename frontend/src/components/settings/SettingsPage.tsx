import { useState } from 'react';
import { KeyRound, Loader2 } from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import { changePassword, setToken, useAuthStore } from '@/shared';
import { ApiError } from '@/shared/api/errors';

export default function SettingsPage() {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [validationError, setValidationError] = useState('');

  const changePasswordMutation = useMutation({
    mutationFn: () => changePassword(currentPassword, newPassword),
    onSuccess: (res) => {
      setToken(res.token);
      useAuthStore.getState().setMustChangePassword(false);
      toast.success('Password updated');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    },
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setValidationError('');

    if (newPassword !== confirmPassword) {
      setValidationError('New passwords do not match.');
      return;
    }

    changePasswordMutation.mutate();
  }

  const mutationErrorMessage =
    changePasswordMutation.error instanceof ApiError
      ? changePasswordMutation.error.message
      : changePasswordMutation.isError
        ? 'Unable to change password.'
        : '';
  const errorMessage = validationError || mutationErrorMessage;

  const canSubmit =
    currentPassword.trim().length > 0 &&
    newPassword.trim().length > 0 &&
    confirmPassword.trim().length > 0 &&
    !changePasswordMutation.isPending;

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-md space-y-6">
        <div>
          <h1 className="text-xl font-semibold text-text">Settings</h1>
          <p className="mt-1 text-sm text-text-muted">Manage your account security.</p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="space-y-4 rounded-xl border border-border bg-surface p-6"
        >
          <div className="flex items-center gap-2 text-sm font-medium text-text">
            <KeyRound size={16} />
            Change password
          </div>

          <div>
            <label
              htmlFor="current-password"
              className="mb-1 block text-xs font-medium text-text-muted"
            >
              Current password
            </label>
            <input
              id="current-password"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
              className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text placeholder:text-text-dim focus:border-primary focus:outline-none transition-colors"
            />
          </div>

          <div>
            <label
              htmlFor="new-password"
              className="mb-1 block text-xs font-medium text-text-muted"
            >
              New password
            </label>
            <input
              id="new-password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
              className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text placeholder:text-text-dim focus:border-primary focus:outline-none transition-colors"
            />
          </div>

          <div>
            <label
              htmlFor="confirm-password"
              className="mb-1 block text-xs font-medium text-text-muted"
            >
              Confirm new password
            </label>
            <input
              id="confirm-password"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
              className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text placeholder:text-text-dim focus:border-primary focus:outline-none transition-colors"
            />
          </div>

          {errorMessage && (
            <p className="rounded-lg border border-error/20 bg-error/10 p-3 text-sm text-error">
              {errorMessage}
            </p>
          )}

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={!canSubmit}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-40"
            >
              {changePasswordMutation.isPending && (
                <Loader2 size={14} className="animate-spin" />
              )}
              Update password
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
