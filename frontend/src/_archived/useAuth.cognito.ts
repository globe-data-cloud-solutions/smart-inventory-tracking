"use client";

// Archived (unused): called POST /auth/token with cognito_token, which was
// removed from the backend in 68b3cf8. Excluded from tsc via tsconfig.json.

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  clearToken,
  getCurrentUser,
  type JWTPayload,
  storeToken,
} from "@/lib/auth";

interface AuthState {
  user: JWTPayload | null;
  token: string | null;
  isLoading: boolean;
}

export function useAuth() {
  const [state, setState] = useState<AuthState>({
    user: null,
    token: null,
    isLoading: true,
  });

  useEffect(() => {
    const user = getCurrentUser();
    setState({ user, token: null, isLoading: false });
  }, []);

  const login = useCallback(async (cognitoToken: string) => {
    const resp = await api.post<{ access_token: string }>(
      "/api/v1/auth/token",
      { cognito_token: cognitoToken }
    );
    storeToken(resp.access_token);
    const user = getCurrentUser();
    setState({ user, token: resp.access_token, isLoading: false });
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setState({ user: null, token: null, isLoading: false });
  }, []);

  return { ...state, login, logout };
}
