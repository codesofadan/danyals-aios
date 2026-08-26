"use client";

// "Did that work?" — answered the same way everywhere.
//
// There was no toast system. Feedback after a mutation was one of five
// hand-rolled mechanisms: ~24 inline `mutation.isError &&` banners, six
// `setFlash(...)` + `setTimeout` pairs inside a single file, a `SavedFlash`
// component used by exactly one file, a `ToolActionResult` used by one
// directory — and, most often, nothing at all. `.mutate(` appears 78 times
// across the product; only 18 files attach an `onError`.
//
// The low-water mark was tasks/TaskManager.tsx, where a failed save rendered
// the two words "Save failed": no reason, no retry, no way to tell a permission
// problem from a dropped connection.
//
// TWO RULES THIS ENCODES:
//   1. A FAILURE DOES NOT AUTO-DISMISS. A success that vanishes after four
//      seconds is fine — the work is done and the screen already shows it. An
//      error that vanishes is a bug the operator never learns about, so errors
//      stay until dismissed.
//   2. AN ERROR CARRIES ITS REASON. `describeError` pulls the API's own message
//      off the thrown error rather than inventing "Something went wrong",
//      because the operator can act on "You do not have permission" and cannot
//      act on a shrug.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

export type ToastTone = "success" | "error" | "info";

export type Toast = {
  id: number;
  tone: ToastTone;
  message: string;
  /** Shown under the message — the API's own words, when it gave any. */
  detail?: string;
};

type ToastApi = {
  success: (message: string, detail?: string) => void;
  error: (message: string, detail?: string) => void;
  info: (message: string, detail?: string) => void;
  /** Convenience for the common `onError` shape. */
  fromError: (message: string, error: unknown) => void;
  dismiss: (id: number) => void;
};

const ToastContext = createContext<ToastApi | null>(null);

/** Successes clear themselves; failures do not. */
const AUTO_DISMISS_MS: Record<ToastTone, number | null> = {
  success: 4000,
  info: 6000,
  error: null,
};

/** The API's own reason, if the thrown thing carries one. */
export function describeError(error: unknown): string | undefined {
  if (!error) return undefined;
  if (typeof error === "string") return error;
  const e = error as { message?: unknown; status?: unknown };
  const message = typeof e.message === "string" ? e.message.trim() : "";
  const status = typeof e.status === "number" ? e.status : undefined;
  if (message && status) return `${message} (${status})`;
  if (message) return message;
  if (status) return `The server refused the request (${status}).`;
  return undefined;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const push = useCallback(
    (tone: ToastTone, message: string, detail?: string) => {
      const id = nextId.current++;
      setToasts((prev) => [...prev, { id, tone, message, detail }]);
      const ttl = AUTO_DISMISS_MS[tone];
      if (ttl !== null) {
        timers.current.set(
          id,
          setTimeout(() => dismiss(id), ttl),
        );
      }
    },
    [dismiss],
  );

  // Clear every pending timer on unmount, so a dismissed provider cannot call
  // setState afterwards.
  useEffect(() => {
    const pending = timers.current;
    return () => {
      pending.forEach(clearTimeout);
      pending.clear();
    };
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      success: (m, d) => push("success", m, d),
      error: (m, d) => push("error", m, d),
      info: (m, d) => push("info", m, d),
      fromError: (m, error) => push("error", m, describeError(error)),
      dismiss,
    }),
    [push, dismiss],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

const TONE: Record<ToastTone, { icon: string; colour: string }> = {
  success: { icon: "check_circle", colour: "var(--ok)" },
  error: { icon: "error", colour: "var(--crit)" },
  info: { icon: "info", colour: "var(--violet)" },
};

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: Toast[];
  onDismiss: (id: number) => void;
}) {
  if (toasts.length === 0) return null;
  return (
    <div
      style={{
        position: "fixed",
        right: "var(--s-7)",
        bottom: "var(--s-7)",
        zIndex: 1000,
        display: "flex",
        flexDirection: "column",
        gap: "var(--s-4)",
        maxWidth: 380,
      }}
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          // Errors interrupt; successes are announced politely.
          role={t.tone === "error" ? "alert" : "status"}
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: "var(--s-4)",
            padding: "var(--s-6) var(--s-7)",
            borderRadius: "var(--r-md)",
            border: "1px solid var(--line)",
            background: "var(--card)",
            boxShadow: "var(--e-3)",
          }}
        >
          <span
            className="material-symbols-rounded"
            aria-hidden="true"
            style={{ color: TONE[t.tone].colour, fontSize: 20 }}
          >
            {TONE[t.tone].icon}
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: "var(--fs-sm)", fontWeight: 700 }}>{t.message}</div>
            {t.detail ? (
              <div
                style={{
                  marginTop: "var(--s-1)",
                  fontSize: "var(--fs-xs)",
                  color: "var(--muted)",
                  lineHeight: 1.5,
                }}
              >
                {t.detail}
              </div>
            ) : null}
          </div>
          <button
            type="button"
            className="iconbtn"
            aria-label="Dismiss"
            onClick={() => onDismiss(t.id)}
          >
            <span className="material-symbols-rounded" aria-hidden="true">
              close
            </span>
          </button>
        </div>
      ))}
    </div>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used inside <ToastProvider>");
  }
  return ctx;
}
