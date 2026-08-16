import { AlertCircle } from 'lucide-react';
import { useAuthStore } from '@/shared';

export default function PasswordWarningBanner() {
  const mustChangePassword = useAuthStore((s) => s.mustChangePassword);

  if (!mustChangePassword) return null;

  return (
    <div className="flex items-center gap-2 border-b border-error/30 bg-error/10 px-4 py-2.5 text-sm text-error">
      <AlertCircle size={16} className="shrink-0" />
      <span>Your password must be changed before you can continue. Update it in Settings.</span>
    </div>
  );
}
