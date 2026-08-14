import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

export type ToastTone = "info" | "success" | "warning" | "error";

export interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  body?: string;
}

interface ToastApi {
  toasts: Toast[];
  push: (tone: ToastTone, title: string, body?: string) => void;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

/** Errors stay until dismissed; everything else self-clears. */
const AUTO_DISMISS_MS: Record<ToastTone, number | null> = {
  info: 5000,
  success: 4000,
  warning: 8000,
  error: null,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (tone: ToastTone, title: string, body?: string) => {
      const id = nextId.current++;
      setToasts((current) => [...current.slice(-4), { id, tone, title, body }]);
      const timeout = AUTO_DISMISS_MS[tone];
      if (timeout !== null) {
        window.setTimeout(() => dismiss(id), timeout);
      }
    },
    [dismiss],
  );

  const value = useMemo<ToastApi>(() => ({ toasts, push, dismiss }), [toasts, push, dismiss]);
  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>;
}

export function useToasts(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToasts must be used inside <ToastProvider>");
  return ctx;
}
