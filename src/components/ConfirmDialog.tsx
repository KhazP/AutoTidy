import { useEffect, useState, type ReactNode } from "react";

import { errorMessage } from "../lib/errors";
import { Modal } from "./Modal";
import { IconWarning } from "./icons";

export interface ConfirmRequest {
  title: string;
  body: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
  /**
   * When set, the confirm button stays disabled until the user ticks a box
   * carrying this text. Reserved for operations nothing can walk back.
   */
  acknowledge?: string;
  onConfirm: () => void | Promise<void>;
}

interface ConfirmDialogProps {
  request: ConfirmRequest | null;
  onClose: () => void;
}

/**
 * A single confirm dialog driven by a request object, so callers can trigger
 * one from anywhere without each view growing its own dialog state machine.
 */
export function ConfirmDialog({ request, onClose }: ConfirmDialogProps) {
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    setAcknowledged(false);
    setBusy(false);
    setFailure(null);
  }, [request]);

  const danger = request?.tone === "danger";
  const blocked = Boolean(request?.acknowledge) && !acknowledged;

  async function confirm() {
    if (!request || blocked) return;
    setBusy(true);
    setFailure(null);
    try {
      await request.onConfirm();
      onClose();
    } catch (err) {
      /*
       * A rejecting onConfirm used to leave the dialog open, not busy, and
       * silent — the user pressed the button and nothing visibly happened.
       * Keep the dialog open (so they can retry or cancel) and say why.
       */
      setFailure(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={request !== null}
      title={request?.title ?? ""}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <span className="spacer" />
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            {request?.cancelLabel ?? "Cancel"}
          </button>
          <button
            type="button"
            className={danger ? "btn btn--danger" : "btn btn--primary"}
            onClick={() => void confirm()}
            disabled={busy || blocked}
            aria-busy={busy}
          >
            {busy ? "Working…" : failure ? "Try again" : (request?.confirmLabel ?? "Confirm")}
          </button>
        </>
      }
    >
      {request && (
        <>
          <div className={danger ? "notice notice--error" : "notice notice--info"}>
            {danger && <IconWarning />}
            <div className="notice__body">{request.body}</div>
          </div>

          {failure && (
            <div className="notice notice--error" role="alert">
              <IconWarning />
              <div className="notice__body">
                <span className="notice__title">That did not work</span>
                <pre>{failure}</pre>
              </div>
            </div>
          )}
          {request.acknowledge && (
            <label className="check">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(e) => setAcknowledged(e.target.checked)}
              />
              <span className="check__text">
                <span className="check__title">{request.acknowledge}</span>
              </span>
            </label>
          )}
        </>
      )}
    </Modal>
  );
}
