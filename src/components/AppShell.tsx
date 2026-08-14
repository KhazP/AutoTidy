import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useConfig } from "../state/ConfigProvider";
import { STATUS_LABEL, useEngine } from "../state/EngineProvider";
import { RulesView } from "../views/RulesView";
import { HistoryView } from "../views/HistoryView";
import { UndoView } from "../views/UndoView";
import { SettingsView } from "../views/SettingsView";
import { ConfirmDialog, type ConfirmRequest } from "./ConfirmDialog";
import { LogPane } from "./LogPane";
import {
  NavigationContext,
  VIEW_LABELS,
  type NavigationApi,
  type UnsavedWork,
  type ViewId,
} from "./Navigation";
import {
  IconHistory,
  IconPlay,
  IconRules,
  IconScan,
  IconSettings,
  IconStop,
  IconUndo,
  IconWarning,
} from "./icons";
import "./AppShell.css";

/**
 * The skip link's target. `<main>` carries this id and `tabindex="-1"` so the
 * link actually moves focus, not just the scroll position.
 */
const MAIN_ID = "main-content";

/*
 * HEADING CONVENTION — see the long-form note in styles/global.css.
 *
 * The shell itself owns no <h1>: each view is a page and renders exactly one,
 * so an extra shell-level h1 would produce two per document. The shell's own
 * regions are landmarks (<nav>, <main>) plus one <h2> for the log pane, which
 * sits after </main> so the outline reads h1 → h2 in DOM order.
 *
 *   h1  the view name           (view owns it, in .view__header)
 *   h2  a major region          (.section-title, .visually-hidden when the
 *                                region needs no visible label)
 *   h3  a sub-region            (.subsection-title)
 *   fieldset/legend             a group of form controls — preferred over a
 *                                heading, because <legend> is announced when
 *                                focus enters any control in the group
 *   Modal                       renders its title as h2; content inside a
 *                                dialog therefore starts at h3
 */

const NAV: Array<{ id: ViewId; label: string; icon: ReactNode }> = [
  { id: "rules", label: VIEW_LABELS.rules, icon: <IconRules /> },
  { id: "history", label: VIEW_LABELS.history, icon: <IconHistory /> },
  { id: "undo", label: VIEW_LABELS.undo, icon: <IconUndo /> },
  { id: "settings", label: VIEW_LABELS.settings, icon: <IconSettings /> },
];

export function AppShell() {
  const [view, setView] = useState<ViewId>("rules");
  const { config } = useConfig();
  const engine = useEngine();

  /*
   * Navigation, published to every view so a cross-view call to action can just
   * navigate instead of re-dispatching the shell's own keyboard shortcut at
   * `window`. It also owns the unsaved-changes gate: switching views unmounts
   * the whole view, and every view here uses a draft + explicit Save model, so
   * an unguarded sidebar click silently throws the user's edits away.
   */
  const [pendingNav, setPendingNav] = useState<{ to: ViewId; work: UnsavedWork } | null>(null);
  const unsaved = useRef(new Map<string, UnsavedWork>());
  const viewRef = useRef(view);
  viewRef.current = view;

  const setUnsavedWork = useCallback((id: string, work: UnsavedWork | null) => {
    if (work) unsaved.current.set(id, work);
    else unsaved.current.delete(id);
  }, []);

  const navigate = useCallback((next: ViewId) => {
    if (next === viewRef.current) return;
    const blocking = unsaved.current.values().next().value;
    if (blocking) {
      setPendingNav({ to: next, work: blocking });
      return;
    }
    setView(next);
  }, []);

  const navigation = useMemo<NavigationApi>(
    () => ({ view, navigate, setUnsavedWork }),
    [view, navigate, setUnsavedWork],
  );

  const navConfirm: ConfirmRequest | null = pendingNav
    ? {
        title: "Discard your unsaved changes?",
        tone: "danger",
        confirmLabel: `Discard and open ${VIEW_LABELS[pendingNav.to]}`,
        cancelLabel: "Stay here",
        body: (
          <div className="notice__body">
            <span className="notice__title">{pendingNav.work.what}</span>
            <span>
              Nothing has been written to config.json yet. Leaving this view throws these edits
              away — there is no way to get them back.
            </span>
          </div>
        ),
        onConfirm: () => {
          // The outgoing view unmounts, and its guard deregisters with it.
          setView(pendingNav.to);
        },
      }
    : null;

  const dryRun = config?.settings.dry_run_mode === true;
  const enabledRules = useMemo(
    () => config?.folders.filter((r) => r.enabled).length ?? 0,
    [config],
  );

  // Ctrl+1..4 to switch views — cheap parity with the old window's shortcuts.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (!event.ctrlKey || event.altKey || event.shiftKey) return;
      const index = Number(event.key) - 1;
      const target = NAV[index];
      if (target) {
        event.preventDefault();
        navigate(target.id);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  const running = engine.status !== "stopped";
  const statusClass = engine.connectionError
    ? "status status--error"
    : `status status--${engine.status}`;

  const statusDetail = engine.connectionError
    ? "Engine unreachable"
    : engine.activeScan
      ? `Run ${engine.activeScan.runId} · ${engine.activeScan.folders} folder${engine.activeScan.folders === 1 ? "" : "s"}`
      : engine.lastScan
        ? `Last scan: ${engine.lastScan.processed} processed, ${engine.lastScan.failed} failed`
        : `${enabledRules} rule${enabledRules === 1 ? "" : "s"} enabled`;

  return (
    <NavigationContext.Provider value={navigation}>
    <div className="shell">
      {/*
       * First stop in the tab order. Without it, reaching the Rules editor from
       * a cold page load means tabbing past the whole header and sidebar on
       * every view change.
       */}
      <a className="skip-link" href={`#${MAIN_ID}`}>
        Skip to main content
      </a>

      <header className="shell__header">
        <div className="brand">
          <span className="brand__name">AutoTidy</span>
        </div>

        {engine.connectionError ? (
          // Nothing will push a status change while the engine is unreachable,
          // so the indicator has to double as the way back.
          <button
            type="button"
            className={`${statusClass} status--button`}
            onClick={() => void engine.refreshStatus()}
            title={`${engine.connectionError}\n\nClick to retry.`}
          >
            <span className="status__dot" />
            <span className="status__label">Unavailable</span>
            <span className="status__detail">Engine unreachable — retry</span>
          </button>
        ) : (
          <div className={statusClass}>
            <span className="status__dot" />
            <span className="status__label">{STATUS_LABEL[engine.status]}</span>
            <span className="status__detail" title={statusDetail}>
              {statusDetail}
            </span>
          </div>
        )}

        <span className="spacer" />

        <div className="btn-row">
          <button
            type="button"
            className="btn"
            onClick={() => void engine.scan()}
            disabled={engine.busy || engine.status === "scanning" || engine.status === "stopping"}
            title="Run a single pass over every enabled folder now"
          >
            <IconScan />
            Scan now
          </button>
          {running ? (
            <button
              type="button"
              className="btn"
              onClick={() => void engine.stop()}
              disabled={engine.busy || engine.status === "stopping"}
            >
              <IconStop />
              Stop
            </button>
          ) : (
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => void engine.start()}
              disabled={engine.busy}
            >
              <IconPlay />
              {dryRun ? "Start dry run" : "Start monitoring"}
            </button>
          )}
        </div>
      </header>

      {dryRun && (
        <div className="dryrun" role="status">
          <IconWarning />
          <span>Dry run is ON.</span>
          <span className="dryrun__text">
            AutoTidy will log every action it would take and change nothing on disk. Turn this off
            in Settings when you are ready to let it run for real.
          </span>
          <span className="spacer" />
          <button type="button" className="btn btn--sm" onClick={() => navigate("settings")}>
            Open settings
          </button>
        </div>
      )}

      <div className="shell__body">
        <nav className="sidebar" aria-label="Sections">
          {NAV.map((item, index) => (
            <button
              key={item.id}
              type="button"
              className="sidebar__item"
              aria-current={view === item.id ? "page" : undefined}
              onClick={() => navigate(item.id)}
              title={`${item.label} (Ctrl+${index + 1})`}
            >
              {item.icon}
              {item.label}
              {item.id === "rules" && config && (
                <span className="sidebar__count">{config.folders.length}</span>
              )}
            </button>
          ))}
          <div className="sidebar__foot">
            {dryRun ? "Dry run active" : running ? "Engine running" : "Engine stopped"}
          </div>
        </nav>

        {/* tabIndex -1 makes this a valid destination for the skip link. */}
        <main className="shell__view" id={MAIN_ID} tabIndex={-1}>
          {view === "rules" && <RulesView />}
          {view === "history" && <HistoryView />}
          {view === "undo" && <UndoView />}
          {view === "settings" && <SettingsView />}
        </main>
      </div>

      <LogPane />

      <ConfirmDialog request={navConfirm} onClose={() => setPendingNav(null)} />
    </div>
    </NavigationContext.Provider>
  );
}
