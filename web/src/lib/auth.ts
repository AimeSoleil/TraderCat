import Cookies from "js-cookie";
import type { LoginResponse, UserInfo } from "./types";

const TOKEN_KEY = "tc_token";
const USER_KEY = "tc_user";

// ── Token storage ──

export function getToken(): string | null {
  return Cookies.get(TOKEN_KEY) ?? null;
}

export function setToken(token: string, expiresInSeconds: number) {
  Cookies.set(TOKEN_KEY, token, {
    expires: expiresInSeconds / 86400, // days
    sameSite: "lax",
  });
}

export function removeToken() {
  Cookies.remove(TOKEN_KEY);
}

// ── User info storage ──

export function getUser(): UserInfo | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as UserInfo;
  } catch {
    return null;
  }
}

export function setUser(user: UserInfo) {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function removeUser() {
  localStorage.removeItem(USER_KEY);
}

// ── Login / Logout ──

export function saveSession(res: LoginResponse) {
  setToken(res.access_token, res.expires_in);
  setUser(res.user);
}

export function clearSession() {
  removeToken();
  removeUser();
}

export function isAuthenticated(): boolean {
  return !!getToken();
}

export function isAdmin(): boolean {
  return getUser()?.role === "admin";
}
