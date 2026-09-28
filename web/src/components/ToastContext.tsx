import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Alert, Box } from "@mui/material";

type ToastSeverity = "success" | "error" | "info" | "warning";

interface ToastState {
  message: string;
  severity: ToastSeverity;
  key: number;
}

interface ToastApi {
  show: (message: string, severity?: ToastSeverity) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastState[]>([]);

  function dismiss(key: number) {
    setToasts((prev) => prev.filter((t) => t.key !== key));
  }

  const show = useCallback((message: string, severity: ToastSeverity = "info") => {
    const key = Date.now() + Math.random();
    setToasts((prev) => [...prev.slice(-2), { message, severity, key }]);
    window.setTimeout(() => dismiss(key), severity === "error" ? 7000 : 4000);
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      show,
      success: (m) => show(m, "success"),
      error: (m) => show(m, "error"),
      info: (m) => show(m, "info"),
    }),
    [show],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <Box sx={{ position: "fixed", bottom: 16, right: 16, zIndex: 2000, display: "flex", flexDirection: "column", gap: 1 }}>
        {toasts.map((t) => (
          <Alert
            key={t.key}
            severity={t.severity}
            variant="filled"
            onClose={() => dismiss(t.key)}
            sx={{ width: "100%", minWidth: 260, boxShadow: 3, "& .MuiAlert-message": { overflowWrap: "anywhere" } }}
          >
            {t.message}
          </Alert>
        ))}
      </Box>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast debe usarse dentro de <ToastProvider>");
  return ctx;
}