import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { open as openDialog, save as saveDialog } from "@tauri-apps/plugin-dialog";

import {
  appInfo,
  exportConfig,
  importConfig,
  removeStaleContextMenu,
  revealInExplorer,
  setAutostart,
  setContextMenu,
  staleContextMenu,
  vocabulary,
} from "../lib/api";
import {
  DEFAULT_SETTINGS,
  FALLBACK_PLACEHOLDERS,
  LOG_LEVELS,
  NOTIFICATION_LEVELS,
  PLACEHOLDER_HELP,
  previewArchiveTemplate,
  validateArchiveTemplate,
} from "../lib/config";
import { errorMessage } from "../lib/errors";
import { describeInterval, formatClock } from "../lib/format";
import type {
  AppInfo,
  Config,
  NotificationLevel,
  Settings,
  StaleContextMenu,
  Vocabulary,
} from "../lib/types";
import { useConfig } from "../state/ConfigProvider";
import { useToasts } from "../state/ToastProvider";
import { ConfirmDialog, type ConfirmRequest } from "../components/ConfirmDialog";
import { Modal } from "../components/Modal";
import { EmptyState, ErrorNotice, Field, Loading } from "../components/common";
import { IconCheck, IconExternal, IconWarning } from "../components/icons";
import "./SettingsView.css";

/**
 * Only the keys this form owns. Saving patches these over the live settings
 * object, so `hide_instructions`, `start_on_login` and any key the UI has never
 * heard of survive untouched.
 */
interface SettingsDraft {
  schedule_type: string;
  interval_minutes: number;
  dry_run_mode: boolean;
  archive_path_template: string;
  notification_level: NotificationLevel;
  log_level: string;
  max_directory_depth: number;
}

const DRAFT_KEYS: Array<keyof SettingsDraft> = [
  "schedule_type",
  "interval_minutes",
  "dry_run_mode",
  "archive_path_template",
  "notification_level",
  "log_level",
  "max_directory_depth",
];

/** Used by the danger-zone confirmation, so it can name each field it resets. */
const DRAFT_LABELS: Record<keyof SettingsDraft, string> = {
  schedule_type: "Schedule type",
  interval_minutes: "Interval (minutes)",
  dry_run_mode: "Dry run mode",
  archive_path_template: "Archive path template",
  notification_level: "Notification level",
  log_level: "Log level",
  max_directory_depth: "Maximum folder depth",
};

const DEFAULT_DRAFT: SettingsDraft = {
  schedule_type: DEFAULT_SETTINGS.schedule_type,
  interval_minutes: DEFAULT_SETTINGS.interval_minutes,
  dry_run_mode: DEFAULT_SETTINGS.dry_run_mode,
  archive_path_template: DEFAULT_SETTINGS.archive_path_template,
  notification_level: DEFAULT_SETTINGS.notification_level,
  log_level: DEFAULT_SETTINGS.log_level,
  max_directory_depth: DEFAULT_SETTINGS.max_directory_depth,
};

function draftFromSettings(s: Settings): SettingsDraft {
  return {
    schedule_type: s.schedule_type,
    interval_minutes: s.interval_minutes,
    dry_run_mode: s.dry_run_mode,
    archive_path_template: s.archive_path_template,
    notification_level: s.notification_level,
    log_level: s.log_level,
    max_directory_depth: s.max_directory_depth,
  };
}

function formatSettingValue(value: unknown): string {
  if (typeof value === "boolean") return value ? "On" : "Off";
  if (value === "" || value === null || value === undefined) return "(empty)";
  return String(value);
}

/** Draft save: explicit, staged, one button. */
type SaveState =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved"; at: Date }
  | { kind: "error"; message: string };

/** Windows integration switches: applied the moment they are flipped. */
type ApplyState =
  | { kind: "idle" }
  | { kind: "applying" }
  | { kind: "applied"; message: string; at: Date }
  | { kind: "failed"; message: string };

export function SettingsView() {
  const { config, loading, error, reload, patchSettings, replaceConfig } = useConfig();
  const { push } = useToasts();

  const [draft, setDraft] = useState<SettingsDraft | null>(null);
  const [saveState, setSaveState] = useState<SaveState>({ kind: "idle" });

  const [info, setInfo] = useState<AppInfo | null>(null);
  const [infoError, setInfoError] = useState<string | null>(null);
  const [vocab, setVocab] = useState<Vocabulary | null>(null);

  const [autostartOn, setAutostartOn] = useState<boolean | null>(null);
  const [contextMenuOn, setContextMenuOn] = useState<boolean | null>(null);
  const [autostartState, setAutostartState] = useState<ApplyState>({ kind: "idle" });
  const [contextMenuState, setContextMenuState] = useState<ApplyState>({ kind: "idle" });

  /** Leftovers from AutoTidy 1.x. `null` until detection has answered. */
  const [stale, setStale] = useState<StaleContextMenu | null>(null);
  const [staleState, setStaleState] = useState<ApplyState>({ kind: "idle" });

  const [pendingImport, setPendingImport] = useState<{ path: string; config: Config } | null>(null);
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);

  // The native <dialog> hands focus back to whatever opened it — unless that
  // control has since been disabled (restoring defaults disables its own
  // button). Fall back to the save action, which is the next step anyway.
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const saveButtonRef = useRef<HTMLButtonElement>(null);

  const ids = {
    interval: useId(),
    schedule: useId(),
    template: useId(),
    notify: useId(),
    log: useId(),
    depth: useId(),
    danger: useId(),
  };

  // Hydrate the draft once, and re-hydrate only when it is not dirty.
  useEffect(() => {
    if (!config) return;
    const fromConfig = draftFromSettings(config.settings);
    setDraft((current) => current ?? fromConfig);
  }, [config]);

  const loadInfo = useCallback(async () => {
    try {
      const next = await appInfo();
      setInfo(next);
      setAutostartOn(next.autostartEnabled);
      setContextMenuOn(next.contextMenuRegistered);
      setInfoError(null);
    } catch (err) {
      setInfoError(errorMessage(err));
    }
    // Separate `try`, because this one is advisory. If the 1.x probe fails we
    // show nothing rather than blanking a section whose switches work — the
    // startup log still carries the warning either way.
    try {
      setStale(await staleContextMenu());
    } catch {
      setStale(null);
    }
  }, []);

  useEffect(() => {
    void loadInfo();
    // Placeholders are served by the engine; the static list is the fallback.
    void vocabulary()
      .then(setVocab)
      .catch(() => setVocab(null));
  }, [loadInfo]);

  useEffect(() => {
    if (confirmRequest !== null) return;
    const origin = returnFocusRef.current;
    returnFocusRef.current = null;
    if (!origin) return;
    const usable = origin.isConnected && !(origin instanceof HTMLButtonElement && origin.disabled);
    (usable ? origin : saveButtonRef.current)?.focus();
  }, [confirmRequest]);

  const placeholders: readonly string[] = vocab?.placeholders ?? FALLBACK_PLACEHOLDERS;

  const dirty = useMemo(() => {
    if (!config || !draft) return false;
    return DRAFT_KEYS.some((key) => draft[key] !== config.settings[key]);
  }, [config, draft]);

  const templateError = useMemo(
    () => (draft ? validateArchiveTemplate(draft.archive_path_template, placeholders) : null),
    [draft, placeholders],
  );

  /** Exactly what "Restore defaults" would change, current value → default. */
  const defaultsDiff = useMemo(() => {
    if (!draft) return [];
    return DRAFT_KEYS.flatMap((key) =>
      draft[key] === DEFAULT_DRAFT[key]
        ? []
        : [
            {
              key,
              label: DRAFT_LABELS[key],
              from: formatSettingValue(draft[key]),
              to: formatSettingValue(DEFAULT_DRAFT[key]),
            },
          ],
    );
  }, [draft]);

  const saving = saveState.kind === "saving";

  const patchDraft = useCallback((patch: Partial<SettingsDraft>) => {
    setDraft((current) => (current ? { ...current, ...patch } : current));
    // A fresh edit invalidates the previous outcome, but never interrupts a
    // save that is still in flight.
    setSaveState((current) =>
      current.kind === "saved" || current.kind === "error" ? { kind: "idle" } : current,
    );
  }, []);

  function openConfirm(request: ConfirmRequest) {
    returnFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setConfirmRequest(request);
  }

  async function handleSave() {
    if (!draft || templateError) return;
    setSaveState({ kind: "saving" });
    try {
      // A partial patch, spread over the live settings by the provider — this is
      // what keeps unmodelled keys alive across a save.
      await patchSettings({ ...draft });
      setSaveState({ kind: "saved", at: new Date() });
      push("success", "Settings saved", "Written to config.json.");
    } catch (err) {
      const message = errorMessage(err);
      setSaveState({ kind: "error", message });
      push("error", "Could not save settings", message);
    }
  }

  function handleRevert() {
    if (!config) return;
    setDraft(draftFromSettings(config.settings));
    setSaveState({ kind: "idle" });
  }

  function applyDefaults() {
    setDraft(DEFAULT_DRAFT);
    setSaveState({ kind: "idle" });
    push(
      "info",
      "Defaults loaded into the form",
      "Nothing has been written yet — press Save settings to keep them, or Revert to back out.",
    );
  }

  function askRestoreDefaults() {
    openConfirm({
      title: "Restore default settings?",
      tone: "danger",
      confirmLabel: "Restore defaults",
      body: (
        <div className="settings__confirm">
          <p>
            This puts {pluraliseFields(defaultsDiff.length)} on the Settings page back to AutoTidy's
            defaults:
          </p>
          <table className="settings__diff">
            <caption className="visually-hidden">Settings that will change</caption>
            <thead>
              <tr>
                <th scope="col">Setting</th>
                <th scope="col">Now</th>
                <th scope="col">Default</th>
              </tr>
            </thead>
            <tbody>
              {defaultsDiff.map((row) => (
                <tr key={row.key}>
                  <th scope="row">{row.label}</th>
                  <td className="settings__diff-from">{row.from}</td>
                  <td className="settings__diff-to">{row.to}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="settings__confirm-keep">
            <strong>Nothing else is touched.</strong> Your monitored folders and their rules, your
            global exclusions, the two Windows integration switches, your history and your undo log
            all stay exactly as they are.
          </p>
          <p className="settings__confirm-keep">
            This only fills in the form. Nothing is written to <code>config.json</code> until you
            press <strong>Save settings</strong>, and <strong>Revert</strong> undoes it before then.
          </p>
        </div>
      ),
      onConfirm: applyDefaults,
    });
  }

  async function toggleAutostart(next: boolean) {
    setAutostartState({ kind: "applying" });
    try {
      await setAutostart(next);
      setAutostartOn(next);
      // Keep the config record in step with the OS state.
      await patchSettings({ start_on_login: next });
      const message = next ? "AutoTidy will start at login" : "Login startup disabled";
      setAutostartState({ kind: "applied", message, at: new Date() });
      push("success", message, "Saved — this one did not need the Save button.");
    } catch (err) {
      const message = errorMessage(err);
      setAutostartState({ kind: "failed", message });
      push("error", "Could not change the startup setting", message);
      await loadInfo();
    }
  }

  async function toggleContextMenu(next: boolean) {
    setContextMenuState({ kind: "applying" });
    try {
      await setContextMenu(next);
      setContextMenuOn(next);
      const message = next ? "Explorer menu entries added" : "Explorer menu entries removed";
      setContextMenuState({ kind: "applied", message, at: new Date() });
      push("success", message, "You may need to restart Explorer for the change to show up.");
    } catch (err) {
      const message = errorMessage(err);
      setContextMenuState({ kind: "failed", message });
      push("error", "Could not change the Explorer menu", message);
      await loadInfo();
    }
  }

  /**
   * Delete the 1.x entries, then re-detect rather than assume.
   *
   * The re-read is the point: a `DeleteRegKey` that returned success while the
   * menu items survived would otherwise close the notice and tell the user the
   * problem was solved. The notice goes away because they are gone, not
   * because we asked for them to be.
   */
  async function removeStale() {
    setStaleState({ kind: "applying" });
    try {
      await removeStaleContextMenu();
      const next = await staleContextMenu();
      setStale(next);
      if (next.verbs.length > 0) {
        const message = `${next.verbs.length} of them are still registered.`;
        setStaleState({ kind: "failed", message });
        push("error", "Some entries could not be removed", message);
        return;
      }
      setStaleState({ kind: "idle" });
      push(
        "success",
        "Old AutoTidy 1.x menu entries removed",
        "You may need to restart Explorer before the folder right-click menu catches up.",
      );
    } catch (err) {
      const message = errorMessage(err);
      setStaleState({ kind: "failed", message });
      push("error", "Could not remove the old entries", message);
    }
  }

  async function handleExport() {
    try {
      const path = await saveDialog({
        title: "Export AutoTidy configuration",
        defaultPath: "autotidy-config.json",
        filters: [{ name: "JSON", extensions: ["json"] }],
      });
      if (typeof path !== "string") return;
      await exportConfig(path);
      push("success", "Configuration exported", path);
    } catch (err) {
      push("error", "Export failed", errorMessage(err));
    }
  }

  async function handleImport() {
    try {
      const path = await openDialog({
        title: "Import AutoTidy configuration",
        multiple: false,
        filters: [{ name: "JSON", extensions: ["json"] }],
      });
      if (typeof path !== "string") return;
      // `importConfig` parses without saving, so the user can confirm first.
      const parsed = await importConfig(path);
      setPendingImport({ path, config: parsed });
    } catch (err) {
      push("error", "Could not read that file", errorMessage(err));
    }
  }

  async function applyImport() {
    if (!pendingImport) return;
    try {
      await replaceConfig(pendingImport.config);
      setDraft(null); // re-hydrate from the imported settings
      setSaveState({ kind: "idle" });
      setPendingImport(null);
      push("success", "Configuration imported", pendingImport.path);
    } catch (err) {
      push("error", "Import failed", errorMessage(err));
    }
  }

  if (loading && !config) return <Loading label="Reading configuration…" />;

  if (!config || !draft) {
    return (
      <div className="view">
        <div className="view__scroll">
          <ErrorNotice
            title="Could not load your configuration"
            message={error ?? "Configuration is unavailable."}
            onRetry={() => void reload()}
          />
        </div>
      </div>
    );
  }

  const saveBarState = saving
    ? "saving"
    : saveState.kind === "error"
      ? "error"
      : dirty
        ? "dirty"
        : saveState.kind === "saved"
          ? "saved"
          : "clean";

  const saveBarText = saving
    ? "Saving to config.json…"
    : saveState.kind === "error"
      ? "Not saved. Your changes are still here — see the message at the top of the page."
      : dirty
        ? templateError
          ? "Unsaved changes. Fix the archive path template before you can save."
          : "Unsaved changes. Nothing is written to config.json until you save."
        : saveState.kind === "saved"
          ? `Saved to config.json at ${formatClock(saveState.at)}.`
          : "No unsaved changes.";

  return (
    <div className="view">
      <div className="view__header">
        <div className="view__heading">
          <h1 className="page-title">Settings</h1>
          <p className="page-subtitle">How AutoTidy runs and where it puts things.</p>
        </div>
        <div className="view__actions">
          <span className="settings__version">
            {info ? `AutoTidy ${info.version}` : "AutoTidy"}
          </span>
        </div>
      </div>

      <div className="view__scroll">
        <div className="settings">
          {saveState.kind === "error" && (
            <ErrorNotice
              title="Could not save settings"
              message={saveState.message}
              onRetry={() => void handleSave()}
              retryLabel="Try saving again"
            />
          )}

          {/* ------------------------------------------------------ dry run */}
          <section className={draft.dry_run_mode ? "dryrun-card" : "dryrun-card dryrun-card--off"}>
            <SwitchField
              label="Dry run mode"
              hint={
                draft.dry_run_mode
                  ? "AutoTidy logs the action it would have taken for each matching file and leaves your files exactly where they are. Turn this off when you trust your rules."
                  : "AutoTidy will move, copy and delete files for real. Turn dry run on if you want to watch what a new rule would do first."
              }
              checked={draft.dry_run_mode}
              onChange={(dry_run_mode) => patchDraft({ dry_run_mode })}
            />
            {draft.dry_run_mode && !config.settings.dry_run_mode && (
              <p className="field__hint" style={{ marginTop: 8 }}>
                Not active until you save.
              </p>
            )}
            {!draft.dry_run_mode && config.settings.dry_run_mode && (
              <div className="notice notice--warn" style={{ marginTop: 8 }}>
                <IconWarning />
                <div className="notice__body">
                  <span className="notice__title">You are about to arm AutoTidy for real</span>
                  <span>
                    After saving, the next scan will actually move, copy or delete matching files.
                    Worth previewing your rules first.
                  </span>
                </div>
              </div>
            )}
          </section>

          {/* --------------------------------------------------- scheduling */}
          <fieldset className="fieldset">
            <legend>Scheduling</legend>
            <div className="grid-2">
              <Field
                label="Schedule type"
                htmlFor={ids.schedule}
                hint="Interval is the only mode the engine currently implements."
              >
                <select
                  id={ids.schedule}
                  className="select"
                  value={draft.schedule_type}
                  onChange={(e) => patchDraft({ schedule_type: e.target.value })}
                >
                  <option value="interval">Every N minutes</option>
                  {draft.schedule_type !== "interval" && (
                    <option value={draft.schedule_type}>{draft.schedule_type}</option>
                  )}
                </select>
              </Field>

              <Field
                label="Interval (minutes)"
                htmlFor={ids.interval}
                hint={`Scans run ${describeInterval(draft.interval_minutes)} apart while monitoring is on.`}
              >
                <input
                  id={ids.interval}
                  className="input input--number"
                  type="number"
                  min={1}
                  max={10080}
                  step={1}
                  value={draft.interval_minutes}
                  onChange={(e) => {
                    const parsed = Number(e.target.value);
                    patchDraft({
                      interval_minutes: Number.isFinite(parsed)
                        ? Math.min(10080, Math.max(1, Math.trunc(parsed)))
                        : 1,
                    });
                  }}
                />
              </Field>
            </div>
          </fieldset>

          {/* ---------------------------------------------------- scanning */}
          <fieldset className="fieldset">
            <legend>Scanning</legend>
            <Field
              label="Maximum folder depth"
              htmlFor={ids.depth}
              hint={
                draft.max_directory_depth === 0
                  ? "0 scans only the monitored folder itself, matching the behaviour of AutoTidy 1.5.0."
                  : `Descends up to ${draft.max_directory_depth} level${draft.max_directory_depth === 1 ? "" : "s"} of subfolders below each monitored folder.`
              }
            >
              <input
                id={ids.depth}
                className="input input--number"
                type="number"
                min={0}
                max={32}
                step={1}
                value={draft.max_directory_depth}
                onChange={(e) => {
                  const parsed = Number(e.target.value);
                  patchDraft({
                    max_directory_depth: Number.isFinite(parsed)
                      ? Math.min(32, Math.max(0, Math.trunc(parsed)))
                      : 0,
                  });
                }}
              />
            </Field>
          </fieldset>

          {/* --------------------------------------------------- archiving */}
          <fieldset className="fieldset">
            <legend>Archiving</legend>
            <Field
              label="Archive path template"
              htmlFor={ids.template}
              error={templateError}
              hint="Used when a rule has no destination folder of its own. Relative paths resolve inside the monitored folder."
            >
              <input
                id={ids.template}
                className="input input--mono"
                type="text"
                value={draft.archive_path_template}
                aria-invalid={templateError !== null}
                placeholder={DEFAULT_SETTINGS.archive_path_template}
                onChange={(e) => patchDraft({ archive_path_template: e.target.value })}
              />
            </Field>

            <p className="template-preview" aria-live="polite">
              {templateError
                ? "Fix the template to see a preview."
                : `Example: ${previewArchiveTemplate(draft.archive_path_template)}`}
            </p>

            <dl className="placeholders">
              {placeholders.map((name) => (
                <div key={name} style={{ display: "contents" }}>
                  <dt>{`{${name}}`}</dt>
                  <dd>{PLACEHOLDER_HELP[name] ?? "Supported by the engine."}</dd>
                </div>
              ))}
            </dl>
          </fieldset>

          {/* --------------------------------------- notifications & logging */}
          <fieldset className="fieldset">
            <legend>Notifications and logging</legend>
            <div className="grid-2">
              <Field
                label="Notification level"
                htmlFor={ids.notify}
                hint={
                  NOTIFICATION_LEVELS.find((l) => l.value === draft.notification_level)?.hint ?? ""
                }
              >
                <select
                  id={ids.notify}
                  className="select"
                  value={draft.notification_level}
                  onChange={(e) =>
                    patchDraft({ notification_level: e.target.value as NotificationLevel })
                  }
                >
                  {(vocab?.notificationLevels ?? NOTIFICATION_LEVELS.map((l) => l.value)).map(
                    (level) => (
                      <option key={level} value={level}>
                        {NOTIFICATION_LEVELS.find((l) => l.value === level)?.label ?? level}
                      </option>
                    ),
                  )}
                </select>
              </Field>

              <Field
                label="Log level"
                htmlFor={ids.log}
                hint="Controls how much detail reaches autotidy.log. Takes effect on the next start."
              >
                <select
                  id={ids.log}
                  className="select"
                  value={draft.log_level}
                  onChange={(e) => patchDraft({ log_level: e.target.value })}
                >
                  {LOG_LEVELS.map((level) => (
                    <option key={level} value={level}>
                      {level}
                    </option>
                  ))}
                  {!LOG_LEVELS.includes(draft.log_level as (typeof LOG_LEVELS)[number]) && (
                    <option value={draft.log_level}>{draft.log_level}</option>
                  )}
                </select>
              </Field>
            </div>
          </fieldset>

          {/* ------------------------------------------ windows integration */}
          <fieldset className="fieldset">
            <legend>Windows integration</legend>
            {infoError ? (
              <ErrorNotice
                title="Could not read the current integration state"
                message={infoError}
                onRetry={() => void loadInfo()}
              />
            ) : (
              <>
                <p className="fieldset__lead">
                  These two are saved the moment you switch them — they change Windows itself, so
                  they are not part of <strong>Save settings</strong> at the bottom of the page.
                </p>
                <div className="switchlist">
                  <SwitchField
                    label="Start AutoTidy when I sign in"
                    hint="Launches minimised to the system tray."
                    checked={autostartOn ?? false}
                    disabled={autostartState.kind === "applying" || autostartOn === null}
                    onChange={(next) => void toggleAutostart(next)}
                    status={<ApplyStatus state={autostartState} />}
                  />
                  <SwitchField
                    label="Add “Add to AutoTidy” to the Explorer folder menu"
                    hint="Right-click any folder to start monitoring it or add it to the global exclusions. Registered for your account only — no administrator prompt."
                    checked={contextMenuOn ?? false}
                    disabled={contextMenuState.kind === "applying" || contextMenuOn === null}
                    onChange={(next) => void toggleContextMenu(next)}
                    status={<ApplyStatus state={contextMenuState} />}
                  />
                </div>

                {/*
                 * Only ever rendered on a machine upgraded from 1.x, which is
                 * why it sits under the switch rather than beside it: for
                 * almost everyone this section is two switches and nothing
                 * else.
                 */}
                {stale && stale.verbs.length > 0 && (
                  <StaleMenuNotice
                    stale={stale}
                    state={staleState}
                    onRemove={() => void removeStale()}
                  />
                )}
              </>
            )}
          </fieldset>

          {/* ---------------------------------------------- files & transfer */}
          <fieldset className="fieldset">
            <legend>Configuration file</legend>
            <div className="stack stack--tight">
              {info ? (
                <div className="pathlist">
                  <span className="pathlist__label">Config</span>
                  <span className="pathlist__value">{info.configPath}</span>
                  <RevealButton path={info.configPath} />
                  <span className="pathlist__label">History</span>
                  <span className="pathlist__value">{info.historyPath}</span>
                  <RevealButton path={info.historyPath} />
                  <span className="pathlist__label">Log</span>
                  <span className="pathlist__value">{info.logPath}</span>
                  <RevealButton path={info.logPath} />
                </div>
              ) : (
                !infoError && <p className="muted">Reading application paths…</p>
              )}

              <div className="btn-row" style={{ marginTop: 4 }}>
                <button type="button" className="btn" onClick={() => void handleExport()}>
                  Export configuration…
                </button>
                <button type="button" className="btn" onClick={() => void handleImport()}>
                  Import configuration…
                </button>
              </div>
              <p className="field__hint">
                Importing replaces every rule, exclusion and setting. You will get a summary to
                confirm before anything is written.
              </p>
            </div>
          </fieldset>

          {/* ------------------------------------------------- danger zone */}
          <section className="dangerzone" aria-labelledby={ids.danger}>
            <div className="dangerzone__head">
              <IconWarning />
              <h2 className="dangerzone__title" id={ids.danger}>
                Danger zone
              </h2>
            </div>

            <div className="dangerzone__item">
              <div className="dangerzone__text">
                <h3 className="dangerzone__item-title">Restore default settings</h3>
                <p className="dangerzone__item-body">
                  Resets the seven settings on this page — schedule, interval, dry run, archive path
                  template, notification level, log level and folder depth — to AutoTidy's defaults.
                  Your monitored folders and rules, your global exclusions, the Windows integration
                  switches and your history are <strong>not</strong> affected. You will see exactly
                  what changes before it happens, and nothing is written until you save.
                </p>
                {defaultsDiff.length === 0 && (
                  <p className="dangerzone__note">
                    Every setting on this page is already at its default value.
                  </p>
                )}
              </div>
              <button
                type="button"
                className="btn btn--danger"
                onClick={askRestoreDefaults}
                disabled={defaultsDiff.length === 0}
                title={
                  defaultsDiff.length === 0
                    ? "Nothing to restore — these settings are already at their defaults"
                    : `Review the ${defaultsDiff.length} setting${defaultsDiff.length === 1 ? "" : "s"} that would change`
                }
              >
                Restore defaults…
              </button>
            </div>

            <p className="dangerzone__foot">
              <strong>Import configuration…</strong> above is the other destructive action here: it
              replaces every rule, exclusion and setting at once. It has its own confirmation.
            </p>
          </section>
        </div>
      </div>

      {/* ------------------------------------------------------------ save bar */}
      <div className="settings__savebar" data-state={saveBarState}>
        <span className="settings__saveicon" aria-hidden="true">
          {saving ? (
            <span className="spinner" />
          ) : saveBarState === "saved" ? (
            <IconCheck />
          ) : saveBarState === "error" ? (
            <IconWarning />
          ) : null}
        </span>
        <p className="settings__savetext" role="status">
          {saveBarText}
        </p>
        <span className="spacer" />
        <button
          type="button"
          className="btn"
          onClick={handleRevert}
          disabled={!dirty || saving}
          title={dirty ? "Discard your edits and reload the saved values" : "Nothing to discard"}
        >
          Revert
        </button>
        <button
          ref={saveButtonRef}
          type="button"
          className="btn btn--primary"
          onClick={() => void handleSave()}
          disabled={!dirty || saving || templateError !== null}
          title={
            !dirty
              ? "No changes to save"
              : templateError
                ? "Fix the archive path template first"
                : "Write these settings to config.json"
          }
        >
          {saving ? "Saving…" : "Save settings"}
        </button>
      </div>

      <ConfirmDialog request={confirmRequest} onClose={() => setConfirmRequest(null)} />

      <Modal
        open={pendingImport !== null}
        title="Replace your configuration?"
        onClose={() => setPendingImport(null)}
        footer={
          <>
            <span className="spacer" />
            <button type="button" className="btn" onClick={() => setPendingImport(null)}>
              Cancel
            </button>
            <button type="button" className="btn btn--danger" onClick={() => void applyImport()}>
              Replace configuration
            </button>
          </>
        }
      >
        {pendingImport && (
          <>
            <div className="notice notice--warn">
              <IconWarning />
              <div className="notice__body">
                <span className="notice__title">
                  This overwrites your current rules and settings
                </span>
                <span>
                  Your history and undo log are not affected. Export your current configuration
                  first if you might want it back.
                </span>
              </div>
            </div>

            <dl className="pathlist" style={{ gridTemplateColumns: "150px minmax(0,1fr)" }}>
              <dt className="pathlist__label">File</dt>
              <dd className="pathlist__value">{pendingImport.path}</dd>
              <dt className="pathlist__label">Monitored folders</dt>
              <dd>
                {pendingImport.config.folders.length} (currently {config.folders.length})
              </dd>
              <dt className="pathlist__label">Global exclusions</dt>
              <dd>
                {pendingImport.config.excluded_folders.length} (currently{" "}
                {config.excluded_folders.length})
              </dd>
              <dt className="pathlist__label">Dry run</dt>
              <dd>{pendingImport.config.settings.dry_run_mode ? "on" : "off"}</dd>
              <dt className="pathlist__label">Interval</dt>
              <dd>{describeInterval(pendingImport.config.settings.interval_minutes)}</dd>
            </dl>

            {pendingImport.config.folders.some((r) => r.action === "delete_permanently") && (
              <div className="notice notice--error">
                <IconWarning />
                <div className="notice__body">
                  <span className="notice__title">
                    This configuration contains permanent-delete rules
                  </span>
                  <span>
                    Review them in the Rules view before you start monitoring. Permanently deleted
                    files cannot be recovered.
                  </span>
                </div>
              </div>
            )}

            {pendingImport.config.folders.length === 0 && (
              <EmptyState
                title="No rules in this file"
                body="Importing it will leave AutoTidy with nothing to monitor."
              />
            )}
          </>
        )}
      </Modal>
    </div>
  );
}

function pluraliseFields(n: number): string {
  return n === 1 ? "1 setting" : `these ${n} settings`;
}

// ------------------------------------------------- leftovers from AutoTidy 1.x

interface StaleMenuNoticeProps {
  stale: StaleContextMenu;
  state: ApplyState;
  onRemove: () => void;
}

/**
 * The upgrade gap, explained and offered as a fix.
 *
 * Two decisions worth keeping. First, it shows the registered command line
 * rather than summarising it: this is a request to delete something from the
 * user's registry, and "trust me, it is junk" is not an argument — seeing
 * `python.exe` and `main.py` in it is. Second, when AutoTidy is not elevated
 * there is no Remove button at all. A button that can only fail is worse than
 * no button: it costs a click to learn what a sentence could have said.
 */
function StaleMenuNotice({ stale, state, onRemove }: StaleMenuNoticeProps) {
  const n = stale.verbs.length;
  const busy = state.kind === "applying";
  return (
    <div className="notice notice--warn stalemenu">
      <IconWarning />
      <div className="notice__body">
        <span className="notice__title">
          {n === 1
            ? "One leftover Explorer entry from AutoTidy 1.x"
            : `${n} leftover Explorer entries from AutoTidy 1.x`}
        </span>
        <div className="stalemenu__text">
          <p>
            AutoTidy 1.x added {n === 1 ? "this" : "these"} to the folder right-click menu for
            the whole computer. {n === 1 ? "It runs" : "They run"} the old Python version, which
            this install replaced, so {n === 1 ? "it now does" : "they now do"} nothing. The
            switch above is AutoTidy 2's replacement, and it applies to your account only.
          </p>
          <dl className="stalemenu__list">
            {stale.verbs.map((entry) => (
              <div className="stalemenu__item" key={entry.verb}>
                <dt>{entry.label ?? entry.verb}</dt>
                <dd>
                  <code>{entry.key}</code>
                </dd>
                <dd>
                  {entry.command ? (
                    <code>{entry.command}</code>
                  ) : (
                    <span className="stalemenu__none">No command registered.</span>
                  )}
                </dd>
              </div>
            ))}
          </dl>
          {stale.elevated ? (
            <>
              <div className="notice__actions">
                <button type="button" className="btn" onClick={onRemove} disabled={busy}>
                  {busy
                    ? "Removing…"
                    : n === 1
                      ? "Remove this entry"
                      : `Remove ${n === 2 ? "both" : `all ${n}`} entries`}
                </button>
              </div>
              <p className="stalemenu__foot">
                Nothing else is touched: your rules, settings, history and the switch above stay
                as they are.
              </p>
            </>
          ) : (
            <p className="stalemenu__foot">
              Removing {n === 1 ? "it" : "them"} needs administrator rights, because{" "}
              {n === 1 ? "it was" : "they were"} registered for the whole computer — and AutoTidy
              is not running as an administrator. Quit AutoTidy from the tray, right-click it and
              choose <strong>Run as administrator</strong>, then come back to this page: a{" "}
              <strong>Remove</strong> button will be here.
            </p>
          )}
          <ApplyStatus state={state} />
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------- switch --

interface SwitchFieldProps {
  label: string;
  hint?: ReactNode;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
  /** Extra line under the hint — used for the auto-save outcome. */
  status?: ReactNode;
}

/**
 * A real switch rather than the shared checkbox `Toggle`: state has to be
 * readable without relying on the accent colour, so the position of the thumb
 * is backed by an explicit ON/OFF word. `role="switch"` on a native checkbox
 * keeps Space working and makes the state announceable.
 */
function SwitchField({ label, hint, checked, disabled, onChange, status }: SwitchFieldProps) {
  const id = useId();
  const hintId = `${id}hint`;
  return (
    <div
      className={
        "switchrow" +
        (checked ? " switchrow--on" : "") +
        (disabled ? " switchrow--disabled" : "")
      }
    >
      <div className="switchrow__text">
        <label className="switchrow__label" htmlFor={id}>
          {label}
        </label>
        {hint && (
          <p className="switchrow__hint" id={hintId}>
            {hint}
          </p>
        )}
        {status}
      </div>
      <div className="switchrow__control">
        <span className="switchrow__state" aria-hidden="true">
          {checked ? "On" : "Off"}
        </span>
        <span className="switch">
          <input
            id={id}
            type="checkbox"
            role="switch"
            className="switch__input"
            checked={checked}
            disabled={disabled}
            aria-describedby={hint ? hintId : undefined}
            onChange={(e) => onChange(e.target.checked)}
          />
          <span className="switch__track" aria-hidden="true">
            <span className="switch__thumb" />
          </span>
        </span>
      </div>
    </div>
  );
}

function ApplyStatus({ state }: { state: ApplyState }) {
  if (state.kind === "idle") return null;
  return (
    <p
      className={`applystate applystate--${state.kind}`}
      role="status"
    >
      {state.kind === "applying" && (
        <>
          <span className="spinner" aria-hidden="true" />
          Applying…
        </>
      )}
      {state.kind === "applied" && (
        <>
          <IconCheck />
          Saved at {formatClock(state.at)} — {state.message}.
        </>
      )}
      {state.kind === "failed" && (
        <>
          <IconWarning />
          Not saved: {state.message}
        </>
      )}
    </p>
  );
}

function RevealButton({ path }: { path: string }) {
  const { push } = useToasts();
  return (
    <button
      type="button"
      className="btn btn--sm"
      onClick={() =>
        void revealInExplorer(path).catch((err: unknown) =>
          push("error", "Could not open that location", errorMessage(err)),
        )
      }
    >
      <IconExternal />
      Show
    </button>
  );
}
