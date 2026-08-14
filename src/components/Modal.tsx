import { useEffect, useId, useRef, type ReactNode } from "react";

import { IconClose } from "./icons";

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
  /** Set while an operation is in flight so Esc/× cannot orphan it. */
  busy?: boolean;
}

/**
 * Built on the native `<dialog>` element: it gives us the top layer, a real
 * backdrop, Esc handling and focus trapping without a focus-management
 * library. React only controls when `showModal()`/`close()` fire.
 */
export function Modal({ open, title, onClose, children, footer, wide, busy }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) {
      opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      el.showModal();
    }
    if (!open && el.open) {
      el.close();
      /*
       * <dialog> returns focus to whatever opened it — but in this app the
       * opener is routinely disabled *by* the action just confirmed (the last
       * undoable row, a "Restore defaults" button that now has nothing to
       * restore). Focus then lands on <body> and keyboard users are dumped at
       * the top of the document.
       *
       * Checked on the next frame, and only when focus really was lost, so a
       * caller that deliberately moved focus somewhere better still wins.
       */
      requestAnimationFrame(() => {
        const active = document.activeElement;
        if (active && active !== document.body) return;
        const previous = opener.current;
        const usable =
          previous &&
          previous.isConnected &&
          !(previous as HTMLButtonElement).disabled &&
          previous.offsetParent !== null;
        if (usable) {
          previous.focus();
          return;
        }
        const main = document.getElementById("main-content");
        main?.focus();
      });
    }
  }, [open]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onCancel = (event: Event) => {
      // Esc: route through our own handler so the parent's state stays truthful.
      event.preventDefault();
      if (!busy) onClose();
    };
    el.addEventListener("cancel", onCancel);
    return () => el.removeEventListener("cancel", onCancel);
  }, [onClose, busy]);

  return (
    <dialog
      ref={ref}
      className={wide ? "modal modal--wide" : "modal"}
      // Only while open: the heading it points at is not rendered otherwise,
      // and a dangling aria-labelledby is worse than none.
      aria-labelledby={open ? titleId : undefined}
    >
      {open && (
        <div className="modal__inner">
          <div className="modal__header">
            <h2 className="modal__title" id={titleId}>
              {title}
            </h2>
            <span className="spacer" />
            <button
              type="button"
              className="btn btn--ghost btn--sm btn--icon"
              onClick={onClose}
              disabled={busy}
              aria-label="Close dialog"
            >
              <IconClose />
            </button>
          </div>
          <div className="modal__body">{children}</div>
          {footer && <div className="modal__footer">{footer}</div>}
        </div>
      )}
    </dialog>
  );
}
