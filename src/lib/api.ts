/**
 * Typed wrappers over the Tauri IPC surface.
 *
 * One function per `#[tauri::command]` in `src-tauri/src/commands.rs`. Views
 * import from here rather than calling `invoke` directly, so a change to the
 * Rust signature breaks in exactly one file.
 */

import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import {
  ENGINE_EVENT,
  type AppInfo,
  type BatchResult,
  type Config,
  type EngineEvent,
  type EngineStatus,
  type HistoryPage,
  type HistoryRecord,
  type Rule,
  type RulePreview,
  type RuleTemplate,
  type RunSummary,
  type StaleContextMenu,
  type Vocabulary,
} from "./types";

// --- config ---------------------------------------------------------------

export const getConfig = () => invoke<Config>("get_config");
export const saveConfig = (config: Config) => invoke<void>("save_config", { config });
export const addRule = (path: string) => invoke<boolean>("add_rule", { path });
export const updateRule = (rule: Rule) => invoke<boolean>("update_rule", { rule });
export const removeRule = (path: string) => invoke<boolean>("remove_rule", { path });
export const addExcludedFolder = (path: string) =>
  invoke<boolean>("add_excluded_folder", { path });
export const removeExcludedFolder = (path: string) =>
  invoke<boolean>("remove_excluded_folder", { path });
export const ruleTemplates = () => invoke<RuleTemplate[]>("rule_templates");

// --- engine ---------------------------------------------------------------

export const engineStatus = () => invoke<EngineStatus>("engine_status");
export const startMonitoring = () => invoke<void>("start_monitoring");
export const stopMonitoring = () => invoke<void>("stop_monitoring");
export const scanNow = () => invoke<void>("scan_now");
export const previewRule = (rule: Rule, limit = 25) =>
  invoke<RulePreview>("preview_rule", { rule, limit });

// --- history & undo -------------------------------------------------------

export const historyPage = (offset: number, limit: number) =>
  invoke<HistoryPage>("history_page", { offset, limit });
export const listRuns = () => invoke<RunSummary[]>("list_runs");
export const runActions = (runId: string) =>
  invoke<HistoryRecord[]>("run_actions", { runId });
export const undoRun = (runId: string) => invoke<BatchResult>("undo_run", { runId });
export const undoOne = (record: HistoryRecord) => invoke<string>("undo_one", { record });

// --- platform -------------------------------------------------------------

export const appInfo = () => invoke<AppInfo>("app_info");
export const setAutostart = (enabled: boolean) => invoke<void>("set_autostart", { enabled });
export const setContextMenu = (enabled: boolean) =>
  invoke<void>("set_context_menu", { enabled });
/** Purely a read: what AutoTidy 1.x left in the machine-wide registry. */
export const staleContextMenu = () => invoke<StaleContextMenu>("stale_context_menu");
export const removeStaleContextMenu = () => invoke<void>("remove_stale_context_menu");
export const revealInExplorer = (path: string) =>
  invoke<void>("reveal_in_explorer", { path });
export const importConfig = (path: string) => invoke<Config>("import_config", { path });
export const exportConfig = (path: string) => invoke<void>("export_config", { path });
export const vocabulary = () => invoke<Vocabulary>("vocabulary");

// --- events ---------------------------------------------------------------

/**
 * Subscribe to the engine's event stream.
 *
 * This replaces 1.5.0's polled `queue.Queue` + `QTimer`: the engine pushes, so
 * the log pane updates as work happens rather than on the next tick.
 */
export function onEngineEvent(handler: (event: EngineEvent) => void): Promise<UnlistenFn> {
  return listen<EngineEvent>(ENGINE_EVENT, (e) => handler(e.payload));
}
