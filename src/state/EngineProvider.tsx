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
import type { UnlistenFn } from "@tauri-apps/api/event";

import { engineStatus, onEngineEvent, scanNow, startMonitoring, stopMonitoring } from "../lib/api";
import { errorMessage } from "../lib/errors";
import type { EngineStatus, LogLevel } from "../lib/types";
import { useToasts } from "./ToastProvider";

export interface LogEntry {
  id: number;
  at: Date;
  level: LogLevel;
  message: string;
}

export interface ScanSummary {
  runId: string;
  processed: number;
  skipped: number;
  failed: number;
  dryRun: boolean;
  finishedAt: Date;
}

interface EngineApi {
  status: EngineStatus;
  /** Non-null when the engine could not be reached at all. */
  connectionError: string | null;
  busy: boolean;
  logs: LogEntry[];
  activeScan: { runId: string; folders: number } | null;
  lastScan: ScanSummary | null;
  start: () => Promise<void>;
  stop: () => Promise<void>;
  scan: () => Promise<void>;
  clearLogs: () => void;
  log: (level: LogLevel, message: string) => void;
  refreshStatus: () => Promise<void>;
  /** Bumped whenever a scan finishes, so history/undo views can refetch. */
  dataRevision: number;
}

const EngineContext = createContext<EngineApi | null>(null);

/** The log pane is a debugging aid, not an archive — the file log is the archive. */
const MAX_LOG_ENTRIES = 1000;

export function EngineProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<EngineStatus>("stopped");
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [activeScan, setActiveScan] = useState<{ runId: string; folders: number } | null>(null);
  const [lastScan, setLastScan] = useState<ScanSummary | null>(null);
  const [dataRevision, setDataRevision] = useState(0);

  const nextLogId = useRef(1);
  const { push } = useToasts();

  const appendLog = useCallback((level: LogLevel, message: string) => {
    setLogs((current) => {
      const next = [...current, { id: nextLogId.current++, at: new Date(), level, message }];
      return next.length > MAX_LOG_ENTRIES ? next.slice(next.length - MAX_LOG_ENTRIES) : next;
    });
  }, []);

  // A single top-level subscription. The engine pushes; nothing here polls.
  // `listen` resolves asynchronously, so a fast unmount (StrictMode's double
  // effect in dev, for one) has to be able to cancel the pending handle.
  useEffect(() => {
    let cancelled = false;
    let unlisten: UnlistenFn | undefined;

    onEngineEvent((event) => {
      switch (event.kind) {
        case "log":
          appendLog(event.level, event.message);
          break;
        case "statusChanged":
          setStatus(event.status);
          setConnectionError(null);
          if (event.status === "stopped" || event.status === "idle") setActiveScan(null);
          break;
        case "scanStarted":
          setActiveScan({ runId: event.runId, folders: event.folders });
          appendLog(
            "info",
            `Scan ${event.runId} started across ${event.folders} folder${event.folders === 1 ? "" : "s"}.`,
          );
          break;
        case "scanFinished": {
          setActiveScan(null);
          setLastScan({
            runId: event.runId,
            processed: event.processed,
            skipped: event.skipped,
            failed: event.failed,
            dryRun: event.dryRun,
            finishedAt: new Date(),
          });
          setDataRevision((n) => n + 1);
          appendLog(
            event.failed > 0 ? "warning" : "info",
            `Scan ${event.runId} finished — ${event.processed} processed, ${event.skipped} skipped, ` +
              `${event.failed} failed${event.dryRun ? " (dry run, nothing was changed)" : ""}.`,
          );
          break;
        }
        case "notify":
          push(event.category === "error" ? "error" : "info", event.title, event.message);
          appendLog(event.category === "error" ? "error" : "info", `${event.title}: ${event.message}`);
          break;
      }
    })
      .then((fn) => {
        if (cancelled) fn();
        else unlisten = fn;
      })
      .catch((err: unknown) => {
        appendLog("error", `Could not subscribe to engine events: ${errorMessage(err)}`);
      });

    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [appendLog, push]);

  const refreshStatus = useCallback(async () => {
    try {
      const next = await engineStatus();
      setStatus(next);
      setConnectionError(null);
    } catch (err) {
      setConnectionError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  const runCommand = useCallback(
    async (label: string, fn: () => Promise<void>) => {
      setBusy(true);
      try {
        await fn();
        setConnectionError(null);
        await refreshStatus();
      } catch (err) {
        const message = errorMessage(err);
        appendLog("error", `${label} failed: ${message}`);
        push("error", `${label} failed`, message);
      } finally {
        setBusy(false);
      }
    },
    [appendLog, push, refreshStatus],
  );

  const start = useCallback(() => runCommand("Start monitoring", startMonitoring), [runCommand]);
  const stop = useCallback(() => runCommand("Stop monitoring", stopMonitoring), [runCommand]);
  const scan = useCallback(() => runCommand("Scan now", scanNow), [runCommand]);
  const clearLogs = useCallback(() => setLogs([]), []);

  const value = useMemo<EngineApi>(
    () => ({
      status,
      connectionError,
      busy,
      logs,
      activeScan,
      lastScan,
      start,
      stop,
      scan,
      clearLogs,
      log: appendLog,
      refreshStatus,
      dataRevision,
    }),
    [
      status,
      connectionError,
      busy,
      logs,
      activeScan,
      lastScan,
      start,
      stop,
      scan,
      clearLogs,
      appendLog,
      refreshStatus,
      dataRevision,
    ],
  );

  return <EngineContext.Provider value={value}>{children}</EngineContext.Provider>;
}

export function useEngine(): EngineApi {
  const ctx = useContext(EngineContext);
  if (!ctx) throw new Error("useEngine must be used inside <EngineProvider>");
  return ctx;
}

export const STATUS_LABEL: Record<EngineStatus, string> = {
  stopped: "Stopped",
  idle: "Monitoring",
  scanning: "Scanning",
  stopping: "Stopping…",
};
