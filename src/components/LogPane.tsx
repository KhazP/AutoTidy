import { useEffect, useId, useMemo, useRef, useState } from "react";

import { formatClock } from "../lib/format";
import { useEngine } from "../state/EngineProvider";
import type { LogLevel } from "../lib/types";
import { IconChevronDown, IconChevronRight } from "./icons";

const PANE_STATE_KEY = "autotidy.logpane";

const LEVEL_FILTERS: Array<{ value: "all" | LogLevel; label: string }> = [
  { value: "all", label: "All levels" },
  { value: "info", label: "Info" },
  { value: "warning", label: "Warning" },
  { value: "error", label: "Error" },
];

/**
 * Live log, fed straight from the engine's event stream. 1.5.0 polled a
 * `queue.Queue` on a 250 ms QTimer; nothing here polls.
 */
export function LogPane() {
  const { logs, clearLogs } = useEngine();
  // The pane costs vertical space every view has to live without, so remember
  // whether the user wanted it.
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(PANE_STATE_KEY) !== "closed";
    } catch {
      return true;
    }
  });
  const [level, setLevel] = useState<"all" | LogLevel>("all");
  const [query, setQuery] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const pinnedToBottom = useRef(true);
  const headingId = useId();
  const listId = useId();

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return logs.filter(
      (entry) =>
        (level === "all" || entry.level === level) &&
        (q === "" || entry.message.toLowerCase().includes(q)),
    );
  }, [logs, level, query]);

  useEffect(() => {
    try {
      localStorage.setItem(PANE_STATE_KEY, open ? "open" : "closed");
    } catch {
      // Storage can be unavailable; the pane just forgets, which is harmless.
    }
  }, [open]);

  // Follow the tail unless the user has scrolled up to read something.
  useEffect(() => {
    const el = listRef.current;
    if (!el || !open || !pinnedToBottom.current) return;
    el.scrollTop = el.scrollHeight;
  }, [visible, open]);

  const errorCount = useMemo(() => logs.filter((l) => l.level === "error").length, [logs]);

  return (
    <section className="logpane" aria-labelledby={headingId}>
      <div className="logpane__bar">
        {/*
         * The disclosure button is the pane's heading, so the outline has an
         * entry for it (h1 for the view, then h2 here) without adding a second
         * line of chrome to a pane that is already competing for vertical space.
         */}
        <h2 className="logpane__heading" id={headingId}>
          <button
            type="button"
            className="logpane__toggle"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls={listId}
          >
            {open ? <IconChevronDown /> : <IconChevronRight />}
            Activity log
            <span className="logpane__count">({logs.length})</span>
            {errorCount > 0 && (
              <span className="badge badge--danger">
                {errorCount} error{errorCount === 1 ? "" : "s"}
              </span>
            )}
          </button>
        </h2>

        <span className="spacer" />

        {open && (
          <>
            <label className="visually-hidden" htmlFor="log-level">
              Filter log by level
            </label>
            <select
              id="log-level"
              className="select logpane__filter"
              value={level}
              onChange={(e) => setLevel(e.target.value as "all" | LogLevel)}
            >
              {LEVEL_FILTERS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>

            <label className="visually-hidden" htmlFor="log-search">
              Search log messages
            </label>
            <input
              id="log-search"
              type="search"
              className="input logpane__search"
              placeholder="Search log…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />

            <button
              type="button"
              className="btn btn--sm"
              onClick={() => void navigator.clipboard?.writeText(
                visible.map((e) => `${formatClock(e.at)}\t${e.level.toUpperCase()}\t${e.message}`).join("\n"),
              )}
              disabled={visible.length === 0}
            >
              Copy
            </button>
            <button
              type="button"
              className="btn btn--sm"
              onClick={clearLogs}
              disabled={logs.length === 0}
            >
              Clear
            </button>
          </>
        )}
      </div>

      {open && (
        <div
          className="logpane__list"
          id={listId}
          ref={listRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            pinnedToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
          }}
          role="log"
          aria-live="polite"
          aria-relevant="additions"
          tabIndex={0}
        >
          {visible.length === 0 ? (
            <p className="logpane__empty">
              {logs.length === 0
                ? "No activity yet. Start monitoring or run a scan to see engine output here."
                : "No log lines match the current filter."}
            </p>
          ) : (
            visible.map((entry) => (
              <div key={entry.id} className={`logline logline--${entry.level}`}>
                <span className="logline__time">{formatClock(entry.at)}</span>
                <span className="logline__level">{entry.level}</span>
                <span className="logline__text">{entry.message}</span>
              </div>
            ))
          )}
        </div>
      )}
    </section>
  );
}
