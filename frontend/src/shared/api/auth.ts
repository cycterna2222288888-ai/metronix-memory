import { apiFetch } from './client';
import type {
  ChangePasswordRequest,
  ChangePasswordResponse,
  LoginRequest,
  LoginResponse,
} from './types';

export async function login(email: string, password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password } satisfies LoginRequest),
  });
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<ChangePasswordResponse> {
  return apiFetch<ChangePasswordResponse>('/api/v1/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    } satisfies ChangePasswordRequest),
  });
}

export function getToken(): string | null {
  return sessionStorage.getItem('metronix_token');
}

export function setToken(token: string): void {
  sessionStorage.setItem('metronix_token', token);
}

export function clearToken(): void {
  sessionStorage.removeItem('metronix_token');
}

export function isAuthenticated(): boolean {
  return !!getToken();
}
