import type { ReactNode } from "react";

import { useToasts, type ToastTone } from "../state/ToastProvider";
import { IconCheck, IconClose, IconInfo, IconWarning } from "./icons";

/** Never render more than this many at once; older ones collapse into a count. */
const MAX_VISIBLE = 4;

const TONE_ICON: Record<ToastTone, ReactNode> = {
  info: <IconInfo size={15} />,
  success: <IconCheck size={15} />,
  warning: <IconWarning size={15} />,
  error: <IconWarning size={15} />,
};

/** Read out to assistive tech alongside the tone colour and icon. */
const TONE_WORD: Record<ToastTone, string> = {
  info: "Information",
  success: "Success",
  warning: "Warning",
  error: "Error",
};

/**
 * Bottom-right toast stack.
 *
 * Announcement is handled by the two always-mounted live regions below rather
 * than by the visible list. A live region has to exist in the DOM *before* the
 * text is inserted for the insertion to be announced, and nesting a
 * `role="alert"` inside an `aria-live="polite"` container lets the polite
 * container win — which would downgrade every failure notice. Splitting them
 * keeps errors assertive and everything else polite, without reordering what
 * the user sees.
 */
export function Toasts() {
  const { toasts, dismiss } = useToasts();

  const hidden = Math.max(0, toasts.length - MAX_VISIBLE);
  const visible = toasts.slice(-MAX_VISIBLE);

  const politeText = toasts
    .filter((t) => t.tone !== "error")
    .map((t) => `${TONE_WORD[t.tone]}: ${t.title}${t.body ? `. ${t.body}` : ""}`);
  const assertiveText = toasts
    .filter((t) => t.tone === "error")
    .map((t) => `${TONE_WORD[t.tone]}: ${t.title}${t.body ? `. ${t.body}` : ""}`);

  return (
    <>
      {/* Mounted unconditionally so additions are announced. */}
      <div className="visually-hidden" role="status" aria-live="polite" aria-atomic="false">
        {politeText.map((text, i) => (
          <p key={`${text}-${i}`}>{text}</p>
        ))}
      </div>
      <div className="visually-hidden" role="alert" aria-live="assertive" aria-atomic="false">
        {assertiveText.map((text, i) => (
          <p key={`${text}-${i}`}>{text}</p>
        ))}
      </div>

      {toasts.length > 0 && (
        <div className="toasts">
          {hidden > 0 && (
            <div className="toasts__overflow">
              <span>
                {hidden} earlier notification{hidden === 1 ? "" : "s"} hidden
              </span>
              <span className="spacer" />
              <button
                type="button"
                className="btn btn--sm"
                onClick={() => toasts.forEach((t) => dismiss(t.id))}
              >
                Dismiss all
              </button>
            </div>
          )}

          {visible.map((toast) => (
            <div key={toast.id} className={`toast toast--${toast.tone}`}>
              <span className="toast__icon">{TONE_ICON[toast.tone]}</span>
              <div className="toast__body">
                <div className="toast__title">
                  <span className="visually-hidden">{TONE_WORD[toast.tone]}: </span>
                  {toast.title}
                </div>
                {toast.body && <div className="toast__text">{toast.body}</div>}
              </div>
              <button
                type="button"
                className="btn btn--ghost btn--sm btn--icon"
                onClick={() => dismiss(toast.id)}
                aria-label={`Dismiss: ${toast.title}`}
              >
                <IconClose />
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
