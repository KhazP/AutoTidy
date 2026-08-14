import { useId, useState, type ReactNode } from "react";

import { IconInfo, IconWarning } from "./icons";

// -------------------------------------------------------------- empty state --

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  body?: ReactNode;
  action?: ReactNode;
  /**
   * `error` is a genuinely different state from `zero`: it means we could not
   * read the data, not that there is none. Showing the zero state after a
   * failed load makes users think their data was deleted.
   */
  tone?: "zero" | "error";
  /** Verbatim failure text, shown monospaced under the description. */
  detail?: string;
  /**
   * Render the title as a real heading at this level instead of a paragraph.
   * Opt-in, because the correct level depends on what encloses the empty state
   * and skipping a level is worse than not having a heading at all.
   */
  headingLevel?: 2 | 3 | 4;
}

export function EmptyState({
  icon,
  title,
  body,
  action,
  tone = "zero",
  detail,
  headingLevel,
}: EmptyStateProps) {
  const Heading = headingLevel ? (`h${headingLevel}` as const) : "p";
  return (
    <div className={tone === "error" ? "empty empty--error" : "empty"}>
      {icon && <span className="empty__icon">{icon}</span>}
      <Heading className="empty__title">{title}</Heading>
      {body && <p className="empty__body">{body}</p>}
      {detail && <pre className="empty__detail">{detail}</pre>}
      {action && <div className="empty__actions">{action}</div>}
    </div>
  );
}

// ------------------------------------------------------------- error notice --

interface ErrorNoticeProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}

/**
 * The whole IPC surface can reject — an unimplemented command, a locked file, a
 * corrupt config. Views render this instead of throwing.
 */
export function ErrorNotice({ title = "Something went wrong", message, onRetry, retryLabel = "Retry" }: ErrorNoticeProps) {
  return (
    <div className="notice notice--error" role="alert">
      <IconWarning />
      <div className="notice__body">
        <span className="notice__title">{title}</span>
        <pre>{message}</pre>
        {onRetry && (
          <div className="btn-row" style={{ marginTop: 6 }}>
            <button type="button" className="btn btn--sm" onClick={onRetry}>
              {retryLabel}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// -------------------------------------------------------------------- field --

interface FieldProps {
  label: string;
  htmlFor?: string;
  hint?: ReactNode;
  error?: string | null;
  /** How to get out of the error, when that is not obvious from `error`. */
  errorFix?: ReactNode;
  /**
   * Ids for the hint and error text. Pass them and wire the control's
   * `aria-describedby` to whichever is currently rendered, so a screen reader
   * reads the problem when focus lands back on the field.
   */
  hintId?: string;
  errorId?: string;
  children: ReactNode;
}

export function Field({
  label,
  htmlFor,
  hint,
  error,
  errorFix,
  hintId,
  errorId,
  children,
}: FieldProps) {
  return (
    <div className={error ? "field field--invalid" : "field"}>
      <label className="field__label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {error ? (
        // role="alert" so the problem is announced when the field is left, not
        // only when it is re-entered. Callers validate on blur, so this fires
        // once per mistake rather than once per keystroke.
        <span className="field__error" id={errorId} role="alert">
          <IconWarning size={14} />
          <span className="field__error-text">
            {error}
            {errorFix && <span className="field__error-fix">{errorFix}</span>}
          </span>
        </span>
      ) : (
        hint && (
          <span className="field__hint" id={hintId}>
            {hint}
          </span>
        )
      )}
    </div>
  );
}

// ------------------------------------------------------------------- toggle --

interface ToggleProps {
  label: string;
  hint?: ReactNode;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}

export function Toggle({ label, hint, checked, disabled, onChange }: ToggleProps) {
  return (
    <label className="check">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="check__text">
        <span className="check__title">{label}</span>
        {hint && <span className="check__hint">{hint}</span>}
      </span>
    </label>
  );
}

// ------------------------------------------------------------------ tooltip --

interface InfoTipProps {
  /** Names the tooltip's subject for screen readers, e.g. "About regular expressions". */
  label: string;
  children: ReactNode;
}

/**
 * A hover/focus tooltip on a small "?" affordance.
 *
 * Deliberately minimal: opens on hover *and* keyboard focus, closes on Escape
 * or leaving, sits above its trigger so it never covers the thing it explains,
 * and is only ever one at a time because hover and focus are both singular.
 * The content is supplementary — nothing here is the only place a fact appears.
 */
export function InfoTip({ label, children }: InfoTipProps) {
  const id = useId();
  const [open, setOpen] = useState(false);

  return (
    <span className="tip">
      <button
        type="button"
        className="tip__trigger"
        aria-label={label}
        aria-describedby={open ? id : undefined}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === "Escape" && open) {
            e.stopPropagation();
            setOpen(false);
          }
        }}
      >
        <IconInfo size={11} />
      </button>
      {open && (
        <span className="tip__bubble" role="tooltip" id={id}>
          {children}
        </span>
      )}
    </span>
  );
}

// ------------------------------------------------------------------ spinner --

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="muted" style={{ padding: "var(--sp-4)" }} role="status">
      {label}
    </p>
  );
}
