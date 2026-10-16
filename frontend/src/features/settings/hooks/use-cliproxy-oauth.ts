import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  cancelCliproxyOauth,
  getCliproxyOauthProviders,
  getCliproxyOauthStatus,
  startCliproxyOauth,
  submitCliproxyOauthCallback,
} from "@/features/settings/api";
import { CLIPROXY_ACCOUNTS_QUERY_KEY } from "@/features/settings/hooks/use-settings";
import { CliproxyOauthStateSchema, type CliproxyOauthState } from "@/features/settings/schemas";

const INITIAL_OAUTH_STATE: CliproxyOauthState = CliproxyOauthStateSchema.parse({
  provider: null,
  state: null,
  status: "idle",
  method: null,
  authorizationUrl: null,
  verificationUrl: null,
  userCode: null,
  intervalSeconds: null,
  expiresInSeconds: null,
  errorMessage: null,
});

export function useCliproxyOauth(open: boolean) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<CliproxyOauthState>(INITIAL_OAUTH_STATE);
  const stateRef = useRef<CliproxyOauthState>(INITIAL_OAUTH_STATE);
  const pollTimerRef = useRef<number | null>(null);
  const countdownTimerRef = useRef<number | null>(null);
  const providersQuery = useQuery({
    queryKey: ["settings", "cliproxy-oauth-providers"],
    queryFn: getCliproxyOauthProviders,
    enabled: open,
    staleTime: 60_000,
  });

  const setOauthState = useCallback((updater: CliproxyOauthState | ((current: CliproxyOauthState) => CliproxyOauthState)) => {
    setState((current) => {
      const next = typeof updater === "function" ? updater(current) : updater;
      stateRef.current = next;
      return next;
    });
  }, []);

  const clearPollTimer = useCallback(() => {
    if (pollTimerRef.current !== null) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const clearCountdownTimer = useCallback(() => {
    if (countdownTimerRef.current !== null) {
      window.clearInterval(countdownTimerRef.current);
      countdownTimerRef.current = null;
    }
  }, []);

  const poll = useCallback(async () => {
    const current = stateRef.current;
    if (!current.state) {
      return;
    }
    try {
      const status = await getCliproxyOauthStatus(current.state);
      if (status.status === "success") {
        setOauthState((prev) => CliproxyOauthStateSchema.parse({ ...prev, status: "success", errorMessage: null }));
        clearPollTimer();
        clearCountdownTimer();
        void queryClient.invalidateQueries({ queryKey: CLIPROXY_ACCOUNTS_QUERY_KEY });
        return;
      }
      if (status.status === "error") {
        setOauthState((prev) =>
          CliproxyOauthStateSchema.parse({
            ...prev,
            status: "error",
            errorMessage: status.errorMessage ?? "Sign-in failed",
          }),
        );
        clearPollTimer();
        clearCountdownTimer();
        return;
      }
      setOauthState((prev) => CliproxyOauthStateSchema.parse({ ...prev, status: "pending", errorMessage: null }));
    } catch (error) {
      clearPollTimer();
      clearCountdownTimer();
      setOauthState((prev) =>
        CliproxyOauthStateSchema.parse({
          ...prev,
          status: "error",
          errorMessage: error instanceof Error ? error.message : "Failed to check sign-in status",
        }),
      );
    }
  }, [clearCountdownTimer, clearPollTimer, queryClient, setOauthState]);

  const schedulePollTimer = useCallback((intervalSeconds: number | null) => {
    clearPollTimer();
    if (!intervalSeconds || intervalSeconds <= 0) {
      return;
    }
    pollTimerRef.current = window.setInterval(() => {
      void poll();
    }, intervalSeconds * 1000);
  }, [clearPollTimer, poll]);

  const scheduleCountdownTimer = useCallback((expiresInSeconds: number | null) => {
    clearCountdownTimer();
    if (!expiresInSeconds || expiresInSeconds <= 0) {
      return;
    }
    countdownTimerRef.current = window.setInterval(() => {
      setOauthState((prev) => {
        const nextExpires = Math.max(0, (prev.expiresInSeconds ?? 0) - 1);
        if (nextExpires === 0) {
          clearCountdownTimer();
        }
        return CliproxyOauthStateSchema.parse({ ...prev, expiresInSeconds: nextExpires });
      });
    }, 1000);
  }, [clearCountdownTimer, setOauthState]);

  const reset = useCallback(() => {
    const current = stateRef.current;
    if ((current.status === "pending" || current.status === "starting") && current.state) {
      void cancelCliproxyOauth(current.state).catch(() => undefined);
    }
    clearPollTimer();
    clearCountdownTimer();
    setOauthState(INITIAL_OAUTH_STATE);
  }, [clearCountdownTimer, clearPollTimer, setOauthState]);

  const start = useCallback(async (provider: string) => {
    clearPollTimer();
    clearCountdownTimer();
    setOauthState((prev) => CliproxyOauthStateSchema.parse({ ...prev, provider, status: "starting", errorMessage: null }));
    try {
      const response = await startCliproxyOauth(provider);
      const method = response.method === "device" ? "device" : "browser";
      const nextState = CliproxyOauthStateSchema.parse({
        provider: response.provider,
        state: response.state,
        status: "pending",
        method,
        authorizationUrl: response.authorizationUrl ?? null,
        verificationUrl: response.verificationUrl ?? null,
        userCode: response.userCode ?? null,
        intervalSeconds: response.intervalSeconds,
        expiresInSeconds: response.expiresInSeconds ?? null,
        errorMessage: null,
      });
      setOauthState(nextState);
      schedulePollTimer(nextState.intervalSeconds);
      scheduleCountdownTimer(nextState.expiresInSeconds);
      await poll();
    } catch (error) {
      clearPollTimer();
      clearCountdownTimer();
      setOauthState((prev) =>
        CliproxyOauthStateSchema.parse({
          ...prev,
          status: "error",
          errorMessage: error instanceof Error ? error.message : "Failed to start sign-in",
        }),
      );
      throw error;
    }
  }, [clearCountdownTimer, clearPollTimer, poll, scheduleCountdownTimer, schedulePollTimer, setOauthState]);

  const manualCallback = useCallback(async (callbackUrl: string) => {
    const current = stateRef.current;
    if (!current.state || !current.provider) {
      throw new Error("Sign-in has not started");
    }
    try {
      const response = await submitCliproxyOauthCallback({
        provider: current.provider,
        state: current.state,
        callbackUrl,
      });
      if (response.status === "error") {
        clearPollTimer();
        clearCountdownTimer();
        setOauthState((prev) =>
          CliproxyOauthStateSchema.parse({
            ...prev,
            status: "error",
            errorMessage: response.errorMessage ?? "Sign-in callback was rejected",
          }),
        );
        return;
      }
      setOauthState((prev) => CliproxyOauthStateSchema.parse({ ...prev, status: "pending", errorMessage: null }));
      await poll();
    } catch (error) {
      clearPollTimer();
      clearCountdownTimer();
      setOauthState((prev) =>
        CliproxyOauthStateSchema.parse({
          ...prev,
          status: "error",
          errorMessage: error instanceof Error ? error.message : "Failed to submit the sign-in callback",
        }),
      );
      throw error;
    }
  }, [clearCountdownTimer, clearPollTimer, poll, setOauthState]);

  useEffect(() => {
    return () => {
      clearPollTimer();
      clearCountdownTimer();
    };
  }, [clearCountdownTimer, clearPollTimer]);

  return {
    providers: providersQuery.data?.providers ?? [],
    providersLoading: providersQuery.isLoading,
    providersError: providersQuery.isError,
    state,
    start,
    manualCallback,
    reset,
  };
}
