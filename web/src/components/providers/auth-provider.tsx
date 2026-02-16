"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import type { UserInfo } from "@/lib/types";
import {
  getToken,
  getUser,
  saveSession,
  clearSession,
  isAuthenticated as checkAuth,
} from "@/lib/auth";
import { authApi } from "@/lib/api-client";

interface AuthContextValue {
  user: UserInfo | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isAdmin: boolean;
  login: (apiKey: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<UserInfo | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Hydrate from cookie/localStorage on mount
  useEffect(() => {
    if (checkAuth()) {
      const cached = getUser();
      if (cached) {
        setUser(cached);
        setIsLoading(false);
        return;
      }
      // Token exists but no cached user — fetch /me
      authApi
        .me()
        .then((u) => setUser(u))
        .catch(() => {
          clearSession();
          setUser(null);
        })
        .finally(() => setIsLoading(false));
    } else {
      setIsLoading(false);
    }
  }, []);

  const login = useCallback(
    async (apiKey: string) => {
      const res = await authApi.login(apiKey);
      saveSession(res);
      setUser(res.user);
      router.push("/dashboard");
    },
    [router],
  );

  const logout = useCallback(() => {
    clearSession();
    setUser(null);
    router.push("/login");
  }, [router]);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user && !!getToken(),
        isAdmin: user?.role === "admin",
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
