/**
 * TypeScript mirror of the Rust IPC contract.
 *
 * These types are hand-maintained against `src-tauri/src/commands.rs` and the
 * serde shapes in `crates/autotidy-core`. Field names use the exact spellings
 * serde emits — the config types are snake_case because they round-trip the
 * user's real `config.json`, while the newer DTOs are camelCase via
 * `#[serde(rename_all = "camelCase")]`. The inconsistency is deliberate: the
 * config's wire format is fixed by backward compatibility, not by taste.
 */

// ---------------------------------------------------------------------------
// Config — snake_case, matches config.json on disk
// ---------------------------------------------------------------------------

export type Action = "move" | "copy" | "delete_to_trash" | "delete_permanently";
export type RuleLogic = "AND" | "OR";
export type NotificationLevel = "none" | "error" | "summary" | "all";

export interface Rule {
  path: string;
  age_days: number;
  pattern: string;
  rule_logic: RuleLogic;
  use_regex: boolean;
  action: Action;
  destination_folder: string;
  exclusions: string[];
  enabled: boolean;
  /** Unknown keys preserved verbatim across a round-trip. */
  [extra: string]: unknown;
}

export interface Settings {
  start_on_login: boolean;
  archive_path_template: string;
  schedule_type: string;
  interval_minutes: number;
  dry_run_mode: boolean;
  notification_level: NotificationLevel;
  hide_instructions: boolean;
  log_level: string;
  /** 0 = this folder only, matching 1.5.0's flat scan. */
  max_directory_depth: number;
  [extra: string]: unknown;
}

export interface Config {
  folders: Rule[];
  excluded_folders: string[];
  settings: Settings;
  /** Orphaned top-level blocks (e.g. `security`) preserved on round-trip. */
  [extra: string]: unknown;
}

// ---------------------------------------------------------------------------
// History & undo
// ---------------------------------------------------------------------------

export type Status = "SUCCESS" | "FAILURE" | "SKIPPED";

export interface HistoryRecord {
  original_path: string;
  action_taken: string;
  destination_path: string | null;
  /** Absent on the UNDO_MOVE records written by the 1.5.0 undo UI. */
  monitored_folder?: string;
  rule_pattern: string;
  rule_age_days: number;
  rule_use_regex: boolean;
  rule_action_config: string;
  status: Status;
  details: string;
  /** Empty on the 77 legacy records that predate run grouping. */
  run_id: string;
  severity: string;
  timestamp: string;
  copy_size?: number;
  copy_mtime?: number;
  [extra: string]: unknown;
}

export interface HistoryPage {
  records: HistoryRecord[];
  total: number;
  offset: number;
}

export interface RunSummary {
  run_id: string;
  start_time: string;
  action_count: number;
}

export interface BatchResult {
  run_id: string;
  success_count: number;
  failure_count: number;
  messages: string[];
}

// ---------------------------------------------------------------------------
// Engine
// ---------------------------------------------------------------------------

export type EngineStatus = "stopped" | "idle" | "scanning" | "stopping";
export type LogLevel = "info" | "warning" | "error";

export type EngineEvent =
  | { kind: "log"; level: LogLevel; message: string }
  | { kind: "statusChanged"; status: EngineStatus }
  | { kind: "scanStarted"; runId: string; folders: number }
  | {
      kind: "scanFinished";
      runId: string;
      processed: number;
      skipped: number;
      failed: number;
      dryRun: boolean;
    }
  | { kind: "notify"; category: string; title: string; message: string };

/** The Tauri event channel engine events arrive on. */
export const ENGINE_EVENT = "autotidy://engine" as const;

// ---------------------------------------------------------------------------
// Misc DTOs
// ---------------------------------------------------------------------------

export interface RulePreview {
  matches: string[];
  total: number;
  exampleDestination: string | null;
}

export interface AppInfo {
  version: string;
  configPath: string;
  historyPath: string;
  logPath: string;
  autostartEnabled: boolean;
  contextMenuRegistered: boolean;
}

export interface Vocabulary {
  actions: Action[];
  notificationLevels: NotificationLevel[];
  placeholders: string[];
}

/**
 * One Explorer folder-menu verb left behind by AutoTidy 1.x.
 *
 * 1.5.0 wrote these under `HKEY_CLASSES_ROOT`, which needed administrator
 * rights; 2.0 registers per-user instead, so its uninstaller cannot reach them.
 */
export interface StaleVerb {
  /** Registry key name, e.g. `AutoTidyAddTo`. */
  verb: string;
  /** Full key path, so the user can check it in regedit before agreeing. */
  key: string;
  /** The caption Explorer draws, when the key still carries one. */
  label: string | null;
  /** The command line it runs — a `python.exe` and a `main.py` that are gone. */
  command: string | null;
}

export interface StaleContextMenu {
  /** Empty on any machine that did not upgrade from 1.x. */
  verbs: StaleVerb[];
  /** Removal writes machine-wide, so unelevated it can only fail. */
  elevated: boolean;
}

export interface RuleTemplate {
  name: string;
  description: string;
  rules: Array<Partial<Rule> & { folder_to_watch?: string; file_pattern?: string }>;
}
