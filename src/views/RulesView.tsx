import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";

import { ruleTemplates } from "../lib/api";
import { findRule, ruleDiffers, templateRules } from "../lib/config";
import { errorMessage } from "../lib/errors";
import { ACTION_LABELS, basename } from "../lib/format";
import type { Rule, RuleTemplate } from "../lib/types";
import { useConfig } from "../state/ConfigProvider";
import { useToasts } from "../state/ToastProvider";
import { ConfirmDialog, type ConfirmRequest } from "../components/ConfirmDialog";
import { Modal } from "../components/Modal";
import { EmptyState, ErrorNotice, Loading } from "../components/common";
import { useUnsavedChangesGuard } from "../components/Navigation";
import {
  IconFolder,
  IconPlus,
  IconRules,
  IconSearch,
  IconTrash,
  IconWarning,
} from "../components/icons";
import { RuleEditor } from "./RuleEditor";
import "./RulesView.css";

/*
 * HEADING STRUCTURE FOR THIS VIEW (the convention is documented in
 * styles/global.css and components/AppShell.tsx):
 *
 *   h1  Rules
 *   h2    Monitored folders        (the left pane)
 *   h2    Rule for <folder>        (the right pane; visually-hidden when empty)
 *   legend  Match criteria / Action / Exclusions for this folder
 *   h2    Rule templates | Global exclusions   (dialog titles, via <Modal>)
 *   h3      Excluded folders / Matching files  (sections inside a dialog)
 *   h3      Downloads / Free up space …        (one per template category)
 */

export function RulesView() {
  const { config, loading, error, reload, addFolder, saveRule, deleteRule, addGlobalExclusion, removeGlobalExclusion } =
    useConfig();
  const { push } = useToasts();

  const listHeadingId = useId();
  const editorHeadingId = useId();

  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [draft, setDraft] = useState<Rule | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [exclusionsOpen, setExclusionsOpen] = useState(false);

  const folders = useMemo(() => config?.folders ?? [], [config]);
  const persisted = findRule(config, selectedPath);

  // Pick the first folder once config arrives, and recover if the selected one
  // disappears (removed here, or by the tray's context-menu integration).
  useEffect(() => {
    if (folders.length === 0) {
      setSelectedPath(null);
      return;
    }
    const stillThere = selectedPath !== null && folders.some((r) => r.path === selectedPath);
    if (!stillThere) setSelectedPath(folders[0]?.path ?? null);
  }, [folders, selectedPath]);

  // Hydrate the draft on selection change. Same path keeps the existing draft so
  // a background reload cannot silently discard in-progress edits.
  useEffect(() => {
    if (!persisted) {
      setDraft(null);
      return;
    }
    setDraft((current) => (current && current.path === persisted.path ? current : { ...persisted }));
    setSaveError(null);
  }, [persisted]);

  const dirty = Boolean(draft && persisted && ruleDiffers(draft, persisted));

  // Switching views unmounts this one and takes the draft with it.
  useUnsavedChangesGuard(dirty, `Unsaved changes to the rule for ${draft?.path ?? ""}`);

  const visibleFolders = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q === "") return folders;
    return folders.filter(
      (rule) =>
        rule.path.toLowerCase().includes(q) ||
        rule.pattern.toLowerCase().includes(q) ||
        ACTION_LABELS[rule.action].toLowerCase().includes(q),
    );
  }, [folders, query]);

  const report = useCallback(
    (label: string, err: unknown) => {
      push("error", label, errorMessage(err));
    },
    [push],
  );

  async function handleAddFolder() {
    try {
      const selected = await openDialog({
        directory: true,
        multiple: false,
        title: "Select a folder for AutoTidy to watch",
      });
      if (typeof selected !== "string") return;
      await addFolder(selected);
      setSelectedPath(selected);
      push("success", "Folder added", selected);
    } catch (err) {
      report("Could not add folder", err);
    }
  }

  async function handleAddExclusion() {
    try {
      const selected = await openDialog({
        directory: true,
        multiple: false,
        title: "Select a folder to exclude",
      });
      if (typeof selected === "string") await addGlobalExclusion(selected);
    } catch (err) {
      report("Could not add exclusion", err);
    }
  }

  function handleChange(patch: Partial<Rule>) {
    // Spread the draft, never rebuild it: unknown per-rule keys live here too.
    setDraft((current) => (current ? { ...current, ...patch } : current));
  }

  async function commit(rule: Rule) {
    setSaving(true);
    setSaveError(null);
    try {
      await saveRule(rule);
      push("success", "Rule saved", rule.path);
    } catch (err) {
      setSaveError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  function handleSave() {
    if (!draft || !persisted) return;
    const becomingIrreversible =
      draft.action === "delete_permanently" && persisted.action !== "delete_permanently";

    if (becomingIrreversible) {
      setConfirmRequest({
        title: "Save a permanent-delete rule?",
        tone: "danger",
        confirmLabel: "Save rule",
        acknowledge: "I understand these files cannot be recovered",
        body: (
          <div className="notice__body">
            <span className="notice__title">{draft.path}</span>
            <span>
              Every matching file in this folder will be erased on the next scan. They will not go
              to the Recycle Bin, and the Undo view cannot restore them. Consider “Delete to
              Recycle Bin” instead, or preview the matches first.
            </span>
          </div>
        ),
        onConfirm: () => commit(draft),
      });
      return;
    }

    void commit(draft);
  }

  function handleRevert() {
    if (persisted) setDraft({ ...persisted });
    setSaveError(null);
  }

  function handleDelete() {
    if (!persisted) return;
    const path = persisted.path;
    setConfirmRequest({
      // The label has to name the consequence: this deletes the rule, it does
      // not merely pause monitoring. "Stop monitoring" reads like the toggle.
      title: "Remove this folder and delete its rule?",
      tone: "danger",
      confirmLabel: "Remove folder",
      body: (
        <div className="notice__body">
          <span className="notice__title">{path}</span>
          <span>
            The rule and everything configured on it — pattern, age, action, destination and
            exclusions — is deleted from AutoTidy's configuration. Files already on disk, and the
            history of what AutoTidy did to them, are left untouched.
          </span>
          <span>
            If you only want to pause it, cancel and turn off “Monitor this folder” instead — that
            keeps the settings.
          </span>
        </div>
      ),
      onConfirm: async () => {
        try {
          await deleteRule(path);
          push("success", "Folder removed", path);
        } catch (err) {
          report("Could not remove folder", err);
        }
      },
    });
  }

  function toggleEnabled(rule: Rule, enabled: boolean) {
    // If the row is the one being edited, fold the change into the draft so the
    // save bar stays the single point of truth. Otherwise write it straight
    // through — there is no draft that could be clobbered.
    if (draft && draft.path === rule.path) {
      handleChange({ enabled });
      return;
    }
    void (async () => {
      try {
        await saveRule({ ...rule, enabled });
      } catch (err) {
        report("Could not update folder", err);
      }
    })();
  }

  const enabledCount = folders.filter((r) => r.enabled).length;
  const subtitle =
    folders.length === 0
      ? "Tell AutoTidy which folders to watch and what to do with the files that pile up in them."
      : `${folders.length} folder${folders.length === 1 ? "" : "s"} configured · ${enabledCount} being monitored`;

  const header = (
    <div className="view__header">
      <div className="view__heading">
        <h1 className="page-title">Rules</h1>
        <p className="page-subtitle">{subtitle}</p>
      </div>
      <div className="view__actions">
        <button type="button" className="btn btn--primary" onClick={() => void handleAddFolder()}>
          <IconPlus />
          Add folder
        </button>
        <button type="button" className="btn" onClick={() => setTemplatesOpen(true)}>
          Templates
        </button>
      </div>
    </div>
  );

  if (loading && !config) {
    return (
      <div className="view">
        {header}
        <Loading label="Reading configuration…" />
      </div>
    );
  }

  /*
   * Distinct from the zero state below, and it wins whenever there would be
   * nothing to show. A user told "no folders yet" when the truth is "we could
   * not read config.json" concludes their rules were wiped.
   */
  if (error && folders.length === 0) {
    return (
      <div className="view">
        {header}
        <div className="view__scroll">
          <EmptyState
            tone="error"
            headingLevel={2}
            icon={<IconWarning size={30} />}
            title="Could not load your configuration"
            body="Your rules are still on disk — AutoTidy just could not read them this time. Nothing has been changed or deleted."
            detail={error}
            action={
              <div className="btn-row">
                <button type="button" className="btn btn--primary" onClick={() => void reload()}>
                  Try again
                </button>
              </div>
            }
          />
        </div>
      </div>
    );
  }

  return (
    <div className="view">
      {header}

      {/*
       * A refresh that failed after a good load leaves stale data on screen.
       * Say so rather than letting it pass for current — silently showing a
       * rule that no longer matches config.json is how a user deletes the
       * wrong files.
       */}
      {error && folders.length > 0 && (
        <div className="notice notice--warn rules__stale" role="status">
          <IconWarning />
          <div className="notice__body">
            <span className="notice__title">Showing the last configuration AutoTidy could read</span>
            <span>{error}</span>
            <div className="notice__actions">
              <button type="button" className="btn btn--sm" onClick={() => void reload()}>
                Reload configuration
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="rules">
        <section className="rules__list" aria-labelledby={listHeadingId}>
          <div className="rules__toolbar">
            <div className="heading-row">
              <h2 className="rules__listtitle" id={listHeadingId}>
                Monitored folders
              </h2>
              <span className="badge">{folders.length}</span>
            </div>
            <div className="input-with-button">
              <label className="visually-hidden" htmlFor="rules-search">
                Search monitored folders
              </label>
              <input
                id="rules-search"
                type="search"
                className="input"
                placeholder="Search folders…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
          </div>

          <div className="rules__scroll">
            {folders.length === 0 ? (
              // Zero state: an action that actually creates the first rule.
              <EmptyState
                headingLevel={3}
                icon={<IconFolder size={26} />}
                title="No folders yet"
                body="Folders you add here get scanned on every run. Downloads is the usual first one."
                action={
                  <div className="btn-row">
                    <button
                      type="button"
                      className="btn btn--primary"
                      onClick={() => void handleAddFolder()}
                    >
                      <IconPlus />
                      Add your first folder
                    </button>
                    <button type="button" className="btn" onClick={() => setTemplatesOpen(true)}>
                      Use a template
                    </button>
                  </div>
                }
              />
            ) : visibleFolders.length === 0 ? (
              // No-results state: different copy, and always an escape route.
              <EmptyState
                headingLevel={3}
                icon={<IconSearch size={22} />}
                title="No folders match your search"
                body={`None of your ${folders.length} folder${folders.length === 1 ? "" : "s"} matches “${query}”. Searching covers the path, the pattern and the action.`}
                action={
                  <button type="button" className="btn" onClick={() => setQuery("")}>
                    Clear search
                  </button>
                }
              />
            ) : (
              <ul>
                {visibleFolders.map((rule) => {
                  const selected = rule.path === selectedPath;
                  const shown = selected && draft ? draft : rule;
                  return (
                    <li
                      key={rule.path}
                      className={
                        "rulerow" +
                        (selected ? " rulerow--selected" : "") +
                        (shown.enabled ? "" : " rulerow--off")
                      }
                    >
                      <input
                        type="checkbox"
                        checked={shown.enabled}
                        onChange={(e) => toggleEnabled(rule, e.target.checked)}
                        aria-label={`Monitor ${rule.path}`}
                      />
                      <button
                        type="button"
                        className="rulerow__btn"
                        onClick={() => setSelectedPath(rule.path)}
                        aria-current={selected ? "true" : undefined}
                      >
                        <span className="rulerow__name">
                          <span>{basename(rule.path) || rule.path}</span>
                          <span className={`dot dot--${shown.action}`} title={ACTION_LABELS[shown.action]} />
                          {shown.action === "delete_permanently" && (
                            <span className="badge badge--danger">Deletes</span>
                          )}
                          {!shown.enabled && <span className="badge">Off</span>}
                        </span>
                        <span className="rulerow__meta" title={rule.path}>
                          {rule.path}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className="rules__toolbar rules__toolbar--foot">
            <button type="button" className="btn" onClick={() => setExclusionsOpen(true)}>
              Global exclusions
              <span className="badge">{config?.excluded_folders.length ?? 0}</span>
            </button>
          </div>
        </section>

        <section className="rules__editor" aria-labelledby={editorHeadingId}>
          {draft && persisted ? (
            <>
              <div className="editor__head">
                <div className="editor__path">
                  <h2 className="editor__pathname" id={editorHeadingId}>
                    {basename(draft.path) || draft.path}
                  </h2>
                  <span className="editor__pathfull">{draft.path}</span>
                </div>
              </div>
              <RuleEditor
                key={draft.path}
                draft={draft}
                dirty={dirty}
                saving={saving}
                saveError={saveError}
                onChange={handleChange}
                onSave={handleSave}
                onRevert={handleRevert}
                onDelete={handleDelete}
              />
            </>
          ) : (
            <div className="view__scroll">
              <h2 className="visually-hidden" id={editorHeadingId}>
                Rule editor
              </h2>
              <EmptyState
                headingLevel={3}
                icon={<IconRules size={30} />}
                title={folders.length === 0 ? "AutoTidy is not watching anything yet" : "Select a folder"}
                body={
                  folders.length === 0
                    ? "Pick a folder that fills up — Downloads, a screenshots folder, a scratch directory — and tell AutoTidy what to do with the files that pile up in it."
                    : "Choose a folder from the list to edit its cleanup rule."
                }
                action={
                  folders.length === 0 ? (
                    <div className="btn-row">
                      <button type="button" className="btn btn--primary" onClick={() => void handleAddFolder()}>
                        <IconPlus />
                        Add your first folder
                      </button>
                      <button type="button" className="btn" onClick={() => setTemplatesOpen(true)}>
                        Browse templates
                      </button>
                    </div>
                  ) : undefined
                }
              />
            </div>
          )}
        </section>
      </div>

      <TemplatesModal
        open={templatesOpen}
        onClose={() => setTemplatesOpen(false)}
        onApply={(template) => {
          const rules = templateRules(template);
          setTemplatesOpen(false);
          if (rules.length === 0) {
            push("warning", "Template has no usable rules", template.name);
            return;
          }
          const hasIrreversible = rules.some((r) => r.action === "delete_permanently");
          setConfirmRequest({
            title: `Apply “${template.name}”?`,
            tone: hasIrreversible ? "danger" : "default",
            confirmLabel: `Add ${rules.length} rule${rules.length === 1 ? "" : "s"}`,
            ...(hasIrreversible
              ? { acknowledge: "I understand this template deletes files permanently" }
              : {}),
            body: (
              <div className="notice__body">
                <span className="notice__title">{template.description}</span>
                <span>Existing rules for these folders will be overwritten:</span>
                <ul style={{ marginTop: 6 }}>
                  {rules.map((r) => (
                    <li key={r.path} className="mono">
                      {r.path} → {ACTION_LABELS[r.action]}
                      {r.destination_folder ? ` → ${r.destination_folder}` : ""}
                    </li>
                  ))}
                </ul>
              </div>
            ),
            onConfirm: async () => {
              let applied = 0;
              const failures: string[] = [];
              for (const rule of rules) {
                try {
                  // addRule returns false when the folder is already monitored,
                  // which is fine — updateRule then overwrites its settings.
                  await addFolder(rule.path).catch(() => undefined);
                  await saveRule(rule);
                  applied += 1;
                } catch (err) {
                  failures.push(`${rule.path}: ${errorMessage(err)}`);
                }
              }
              if (applied > 0) {
                push("success", `Applied “${template.name}”`, `${applied} rule${applied === 1 ? "" : "s"} written.`);
                const first = rules[0];
                if (first) setSelectedPath(first.path);
              }
              if (failures.length > 0) {
                push("error", "Some template rules failed", failures.join("\n"));
              }
            },
          });
        }}
      />

      <Modal
        open={exclusionsOpen}
        title="Global exclusions"
        onClose={() => setExclusionsOpen(false)}
        footer={
          <>
            <span className="spacer" />
            <button type="button" className="btn" onClick={() => setExclusionsOpen(false)}>
              Done
            </button>
          </>
        }
      >
        <p className="muted">
          AutoTidy never scans these folders, whatever your rules say. Use this for anything you
          want permanently off-limits.
        </p>

        <div className="btn-row">
          <button type="button" className="btn" onClick={() => void handleAddExclusion()}>
            <IconPlus />
            Add excluded folder
          </button>
        </div>

        {config && config.excluded_folders.length > 0 ? (
          <>
            <h3 className="subsection-title">
              Excluded folders ({config.excluded_folders.length})
            </h3>
            <ul className="exclusions">
              {config.excluded_folders.map((path) => (
                <li className="exclusion-row" key={path}>
                  <span className="mono truncate" title={path} style={{ flex: "1 1 auto", minWidth: 0 }}>
                    {path}
                  </span>
                  <button
                    type="button"
                    className="btn btn--sm btn--icon"
                    aria-label={`Remove exclusion ${path}`}
                    onClick={() => {
                      void (async () => {
                        try {
                          await removeGlobalExclusion(path);
                        } catch (err) {
                          report("Could not remove exclusion", err);
                        }
                      })();
                    }}
                  >
                    <IconTrash />
                  </button>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <EmptyState
            headingLevel={3}
            icon={<IconFolder size={26} />}
            title="No folders are off-limits yet"
            body="Anything you add here is skipped by every rule, in every scan. Good candidates are folders you sync, back up, or never want touched — OneDrive, a code checkout, a photo library."
            action={
              <button type="button" className="btn btn--primary" onClick={() => void handleAddExclusion()}>
                <IconPlus />
                Add the first excluded folder
              </button>
            }
          />
        )}
      </Modal>

      <ConfirmDialog request={confirmRequest} onClose={() => setConfirmRequest(null)} />
    </div>
  );
}

// --------------------------------------------------------------- templates --

interface TemplatesModalProps {
  open: boolean;
  onClose: () => void;
  onApply: (template: RuleTemplate) => void;
}

function TemplatesModal({ open, onClose, onApply }: TemplatesModalProps) {
  const [templates, setTemplates] = useState<RuleTemplate[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setTemplates(await ruleTemplates());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (open && templates === null && !busy && error === null) void load();
  }, [open, templates, busy, error, load]);

  const groups = useMemo(() => groupByCategory(templates), [templates]);

  return (
    <Modal
      open={open}
      title="Rule templates"
      wide
      onClose={onClose}
      footer={
        <>
          <span className="spacer" />
          <button type="button" className="btn" onClick={onClose}>
            Close
          </button>
        </>
      }
    >
      <p className="muted">
        A template adds one or more folders with a rule already filled in. Everything a template
        writes is editable afterwards, and you can preview what a rule matches before it runs.
      </p>

      {busy && <p className="muted">Loading templates…</p>}
      {error && <ErrorNotice title="Could not load templates" message={error} onRetry={() => void load()} />}

      {templates && templates.length === 0 && (
        <EmptyState
          headingLevel={3}
          icon={<IconRules size={26} />}
          title="No templates available"
          body="The engine did not return any rule templates. You can still add folders by hand and configure them yourself."
        />
      )}

      {groups.map(([category, entries]) => (
        <section key={category} className="stack stack--tight template-group">
          <h3 className="template-group__title">{category}</h3>
          {entries.map((template) => (
            <button
              key={template.name}
              type="button"
              className="template-card"
              onClick={() => onApply(template)}
            >
              <IconFolder />
              <span className="template-card__body">
                <span className="template-card__name">{template.name}</span>
                <span className="template-card__desc">{template.description}</span>
                <span className="template-card__desc">{templateSummary(template)}</span>
              </span>
            </button>
          ))}
        </section>
      ))}
    </Modal>
  );
}

/**
 * Group for display, preserving the order the engine sent.
 *
 * A `Map` keyed by category does that on its own — first appearance fixes the
 * group's position — and the engine keeps each category's templates adjacent,
 * so the order inside a group is its order too. Templates with no category
 * (a 1.5.0-era payload) collect under one neutral heading rather than vanishing.
 */
function groupByCategory(templates: RuleTemplate[] | null): Array<[string, RuleTemplate[]]> {
  const groups = new Map<string, RuleTemplate[]>();
  for (const template of templates ?? []) {
    const key = template.category?.trim() || "Templates";
    const existing = groups.get(key);
    if (existing) existing.push(template);
    else groups.set(key, [template]);
  }
  return [...groups];
}

/**
 * The one line that says what applying this would actually do. "3 rules" told
 * the user nothing they could act on; the action and the folder count are what
 * separates "files move into a subfolder" from "files are deleted".
 */
function templateSummary(template: RuleTemplate): string {
  const rules = templateRules(template);
  if (rules.length === 0) return "No usable rules";

  const actions = [...new Set(rules.map((r) => ACTION_LABELS[r.action]))];
  const folders = `${rules.length} folder${rules.length === 1 ? "" : "s"}`;
  return `${actions.join(" · ")} · ${folders}`;
}
