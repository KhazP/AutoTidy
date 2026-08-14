/**
 * Pure helpers over the config shapes.
 *
 * The single rule that governs this file: `Config`, `Rule` and `Settings` all
 * carry index signatures because the real config.json holds ~28 orphaned keys
 * plus a `security` block that must survive a round-trip. Every function here
 * therefore SPREADS the original object and overrides named fields. Nothing
 * rebuilds a config object from scratch — doing so would silently delete the
 * user's data the next time they pressed Save.
 */

import type { Action, Config, NotificationLevel, Rule, RuleTemplate, Settings } from "./types";

// ---------------------------------------------------------------- defaults --

/** Mirrors `Settings::default()` in autotidy-core / 1.5.0's ConfigManager. */
export const DEFAULT_SETTINGS: Settings = {
  start_on_login: false,
  archive_path_template: "_Cleanup/{YYYY}-{MM}-{DD}",
  schedule_type: "interval",
  interval_minutes: 60,
  dry_run_mode: false,
  notification_level: "all",
  hide_instructions: false,
  log_level: "INFO",
  max_directory_depth: 0,
};

export const NOTIFICATION_LEVELS: Array<{ value: NotificationLevel; label: string; hint: string }> =
  [
    { value: "none", label: "None", hint: "Never show desktop notifications." },
    { value: "error", label: "Errors only", hint: "Notify when an operation fails." },
    { value: "summary", label: "Scan summaries", hint: "One notification per completed scan." },
    { value: "all", label: "All activity", hint: "Notify for every logged step." },
  ];

export const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;

/** Fallback when the `vocabulary` command is unavailable. */
export const FALLBACK_PLACEHOLDERS = [
  "YYYY",
  "MM",
  "DD",
  "FILENAME",
  "EXT",
  "ORIGINAL_FOLDER_NAME",
] as const;

export const PLACEHOLDER_HELP: Record<string, string> = {
  YYYY: "Four-digit year at the time the file is filed",
  MM: "Two-digit month",
  DD: "Two-digit day of month",
  FILENAME: "File name without its extension",
  EXT: "File extension, including the leading dot",
  ORIGINAL_FOLDER_NAME: "Name of the monitored folder the file came from",
};

// -------------------------------------------------------------------- rules --

export function newRule(path: string): Rule {
  return {
    path,
    age_days: 0,
    pattern: "*.*",
    rule_logic: "OR",
    use_regex: false,
    action: "move",
    destination_folder: "",
    exclusions: [],
    enabled: true,
  };
}

export function findRule(config: Config | null, path: string | null): Rule | undefined {
  if (!config || !path) return undefined;
  return config.folders.find((r) => r.path === path);
}

/** True when the two rules differ in any field the editor can touch. */
export function ruleDiffers(a: Rule, b: Rule): boolean {
  return (
    a.age_days !== b.age_days ||
    a.pattern !== b.pattern ||
    a.rule_logic !== b.rule_logic ||
    a.use_regex !== b.use_regex ||
    a.action !== b.action ||
    a.destination_folder !== b.destination_folder ||
    a.enabled !== b.enabled ||
    a.exclusions.length !== b.exclusions.length ||
    a.exclusions.some((v, i) => v !== b.exclusions[i])
  );
}

/**
 * Plain-English restatement of a rule. 1.5.0's best idea was showing the user
 * their rule as a sentence instead of making them re-derive it from five
 * widgets; it is carried over verbatim in spirit.
 */
export function describeRule(rule: Rule): string {
  if (!rule.enabled) {
    return "This rule is off. Its settings are kept, but files here are left alone.";
  }

  const clauses: string[] = [];
  if (rule.age_days > 0) {
    clauses.push(`are at least ${rule.age_days} day${rule.age_days === 1 ? "" : "s"} old`);
  }
  const pattern = rule.pattern.trim();
  const trivialGlob = !rule.use_regex && (pattern === "" || pattern === "*" || pattern === "*.*");
  if (!trivialGlob) {
    clauses.push(
      rule.use_regex
        ? `match the regular expression “${pattern}”`
        : `match the pattern “${pattern}”`,
    );
  }

  const condition =
    clauses.length === 0
      ? "Every file in this folder"
      : `Files that ${clauses.join(rule.rule_logic === "AND" ? " and " : " or ")}`;

  const dest = rule.destination_folder.trim();
  let outcome: string;
  switch (rule.action) {
    case "move":
      outcome = dest ? `will be moved to “${dest}”` : "will be moved using the archive template";
      break;
    case "copy":
      outcome = dest ? `will be copied to “${dest}”` : "will be copied using the archive template";
      break;
    case "delete_to_trash":
      outcome = "will be sent to the Recycle Bin";
      break;
    case "delete_permanently":
      outcome = "will be permanently erased and cannot be recovered";
      break;
  }

  return `${condition} ${outcome}.`;
}

export function actionUsesDestination(action: Action): boolean {
  return action === "move" || action === "copy";
}

export function isIrreversible(action: Action): boolean {
  return action === "delete_permanently";
}

// ---------------------------------------------------------- config mutation --

/**
 * Replace one rule in-place, preserving every other rule and every unknown
 * top-level key. Used for the whole-config save path.
 */
export function withRule(config: Config, rule: Rule): Config {
  const exists = config.folders.some((r) => r.path === rule.path);
  return {
    ...config,
    folders: exists
      ? config.folders.map((r) => (r.path === rule.path ? { ...r, ...rule } : r))
      : [...config.folders, rule],
  };
}

export function withSettings(config: Config, patch: Partial<Settings>): Config {
  return { ...config, settings: { ...config.settings, ...patch } };
}

// ---------------------------------------------------------------- templates --

function asNumber(value: unknown, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function asString(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

function asBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

const KNOWN_ACTIONS: readonly string[] = [
  "move",
  "copy",
  "delete_to_trash",
  "delete_permanently",
];

/**
 * Template entries are loose: 1.5.0's RULE_TEMPLATES used `folder_to_watch`,
 * `file_pattern` and `days_older_than` where the saved rule uses `path`,
 * `pattern` and `age_days`. Normalise into a real Rule, dropping the aliases so
 * they don't get written back into config.json as junk keys.
 */
export function ruleFromTemplate(entry: RuleTemplate["rules"][number]): Rule | null {
  const { folder_to_watch, file_pattern, ...rest } = entry;
  const path = asString(rest.path ?? folder_to_watch, "");
  if (!path) return null;

  const rawAction = asString(rest.action, "move");
  const action = (KNOWN_ACTIONS.includes(rawAction) ? rawAction : "move") as Action;
  const logic = rest.rule_logic === "AND" ? "AND" : "OR";

  // `days_older_than` only exists on legacy templates, so it comes through the
  // index signature as `unknown`.
  const legacyAge = rest["days_older_than"];
  const exclusions = Array.isArray(rest.exclusions)
    ? rest.exclusions.filter((e): e is string => typeof e === "string")
    : [];

  // Carry any unknown template keys through, minus the legacy aliases we have
  // already folded into their modern equivalents.
  const carried: Record<string, unknown> = { ...rest };
  delete carried["days_older_than"];

  return {
    ...carried,
    path,
    age_days: Math.max(0, asNumber(rest.age_days ?? legacyAge, 0)),
    pattern: asString(rest.pattern ?? file_pattern, "*.*"),
    rule_logic: logic,
    use_regex: asBoolean(rest.use_regex, false),
    action,
    destination_folder: asString(rest.destination_folder, ""),
    exclusions,
    enabled: asBoolean(rest.enabled, true),
  };
}

export function templateRules(template: RuleTemplate): Rule[] {
  return template.rules
    .map(ruleFromTemplate)
    .filter((r): r is Rule => r !== null);
}

// -------------------------------------------------- archive path templates --

const DANGEROUS_CHARS = [";", "|", "&", "`"];

/**
 * Client-side mirror of `autotidy-core::template::validate`, so the field can
 * complain before the user saves. The backend still validates; this is a
 * courtesy, not a security boundary.
 */
export function validateArchiveTemplate(
  template: string,
  allowed: readonly string[],
): string | null {
  if (template.trim() === "") return null; // empty falls back to the default

  const normalised = template.replace(/\\/g, "/");
  if (normalised.split("/").some((part) => part === "..")) {
    return "Template must not contain '..' path traversal components.";
  }

  for (const ch of DANGEROUS_CHARS) {
    if (template.includes(ch)) {
      return `Template contains a disallowed character: '${ch}'`;
    }
  }

  const opens = (template.match(/\{/g) ?? []).length;
  const closes = (template.match(/\}/g) ?? []).length;
  if (opens !== closes) return "Template has unbalanced { } braces.";

  for (const match of template.matchAll(/\{([^}]*)\}/g)) {
    const name = match[1] ?? "";
    if (!allowed.includes(name)) {
      return `Unknown placeholder {${name}}. Allowed: ${allowed.join(", ")}`;
    }
  }

  return null;
}

/**
 * Renders a sample destination for the template so the user can see the shape
 * without running a scan. Deliberately synthetic — the real path is resolved by
 * the engine.
 */
export function previewArchiveTemplate(template: string): string {
  const effective = template.trim() === "" ? DEFAULT_SETTINGS.archive_path_template : template;
  const now = new Date();
  const values: Record<string, string> = {
    YYYY: String(now.getFullYear()),
    MM: pad2(now.getMonth() + 1),
    DD: pad2(now.getDate()),
    FILENAME: "report",
    EXT: ".pdf",
    ORIGINAL_FOLDER_NAME: "Downloads",
  };

  let rendered = effective.replace(/\{([^}]*)\}/g, (whole, name: string) =>
    name in values ? (values[name] as string) : whole,
  );
  rendered = rendered.replace(/\//g, "\\");

  const hasFileName = effective.includes("{FILENAME}") || effective.includes("{EXT}");
  const base = "C:\\Users\\You\\Downloads";
  const isAbsolute = /^[a-zA-Z]:[\\/]/.test(rendered) || rendered.startsWith("\\\\");
  const full = isAbsolute ? rendered : `${base}\\${rendered.replace(/^[\\/]+/, "")}`;
  return hasFileName ? full : `${full.replace(/[\\]+$/, "")}\\report.pdf`;
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

// -------------------------------------------------------------- undo policy --

/**
 * The engine can only reverse a move (put it back) or a copy (delete the
 * duplicate). Everything else — trashed files, permanent deletes, dry-run
 * simulations, error records and prior undos — is terminal. 1.5.0 only told the
 * user this *after* they confirmed; here it drives the disabled state.
 */
export function undoability(actionTaken: string, status: string): {
  undoable: boolean;
  reason: string;
} {
  const action = actionTaken.toUpperCase();
  if (status !== "SUCCESS") {
    return { undoable: false, reason: `Only successful actions can be undone (this one is ${status.toLowerCase()}).` };
  }
  if (action === "MOVED") return { undoable: true, reason: "Moves the file back to its original path." };
  if (action === "COPIED") return { undoable: true, reason: "Deletes the copy, after verifying it is unchanged." };
  if (action.startsWith("SIMULATED")) {
    return { undoable: false, reason: "Dry run — nothing happened on disk, so there is nothing to undo." };
  }
  if (action.includes("PERMANENT")) {
    return { undoable: false, reason: "Permanently deleted files cannot be recovered." };
  }
  if (action.includes("TRASH")) {
    return { undoable: false, reason: "Restore this from the Recycle Bin instead." };
  }
  if (action.startsWith("UNDO")) {
    return { undoable: false, reason: "This record is itself an undo." };
  }
  return { undoable: false, reason: `Undo is not supported for ${actionTaken}.` };
}
