import { create } from "zustand";

export type NotifyKind = "success" | "warning" | "error";

export interface Notice {
  id: number;
  kind: NotifyKind;
  message: string;
}

interface NotifyState {
  notice: Notice | null;
  notify: (n: { kind: NotifyKind; message: string }) => void;
  dismiss: () => void;
}

let nextId = 1;

export const useNotifyStore = create<NotifyState>((set) => ({
  notice: null,
  notify: ({ kind, message }) => set({ notice: { id: nextId++, kind, message } }),
  dismiss: () => set({ notice: null }),
}));

/** Fire a global toast from anywhere (event handlers, async code). */
export function notify(n: { kind: NotifyKind; message: string }): void {
  useNotifyStore.getState().notify(n);
}

/** Auto-dismiss delay in ms; errors stay until closed. */
export const NOTIFY_TIMEOUT_MS: Record<NotifyKind, number | null> = {
  success: 4000,
  warning: 6000,
  error: null,
};
