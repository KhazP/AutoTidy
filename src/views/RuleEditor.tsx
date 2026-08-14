import { useEffect, useId, useMemo, useRef, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";

import { previewRule, vocabulary } from "../lib/api";
import {
  FALLBACK_PLACEHOLDERS,
  PLACEHOLDER_HELP,
  actionUsesDestination,
  describeRule,
  isIrreversible,
  validateArchiveTemplate,
} from "../lib/config";
import { errorMessage } from "../lib/errors";
import { ACTION_LABELS, ACTION_ORDER, basename } from "../lib/format";
import type { Action, Rule, RuleLogic, RulePreview } from "../lib/types";
import { ErrorNotice, Field, InfoTip, Toggle } from "../components/common";
import { useNavigation } from "../components/Navigation";
import { Modal } from "../components/Modal";
import { IconEye, IconFolder, IconPlus, IconTrash, IconWarning } from "../components/icons";

interface RuleEditorProps {
  draft: Rule;
  dirty: boolean;
  saving: boolean;
  saveError: string | null;
  onChange: (patch: Partial<Rule>) => void;
  onSave: () => void;
  onRevert: () => void;
  onDelete: () => void;
}

const PREVIEW_LIMIT = 100;
const AGE_MAX = 3650;

/**
 * An input problem, split into the two halves the user actually needs: what is
 * wrong, and what to do about it. `flows/showing-input-error` asks for both,
 * and "Invalid input" on its own satisfies neither.
 */
interface FieldIssue {
  message: string;
  fix: string;
}

// ------------------------------------------------------------- placeholders --

/**
 * `vocabulary()` is the authority on which `{PLACEHOLDER}` tokens the engine
 * understands. Cached at module scope because the editor remounts on every
 * folder selection and the answer cannot change while the app is running.
 */
let placeholderCache: string[] | null = null;

function usePlaceholders(): string[] {
  const [list, setList] = useState<string[]>(
    () => placeholderCache ?? [...FALLBACK_PLACEHOLDERS],
  );

  useEffect(() => {
    if (placeholderCache) return;
    let alive = true;
    void vocabulary()
      .then((v) => {
        const next = v?.placeholders;
        if (!Array.isArray(next) || next.length === 0) return;
        placeholderCache = next;
        if (alive) setList(next);
      })
      // The fallback list is the same one the Rust side ships; a failed lookup
      // degrades to "validate against the built-in set", never to "no
      // validation at all".
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  return list;
}

// --------------------------------------------------------------- validators --

function validateAge(text: string): FieldIssue | null {
  const trimmed = text.trim();
  if (trimmed === "") {
    return {
      message: "Minimum age is empty.",
      fix: "Enter a number of days. Use 0 to match files of any age.",
    };
  }
  if (!/^\d+$/.test(trimmed)) {
    return {
      message: `“${trimmed}” is not a whole number of days.`,
      fix: "Use digits only — no minus sign, decimal point or units. 0 matches files of any age.",
    };
  }
  if (Number(trimmed) > AGE_MAX) {
    return {
      message: `${trimmed} days is past the ${AGE_MAX}-day limit.`,
      fix: `Enter a value between 0 and ${AGE_MAX} (about ten years).`,
    };
  }
  return null;
}

function validatePattern(pattern: string, useRegex: boolean): FieldIssue | null {
  if (!useRegex) return null;
  if (pattern.trim() === "") {
    return {
      message: "A regular expression is required while regex mode is on.",
      fix: "Enter an expression such as ^report_\\d{4}\\.pdf$, or turn off “Treat the pattern as a regular expression”.",
    };
  }
  try {
    new RegExp(pattern);
    return null;
  } catch (err) {
    return {
      message: `Not a valid regular expression: ${errorMessage(err)}`,
      fix: "Fix the expression, or turn off “Treat the pattern as a regular expression” to use * and ? wildcards instead.",
    };
  }
}

function validateExclusion(value: string, all: string[], index: number): FieldIssue | null {
  const trimmed = value.trim();
  if (trimmed === "") {
    return {
      message: "This exclusion pattern is blank.",
      fix: "Enter a pattern such as *.tmp or build/, or remove the row.",
    };
  }
  if (trimmed.split(/[\\/]/).includes("..")) {
    return {
      message: "An exclusion cannot contain “..”.",
      fix: "Write the pattern relative to the monitored folder, such as archive/ or *.tmp.",
    };
  }
  if (all.some((other, i) => i !== index && other.trim() === trimmed)) {
    return {
      message: "This pattern is already in the list.",
      fix: "Remove the duplicate, or change it to match something else.",
    };
  }
  return null;
}

// ------------------------------------------------------------------ editor --

export function RuleEditor({
  draft,
  dirty,
  saving,
  saveError,
  onChange,
  onSave,
  onRevert,
  onDelete,
}: RuleEditorProps) {
  const ids = {
    age: useId(),
    pattern: useId(),
    logic: useId(),
    action: useId(),
    destination: useId(),
    exclusion: useId(),
    dangerBanner: useId(),
    summary: useId(),
  };

  const [newExclusion, setNewExclusion] = useState("");
  const [preview, setPreview] = useState<RulePreview | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const placeholders = usePlaceholders();
  const { navigate } = useNavigation();
  const needsDestination = actionUsesDestination(draft.action);
  const irreversible = isIrreversible(draft.action);

  /*
   * The age field keeps its own text so the user can type freely — including
   * something invalid — without the draft being rewritten under them on every
   * keystroke. Only a well-formed value is pushed into the rule.
   */
  const [ageText, setAgeText] = useState(() => String(draft.age_days));
  const lastEmittedAge = useRef(draft.age_days);
  useEffect(() => {
    // Reverting, or any change that did not originate here, resyncs the text.
    if (draft.age_days !== lastEmittedAge.current) {
      lastEmittedAge.current = draft.age_days;
      setAgeText(String(draft.age_days));
    }
  }, [draft.age_days]);

  /*
   * Validation state. A field is only *shown* as invalid once it has been
   * touched — blurred, or flagged by a blocked save. Focusing it again clears
   * the flag, which is what returns the field to its default state on retry.
   */
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [submitBlocked, setSubmitBlocked] = useState(false);
  const controls = useRef<Record<string, HTMLElement | null>>({});
  // Set while we move focus to the first bad field after a blocked save, so
  // that programmatic focus does not immediately wipe the error we just raised.
  const programmaticFocus = useRef(false);

  const ageIssue = useMemo(() => validateAge(ageText), [ageText]);
  const patternIssue = useMemo(
    () => validatePattern(draft.pattern, draft.use_regex),
    [draft.pattern, draft.use_regex],
  );
  const destinationIssue = useMemo<FieldIssue | null>(() => {
    if (!needsDestination) return null;
    const problem = validateArchiveTemplate(draft.destination_folder, placeholders);
    if (!problem) return null;
    return {
      message: problem,
      fix: `Use only ${placeholders.map((p) => `{${p}}`).join(", ")}, or leave the field blank to fall back to the archive path template in Settings.`,
    };
  }, [needsDestination, draft.destination_folder, placeholders]);
  const exclusionIssues = useMemo(
    () => draft.exclusions.map((value, i) => validateExclusion(value, draft.exclusions, i)),
    [draft.exclusions],
  );
  const newExclusionIssue = useMemo<FieldIssue | null>(() => {
    // Empty is not an error here — it is just an unused staging field.
    if (newExclusion.trim() === "") return null;
    return validateExclusion(newExclusion, draft.exclusions, -1);
  }, [newExclusion, draft.exclusions]);

  /** Everything that must be clean before the rule can be written to disk. */
  const blocking = useMemo(() => {
    const list: Array<{ key: string; label: string; issue: FieldIssue }> = [];
    if (ageIssue) list.push({ key: "age", label: "Minimum age (days)", issue: ageIssue });
    if (patternIssue) list.push({ key: "pattern", label: "Filename pattern", issue: patternIssue });
    if (destinationIssue) {
      list.push({ key: "destination", label: "Destination folder", issue: destinationIssue });
    }
    exclusionIssues.forEach((issue, i) => {
      if (issue) list.push({ key: `exclusion:${i}`, label: `Exclusion pattern ${i + 1}`, issue });
    });
    return list;
  }, [ageIssue, patternIssue, destinationIssue, exclusionIssues]);

  useEffect(() => {
    if (blocking.length === 0) setSubmitBlocked(false);
  }, [blocking.length]);

  function markTouched(key: string) {
    setTouched((current) => (current[key] ? current : { ...current, [key]: true }));
  }

  function clearTouched(key: string) {
    if (programmaticFocus.current) return;
    setTouched((current) => (current[key] ? { ...current, [key]: false } : current));
  }

  /** Blur validates, focus resets — the whole flow, in one spread. */
  function validationProps(key: string) {
    return {
      onBlur: () => markTouched(key),
      onFocus: () => clearTouched(key),
    };
  }

  function shown(key: string, issue: FieldIssue | null): FieldIssue | null {
    return issue && touched[key] ? issue : null;
  }

  const ageError = shown("age", ageIssue);
  const patternError = shown("pattern", patternIssue);
  const destinationError = shown("destination", destinationIssue);
  const newExclusionError = shown("exclusion-new", newExclusionIssue);

  /**
   * Point the control at its error when there is one, otherwise at its hint —
   * so a screen reader reads the problem the moment focus lands back on the
   * field, which is exactly when the user is about to retry.
   */
  function describedBy(baseId: string, hasError: boolean): string {
    return hasError ? `${baseId}-error` : `${baseId}-hint`;
  }

  async function browseDestination() {
    try {
      const selected = await openDialog({ directory: true, multiple: false, title: "Choose destination folder" });
      if (typeof selected === "string") onChange({ destination_folder: selected });
    } catch (err) {
      setPreviewError(errorMessage(err));
    }
  }

  async function runPreview() {
    setPreviewOpen(true);
    setPreviewBusy(true);
    setPreviewError(null);
    setPreview(null);
    try {
      setPreview(await previewRule(draft, PREVIEW_LIMIT));
    } catch (err) {
      setPreviewError(errorMessage(err));
    } finally {
      setPreviewBusy(false);
    }
  }

  function addExclusion() {
    const value = newExclusion.trim();
    if (value === "" || newExclusionIssue) {
      markTouched("exclusion-new");
      return;
    }
    onChange({ exclusions: [...draft.exclusions, value] });
    setNewExclusion("");
    setTouched((current) => ({ ...current, "exclusion-new": false }));
  }

  function handleSaveClick() {
    if (blocking.length > 0) {
      setTouched((current) => {
        const next = { ...current };
        for (const item of blocking) next[item.key] = true;
        return next;
      });
      setSubmitBlocked(true);
      const first = blocking[0];
      const el = first ? controls.current[first.key] : null;
      if (el) {
        programmaticFocus.current = true;
        el.focus();
        programmaticFocus.current = false;
      }
      return;
    }
    setSubmitBlocked(false);
    onSave();
  }

  // A second sentence under the natural-language summary, covering the parts
  // the sentence itself would make unwieldy.
  const summaryExtras: string[] = [];
  if (draft.enabled && needsDestination && draft.destination_folder.trim() === "") {
    summaryExtras.push("The destination comes from the archive path template in Settings.");
  }
  if (draft.enabled && draft.exclusions.length > 0) {
    summaryExtras.push(
      `${draft.exclusions.length} exclusion pattern${draft.exclusions.length === 1 ? "" : "s"} ${draft.exclusions.length === 1 ? "is" : "are"} checked first; anything matching is skipped.`,
    );
  }

  return (
    <>
      <div className="editor__body">
        <div className="rule-summary" id={ids.summary}>
          <p className="rule-summary__text">{describeRule(draft)}</p>
          {summaryExtras.length > 0 && (
            <p className="rule-summary__more">{summaryExtras.join(" ")}</p>
          )}
        </div>

        {saveError && <ErrorNotice title="Could not save this rule" message={saveError} />}

        {/*
         * Submit-time summary. The per-field errors below say what is wrong;
         * this says why the save did not happen and where to look.
         */}
        {submitBlocked && blocking.length > 0 && (
          <div className="notice notice--error" role="alert">
            <IconWarning />
            <div className="notice__body">
              <span className="notice__title">
                This rule was not saved — {blocking.length} field
                {blocking.length === 1 ? " needs" : "s need"} fixing
              </span>
              <ul className="notice__list">
                {blocking.map((item) => (
                  <li key={item.key}>
                    <strong>{item.label}:</strong> {item.issue.message}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}

        <Toggle
          label="Monitor this folder"
          hint="When off, AutoTidy skips the folder entirely but keeps these settings."
          checked={draft.enabled}
          onChange={(enabled) => onChange({ enabled })}
        />

        <fieldset className="fieldset">
          <legend>Match criteria</legend>
          <div className="grid-2">
            <Field
              label="Minimum age (days)"
              htmlFor={ids.age}
              hintId={`${ids.age}-hint`}
              errorId={`${ids.age}-error`}
              error={ageError?.message ?? null}
              errorFix={ageError?.fix}
              hint="Whole days. 0 matches files of any age."
            >
              <input
                id={ids.age}
                ref={(el) => {
                  controls.current["age"] = el;
                }}
                className="input input--number"
                type="number"
                inputMode="numeric"
                min={0}
                max={AGE_MAX}
                step={1}
                value={ageText}
                aria-invalid={ageError !== null}
                aria-describedby={describedBy(ids.age, ageError !== null)}
                onChange={(e) => {
                  const text = e.target.value;
                  setAgeText(text);
                  // Only a valid value reaches the draft; an invalid one leaves
                  // the last good number in place until it is corrected.
                  if (validateAge(text) === null) {
                    const parsed = Number(text.trim());
                    lastEmittedAge.current = parsed;
                    onChange({ age_days: parsed });
                  }
                }}
                {...validationProps("age")}
              />
            </Field>

            <Field
              label="Filename pattern"
              htmlFor={ids.pattern}
              hintId={`${ids.pattern}-hint`}
              errorId={`${ids.pattern}-error`}
              error={patternError?.message ?? null}
              errorFix={patternError?.fix}
              hint={
                draft.use_regex
                  ? "A regular expression tested against the file name."
                  : "Wildcards: * matches anything, ? matches one character."
              }
            >
              <input
                id={ids.pattern}
                ref={(el) => {
                  controls.current["pattern"] = el;
                }}
                className="input input--mono"
                type="text"
                spellCheck={false}
                autoComplete="off"
                value={draft.pattern}
                aria-invalid={patternError !== null}
                aria-describedby={describedBy(ids.pattern, patternError !== null)}
                placeholder={draft.use_regex ? "^report_\\d{4}\\.pdf$" : "*.*"}
                onChange={(e) => onChange({ pattern: e.target.value })}
                {...validationProps("pattern")}
              />
            </Field>
          </div>

          <div className="stack stack--tight" style={{ marginTop: "var(--space-field-gap)" }}>
            <Toggle
              label="Treat the pattern as a regular expression"
              checked={draft.use_regex}
              onChange={(use_regex) => {
                onChange({ use_regex });
                // Switching modes changes what "valid" means, so the pattern
                // goes back to its default state rather than showing an error
                // the user has not had a chance to react to yet.
                setTouched((current) => ({ ...current, pattern: false }));
              }}
            />

            <Field
              label="Combine age and pattern with"
              htmlFor={ids.logic}
              hintId={`${ids.logic}-hint`}
              hint={
                draft.rule_logic === "AND"
                  ? "A file must satisfy both the age and the pattern."
                  : "A file only has to satisfy one of the age or the pattern."
              }
            >
              <select
                id={ids.logic}
                className="select"
                style={{ maxWidth: 200 }}
                value={draft.rule_logic}
                aria-describedby={`${ids.logic}-hint`}
                onChange={(e) => onChange({ rule_logic: e.target.value as RuleLogic })}
              >
                <option value="OR">OR — either condition</option>
                <option value="AND">AND — both conditions</option>
              </select>
            </Field>
          </div>
        </fieldset>

        <fieldset className={irreversible ? "fieldset fieldset--danger" : "fieldset"}>
          <legend>Action</legend>
          <div className="stack stack--tight">
            <Field label="What to do with matching files" htmlFor={ids.action}>
              <select
                id={ids.action}
                className={irreversible ? "select select--danger" : "select"}
                style={{ maxWidth: 320 }}
                value={draft.action}
                aria-describedby={irreversible ? ids.dangerBanner : undefined}
                onChange={(e) => onChange({ action: e.target.value as Action })}
              >
                {ACTION_ORDER.map((action) => (
                  <option key={action} value={action}>
                    {ACTION_LABELS[action]}
                    {action === "delete_permanently" ? " — cannot be undone" : ""}
                  </option>
                ))}
              </select>
            </Field>

            {/*
             * The one place in this app where getting it wrong is unrecoverable.
             * Banner rather than a hint: title, description, and two ways out
             * (switch to the reversible action, or look at what would be hit).
             */}
            {irreversible && (
              <div className="notice notice--danger" role="alert" id={ids.dangerBanner}>
                <IconWarning size={18} />
                <div className="notice__body">
                  <span className="notice__title">
                    Permanent deletion — these files cannot be recovered
                  </span>
                  <span>
                    Every matching file in {basename(draft.path) || draft.path} is erased on the
                    next scan. It does not go to the Recycle Bin, it is not in File History, and
                    the Undo view cannot bring it back.
                  </span>
                  <div className="notice__actions">
                    <button
                      type="button"
                      className="btn btn--sm"
                      onClick={() => onChange({ action: "delete_to_trash" })}
                    >
                      Use the Recycle Bin instead
                    </button>
                    <button type="button" className="btn btn--sm" onClick={() => void runPreview()}>
                      <IconEye />
                      Preview what would be deleted
                    </button>
                  </div>
                </div>
              </div>
            )}

            {draft.action === "delete_to_trash" && (
              <p className="field__hint">
                Files go to the Recycle Bin, where you can restore them manually. The Undo view
                cannot do it for you.
              </p>
            )}

            <Field
              label="Destination folder"
              htmlFor={ids.destination}
              hintId={`${ids.destination}-hint`}
              errorId={`${ids.destination}-error`}
              error={destinationError?.message ?? null}
              errorFix={destinationError?.fix}
              hint={
                needsDestination
                  ? "Leave blank to use the archive path template from Settings."
                  : "Not used by this action."
              }
            >
              <div className="input-with-button">
                <input
                  id={ids.destination}
                  ref={(el) => {
                    controls.current["destination"] = el;
                  }}
                  className="input input--mono"
                  type="text"
                  spellCheck={false}
                  autoComplete="off"
                  value={draft.destination_folder}
                  disabled={!needsDestination}
                  aria-invalid={destinationError !== null}
                  aria-describedby={describedBy(ids.destination, destinationError !== null)}
                  placeholder="Use archive path template"
                  onChange={(e) => onChange({ destination_folder: e.target.value })}
                  {...validationProps("destination")}
                />
                <button
                  type="button"
                  className="btn"
                  onClick={() => void browseDestination()}
                  disabled={!needsDestination}
                >
                  <IconFolder />
                  Browse…
                </button>
              </div>
            </Field>

            {needsDestination && (
              <details className="placeholders">
                <summary>
                  Placeholders you can use here
                  <span className="badge">{placeholders.length}</span>
                </summary>
                <ul className="placeholders__list">
                  {placeholders.map((name) => (
                    <li key={name}>
                      <code>{`{${name}}`}</code>
                      <span>{PLACEHOLDER_HELP[name] ?? "Supported by the engine."}</span>
                    </li>
                  ))}
                </ul>
                <div className="placeholders__foot">
                  <span>Leaving the field blank uses the archive path template instead.</span>
                  <button type="button" className="btn btn--sm" onClick={() => navigate("settings")}>
                    Edit it in Settings
                  </button>
                </div>
              </details>
            )}

            <div className="btn-row">
              <button type="button" className="btn" onClick={() => void runPreview()}>
                <IconEye />
                Preview matches
              </button>
              <span className="field__hint">
                Runs the rule as currently shown, without changing anything.
              </span>
            </div>
          </div>
        </fieldset>

        <fieldset className="fieldset">
          <legend>Exclusions for this folder</legend>
          <div className="stack stack--tight">
            <p className="field__hint">
              Files and folders matching any of these are skipped before the rule is even
              evaluated. Wildcards are supported; a trailing slash (<code>build/</code>) skips a
              whole subtree.
              <InfoTip label="About exclusion patterns">
                Exclusions win over the rule. If a file matches both the rule and an exclusion, it
                is left alone.
              </InfoTip>
            </p>

            {draft.exclusions.length > 0 && (
              <ul className="exclusions">
                {draft.exclusions.map((pattern, index) => {
                  const key = `exclusion:${index}`;
                  const issue = shown(key, exclusionIssues[index] ?? null);
                  return (
                    <li className="exclusion-row" key={`row-${index}`}>
                      <div className="exclusion-row__field">
                        <input
                          className="input input--mono"
                          type="text"
                          spellCheck={false}
                          autoComplete="off"
                          value={pattern}
                          ref={(el) => {
                            controls.current[key] = el;
                          }}
                          aria-label={`Exclusion pattern ${index + 1}`}
                          aria-invalid={issue !== null}
                          aria-describedby={issue ? `${ids.exclusion}-${index}-error` : undefined}
                          onChange={(e) => {
                            const next = [...draft.exclusions];
                            next[index] = e.target.value;
                            onChange({ exclusions: next });
                          }}
                          {...validationProps(key)}
                        />
                        {issue && (
                          <span className="field__error" id={`${ids.exclusion}-${index}-error`} role="alert">
                            <IconWarning size={14} />
                            <span className="field__error-text">
                              {issue.message}
                              <span className="field__error-fix">{issue.fix}</span>
                            </span>
                          </span>
                        )}
                      </div>
                      <button
                        type="button"
                        className="btn btn--icon"
                        aria-label={`Remove exclusion ${pattern || index + 1}`}
                        onClick={() =>
                          onChange({ exclusions: draft.exclusions.filter((_, i) => i !== index) })
                        }
                      >
                        <IconTrash />
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}

            <Field
              label="Add an exclusion pattern"
              htmlFor={ids.exclusion}
              hintId={`${ids.exclusion}-hint`}
              errorId={`${ids.exclusion}-error`}
              error={newExclusionError?.message ?? null}
              errorFix={newExclusionError?.fix}
              hint="Press Enter or Add to put it in the list above."
            >
              <div className="input-with-button">
                <input
                  id={ids.exclusion}
                  className="input input--mono"
                  type="text"
                  spellCheck={false}
                  autoComplete="off"
                  placeholder="*.tmp"
                  value={newExclusion}
                  aria-invalid={newExclusionError !== null}
                  aria-describedby={describedBy(ids.exclusion, newExclusionError !== null)}
                  onChange={(e) => setNewExclusion(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addExclusion();
                    }
                  }}
                  {...validationProps("exclusion-new")}
                />
                <button
                  type="button"
                  className="btn"
                  onClick={addExclusion}
                  disabled={newExclusion.trim() === ""}
                >
                  <IconPlus />
                  Add
                </button>
              </div>
            </Field>
          </div>
        </fieldset>

        <div className="editor__danger">
          <button type="button" className="btn btn--danger-text" onClick={onDelete}>
            <IconTrash />
            Remove folder and delete this rule
          </button>
          <p className="field__hint">
            Deletes the rule from AutoTidy. Files on disk and your history are untouched. To pause
            it instead, turn off “Monitor this folder” above.
          </p>
        </div>
      </div>

      {dirty && (
        <div className="editor__savebar">
          <strong>Unsaved changes</strong>
          <span className="muted">Nothing is written to config.json until you save.</span>
          <span className="spacer" />
          <button type="button" className="btn" onClick={onRevert} disabled={saving}>
            Revert
          </button>
          {/*
           * Deliberately not disabled while there are validation problems: a
           * dead button explains nothing. Pressing it surfaces every problem at
           * once and moves focus to the first one.
           */}
          <button
            type="button"
            className="btn btn--primary"
            onClick={handleSaveClick}
            disabled={saving}
            aria-busy={saving}
          >
            {saving ? "Saving…" : "Save rule"}
          </button>
        </div>
      )}

      <Modal
        open={previewOpen}
        title="Preview matches"
        wide
        onClose={() => setPreviewOpen(false)}
        footer={
          <>
            <span className="muted">
              {preview
                ? `${preview.total} file${preview.total === 1 ? "" : "s"} match this rule right now.`
                : ""}
            </span>
            <span className="spacer" />
            <button type="button" className="btn" onClick={() => setPreviewOpen(false)}>
              Close
            </button>
          </>
        }
      >
        {previewBusy && <p className="muted">Scanning {draft.path}…</p>}

        {previewError && (
          <ErrorNotice
            title="Preview failed"
            message={previewError}
            onRetry={() => void runPreview()}
          />
        )}

        {preview && !previewBusy && (
          <>
            <div className={irreversible ? "notice notice--danger" : "notice notice--info"}>
              {irreversible && <IconWarning size={18} />}
              <div className="notice__body">
                <span className="notice__title">
                  {preview.total === 0
                    ? "No files match right now"
                    : `${preview.total} file${preview.total === 1 ? "" : "s"} would be ${ACTION_LABELS[draft.action].toLowerCase()}`}
                </span>
                <span>
                  {preview.exampleDestination
                    ? `Example destination: ${preview.exampleDestination}`
                    : needsDestination
                      ? "No destination could be resolved for these files."
                      : "This action does not use a destination."}
                </span>
              </div>
            </div>

            {preview.matches.length === 0 ? (
              <p className="muted">
                Nothing in {draft.path} satisfies the current age and pattern settings.
              </p>
            ) : (
              <>
                {/* Dialog titles are h2, so content inside one starts at h3. */}
                <h3 className="subsection-title">Matching files</h3>
                <ul className="preview-list">
                  {preview.matches.map((match) => (
                    <li key={match} title={match}>
                      {basename(match)}
                    </li>
                  ))}
                </ul>
                {preview.total > preview.matches.length && (
                  <p className="field__hint">
                    Showing the first {preview.matches.length} of {preview.total} matches.
                  </p>
                )}
              </>
            )}
          </>
        )}
      </Modal>
    </>
  );
}
