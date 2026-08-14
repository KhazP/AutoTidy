import { createContext, useContext, useEffect, useId } from "react";

/**
 * Cross-view navigation.
 *
 * The shell keeps the active view in local state. Views that need to point at
 * another view — an empty state whose call to action lives elsewhere, a hint
 * that refers to a setting — read this rather than synthesising the shell's
 * Ctrl+1..4 keyboard shortcut, which was the only seam available before.
 *
 * Kept in its own module so a view can import it without importing AppShell,
 * which imports every view in turn.
 */

export type ViewId = "rules" | "history" | "undo" | "settings";

export const VIEW_LABELS: Record<ViewId, string> = {
  rules: "Rules",
  history: "History",
  undo: "Undo",
  settings: "Settings",
};

/** What a view stands to lose if the user navigates away right now. */
export interface UnsavedWork {
  /** Names the pending edit, e.g. `Unsaved changes to C:\Users\You\Downloads`. */
  what: string;
}

export interface NavigationApi {
  /** The view currently mounted in <main>. */
  view: ViewId;
  /** Switch views. Safe to call from an event handler in any view. */
  navigate: (view: ViewId) => void;
  /**
   * Register (or clear, with `null`) a warning to raise before this view is
   * swapped out. Prefer the `useUnsavedChangesGuard` hook below.
   */
  setUnsavedWork: (id: string, work: UnsavedWork | null) => void;
}

export const NavigationContext = createContext<NavigationApi | null>(null);

export function useNavigation(): NavigationApi {
  const ctx = useContext(NavigationContext);
  if (!ctx) throw new Error("useNavigation must be used inside <AppShell>");
  return ctx;
}

/**
 * Warn before this view is navigated away from while it holds unsaved edits.
 *
 * Views in this app use a draft + explicit Save model, and the sidebar unmounts
 * the whole view on a click — so without this, one mis-click silently discards
 * everything the user typed. Pass `false` and the guard lifts.
 */
export function useUnsavedChangesGuard(active: boolean, what: string): void {
  const { setUnsavedWork } = useNavigation();
  // Keyed per call site so two guards cannot clobber each other, and so
  // StrictMode's double-invoked effects cannot leave a stale registration.
  const id = useId();

  useEffect(() => {
    setUnsavedWork(id, active ? { what } : null);
    return () => setUnsavedWork(id, null);
  }, [id, active, what, setUnsavedWork]);
}
