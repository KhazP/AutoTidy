/**
 * Display formatting. The history log stores UTC ISO timestamps; 1.5.0 showed
 * them raw in one table and reformatted them inconsistently in two others.
 * Everything here renders local time in one fixed shape.
 */

import type { Action, Status } from "./types";

const pad = (n: number) => String(n).padStart(2, "0");

/** `2026-08-14 15:04:21` in local time, or the raw string if unparseable. */
export function formatTimestamp(iso: string | undefined | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

/** `15:04:21` — used by the log pane, where the date is noise. */
export function formatClock(date: Date): string {
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function relativeTime(iso: string | undefined | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const secs = Math.round((Date.now() - d.getTime()) / 1000);
  if (secs < 45) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} day${days === 1 ? "" : "s"} ago`;
  return formatTimestamp(iso);
}

/** Last path segment, tolerant of both separators. */
export function basename(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, "");
  const idx = Math.max(trimmed.lastIndexOf("\\"), trimmed.lastIndexOf("/"));
  return idx === -1 ? trimmed : trimmed.slice(idx + 1);
}

/** Everything but the last segment. */
export function dirname(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, "");
  const idx = Math.max(trimmed.lastIndexOf("\\"), trimmed.lastIndexOf("/"));
  return idx <= 0 ? "" : trimmed.slice(0, idx);
}

export const ACTION_LABELS: Record<Action, string> = {
  move: "Move",
  copy: "Copy",
  delete_to_trash: "Delete to Recycle Bin",
  delete_permanently: "Delete permanently",
};

export const ACTION_ORDER: Action[] = [
  "move",
  "copy",
  "delete_to_trash",
  "delete_permanently",
];

export function actionLabel(action: string): string {
  if (action in ACTION_LABELS) return ACTION_LABELS[action as Action];
  return action;
}

/**
 * History records carry the engine's own uppercase constants
 * (`MOVED`, `SIMULATED_COPY`, `MOVE_ERROR_COLLISION`, …). Title-case them
 * rather than maintaining a map that will drift from the Rust side.
 */
export function historyActionLabel(raw: string): string {
  if (!raw) return "—";
  return raw
    .toLowerCase()
    .split("_")
    .map((word, i) => (i === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word))
    .join(" ");
}

export function statusTone(status: Status | string): "ok" | "danger" | "warn" | "" {
  switch (status) {
    case "SUCCESS":
      return "ok";
    case "FAILURE":
      return "danger";
    case "SKIPPED":
      return "warn";
    default:
      return "";
  }
}

export function pluralise(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** "1 hour", "90 minutes" — used by the interval field's derived hint. */
export function describeInterval(minutes: number): string {
  if (!Number.isFinite(minutes) || minutes <= 0) return "not scheduled";
  if (minutes < 60) return pluralise(minutes, "minute");
  const hours = minutes / 60;
  if (Number.isInteger(hours) && hours < 48) return pluralise(hours, "hour");
  const days = minutes / 1440;
  if (Number.isInteger(days)) return pluralise(days, "day");
  return `${minutes} minutes`;
}
