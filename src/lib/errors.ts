/**
 * Every `invoke` in this app can reject: the command may be unimplemented, the
 * file operation may have failed, or the config may be unreadable. Tauri
 * rejects with whatever the Rust side serialised, which is usually a bare
 * string but is not guaranteed to be. Normalise it to something displayable so
 * a view can render an error state instead of throwing during render.
 */
export function errorMessage(err: unknown): string {
  if (typeof err === "string") return err;
  if (err instanceof Error) return err.message;
  if (typeof err === "number" || typeof err === "boolean") return String(err);
  if (err && typeof err === "object") {
    const message = (err as { message?: unknown }).message;
    if (typeof message === "string") return message;
    try {
      return JSON.stringify(err);
    } catch {
      return "Unknown error";
    }
  }
  return "Unknown error";
}
