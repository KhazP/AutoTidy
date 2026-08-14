import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { listRuns, runActions, undoOne, undoRun } from "../lib/api";
import { undoability } from "../lib/config";
import { errorMessage } from "../lib/errors";
import { formatTimestamp, historyActionLabel, pluralise, relativeTime } from "../lib/format";
import type { BatchResult, HistoryRecord, RunSummary } from "../lib/types";
import { useEngine } from "../state/EngineProvider";
import { useToasts } from "../state/ToastProvider";
import { ConfirmDialog, type ConfirmRequest } from "../components/ConfirmDialog";
import { EmptyState, ErrorNotice, Loading } from "../components/common";
import { IconRefresh, IconUndo, IconWarning } from "../components/icons";
import "./UndoView.css";

type RowFilter = "all" | "reversible" | "blocked";

export function UndoView() {
  const { dataRevision, scan, busy: engineBusy, status: engineState } = useEngine();
  const { push } = useToasts();

  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [runsLoading, setRunsLoading] = useState(true);

  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [actions, setActions] = useState<HistoryRecord[] | null>(null);
  const [actionsError, setActionsError] = useState<string | null>(null);
  const [actionsLoading, setActionsLoading] = useState(false);
  const [rowFilter, setRowFilter] = useState<RowFilter>("all");

  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);
  const [lastResult, setLastResult] = useState<BatchResult | null>(null);
  const [working, setWorking] = useState(false);

  // The native <dialog> returns focus to whatever opened it, but the openers
  // here routinely vanish or go disabled as a result of the very action that
  // was confirmed (the last reversible row is undone, the batch button greys
  // out). Keep a stable anchor to catch those cases.
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const detailHeadingRef = useRef<HTMLHeadingElement>(null);

  const loadRuns = useCallback(async () => {
    setRunsLoading(true);
    try {
      const next = await listRuns();
      setRuns(next);
      setRunsError(null);
      setSelectedRun((current) =>
        current && next.some((r) => r.run_id === current) ? current : (next[0]?.run_id ?? null),
      );
    } catch (err) {
      setRunsError(errorMessage(err));
    } finally {
      setRunsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns, dataRevision]);

  const loadActions = useCallback(async (runId: string) => {
    setActionsLoading(true);
    setActions(null);
    try {
      setActions(await runActions(runId));
      setActionsError(null);
    } catch (err) {
      setActionsError(errorMessage(err));
    } finally {
      setActionsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedRun === null) {
      setActions(null);
      return;
    }
    setRowFilter("all");
    void loadActions(selectedRun);
  }, [selectedRun, loadActions]);

  useEffect(() => {
    if (confirmRequest !== null) return;
    const origin = returnFocusRef.current;
    returnFocusRef.current = null;
    if (!origin) return;
    const usable = origin.isConnected && !(origin instanceof HTMLButtonElement && origin.disabled);
    (usable ? origin : detailHeadingRef.current)?.focus();
  }, [confirmRequest]);

  const annotated = useMemo(
    () =>
      (actions ?? []).map((record) => ({
        record,
        ...undoability(record.action_taken, record.status),
      })),
    [actions],
  );

  const undoableCount = annotated.filter((a) => a.undoable).length;
  const blockedCount = annotated.length - undoableCount;
  const currentRun = runs?.find((r) => r.run_id === selectedRun);

  /** Everything the confirmation has to state before anything touches disk. */
  const blastRadius = useMemo(() => {
    let moves = 0;
    let copies = 0;
    const reasons = new Map<string, number>();
    for (const entry of annotated) {
      if (entry.undoable) {
        if (entry.record.action_taken.toUpperCase() === "COPIED") copies += 1;
        else moves += 1;
      } else {
        reasons.set(entry.reason, (reasons.get(entry.reason) ?? 0) + 1);
      }
    }
    return {
      moves,
      copies,
      reasons: [...reasons.entries()].map(([reason, count]) => ({ reason, count })),
    };
  }, [annotated]);

  const visibleRows = useMemo(
    () =>
      annotated.filter((entry) =>
        rowFilter === "all" ? true : rowFilter === "reversible" ? entry.undoable : !entry.undoable,
      ),
    [annotated, rowFilter],
  );

  async function refreshAfterUndo() {
    await loadRuns();
    if (selectedRun) await loadActions(selectedRun);
  }

  function openConfirm(request: ConfirmRequest) {
    returnFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setConfirmRequest(request);
  }

  function confirmUndoRun() {
    if (!selectedRun || undoableCount === 0) return;
    const runId = selectedRun;
    const parts: string[] = [];
    if (blastRadius.moves > 0) {
      parts.push(
        `${pluralise(blastRadius.moves, "moved file")} put back where ` +
          `${blastRadius.moves === 1 ? "it" : "they"} came from`,
      );
    }
    if (blastRadius.copies > 0) {
      parts.push(`${pluralise(blastRadius.copies, "copy", "copies")} deleted`);
    }

    openConfirm({
      title: "Undo this entire run?",
      tone: "danger",
      confirmLabel: `Undo ${pluralise(undoableCount, "action")}`,
      body: (
        <div className="undo__confirm">
          <p className="undo__confirm-lead">
            Run <span className="mono">{runId}</span> recorded{" "}
            {pluralise(annotated.length, "action")}.
          </p>

          <dl className="undo__kv">
            <dt>Will be reversed</dt>
            <dd>
              <strong>{pluralise(undoableCount, "action")}</strong>
              {parts.length > 0 && <> — {parts.join(", ")}</>}.
            </dd>

            <dt>Cannot be reversed</dt>
            <dd>
              {blockedCount === 0 ? (
                <>None. Every action in this run can be undone.</>
              ) : (
                <>
                  <strong>{pluralise(blockedCount, "action")}</strong>, left exactly as they are
                  now:
                  <ul className="undo__confirm-list">
                    {blastRadius.reasons.map((entry) => (
                      <li key={entry.reason}>
                        {entry.count} × {entry.reason}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </dd>

            <dt>If one fails</dt>
            <dd>
              AutoTidy keeps going with the rest and lists every failure file by file when it
              finishes. A file that fails stays where it is now, and the reversals that already
              succeeded are <strong>not</strong> rolled back — you can be left part-way.
            </dd>
          </dl>

          <p className="undo__confirm-foot">
            Actions are reversed newest first. Moves go back to their original path; a copy is
            deleted only after AutoTidy checks its size and timestamp still match what it recorded.
            This writes to disk and cannot itself be undone from here.
          </p>
        </div>
      ),
      onConfirm: async () => {
        setWorking(true);
        try {
          const result = await undoRun(runId);
          setLastResult(result);
          push(
            result.failure_count > 0 ? "warning" : "success",
            `Undo finished — ${result.success_count} succeeded, ${result.failure_count} failed`,
            result.failure_count > 0 ? "See the results panel for the per-file detail." : undefined,
          );
          await refreshAfterUndo();
        } catch (err) {
          const message = errorMessage(err);
          setActionsError(message);
          push("error", "Undo failed", message);
        } finally {
          setWorking(false);
        }
      },
    });
  }

  function confirmUndoOne(record: HistoryRecord) {
    const isCopy = record.action_taken.toUpperCase() === "COPIED";
    openConfirm({
      title: "Undo this action?",
      tone: "danger",
      confirmLabel: "Undo it",
      body: (
        <div className="undo__confirm">
          <p className="undo__confirm-lead">
            One action will be reversed. The other{" "}
            {pluralise(Math.max(0, annotated.length - 1), "action")} in this run are left alone.
          </p>
          <dl className="undo__kv">
            <dt>Action</dt>
            <dd>{historyActionLabel(record.action_taken)}</dd>
            <dt>From</dt>
            <dd className="mono">{record.original_path}</dd>
            <dt>To</dt>
            <dd className="mono">{record.destination_path ?? "—"}</dd>
            <dt>What happens</dt>
            <dd>
              {isCopy
                ? "The copy is deleted, but only after AutoTidy verifies its size and timestamp still match what was recorded. The original is untouched either way."
                : "The file is moved back to its original location. If something already exists there, the move is refused rather than overwriting it."}
            </dd>
            <dt>If it fails</dt>
            <dd>
              The file stays exactly where it is now and nothing else in this run changes. You will
              get the reason in a notification.
            </dd>
          </dl>
        </div>
      ),
      onConfirm: async () => {
        setWorking(true);
        try {
          const message = await undoOne(record);
          push("success", "Action undone", message);
          await refreshAfterUndo();
        } catch (err) {
          const message = errorMessage(err);
          push("error", "Could not undo that action", message);
        } finally {
          setWorking(false);
        }
      },
    });
  }

  const scanDisabled = engineBusy || engineState === "scanning" || engineState === "stopping";

  const header = (
    <div className="view__header">
      <div className="view__heading">
        <h1 className="page-title">Undo</h1>
        <p className="page-subtitle">
          Reverse a batch of moves or copies. Deletions and dry runs cannot be reversed.
        </p>
      </div>
      <div className="view__actions">
        <button
          type="button"
          className="btn"
          onClick={() => void loadRuns()}
          disabled={runsLoading}
        >
          <IconRefresh />
          {runsLoading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
    </div>
  );

  // ---------------------------------------------------------------- states --
  // Failed-to-load and genuinely-empty are different situations with different
  // fixes, so they never share a panel: seeing "nothing here" when the real
  // problem is a read error reads as data loss.

  let body: ReactNode;

  if (runs === null && runsLoading) {
    body = (
      <div className="view__scroll">
        <Loading label="Reading run history…" />
      </div>
    );
  } else if (runsError !== null && (runs === null || runs.length === 0)) {
    // A failed read with nothing to fall back on. This branch has to win over
    // the zero state below: showing "no runs recorded" when the truth is "we
    // could not read them" reads as data loss.
    body = (
      <div className="view__scroll">
        <div className="undo__state undo__state--error" role="alert">
          <span className="undo__state-icon undo__state-icon--error" aria-hidden="true">
            <IconWarning size={30} />
          </span>
          <h2 className="undo__state-title">Could not load your undo history</h2>
          <p className="undo__state-body">
            AutoTidy could not read the run list from its history log. This is a read failure, not
            an empty history — nothing has been lost, and nothing has been changed on disk.
          </p>
          <pre className="undo__state-detail">{runsError}</pre>
          <div className="btn-row undo__state-actions">
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => void loadRuns()}
              disabled={runsLoading}
            >
              <IconRefresh />
              {runsLoading ? "Trying…" : "Try again"}
            </button>
          </div>
          <p className="undo__state-foot">
            If it keeps failing, open <span className="mono">autotidy_history.jsonl</span> from
            Settings → Configuration file to check the log is readable.
          </p>
        </div>
      </div>
    );
  } else if (runs !== null && runs.length === 0) {
    body = (
      <div className="view__scroll">
        <div className="undo__state">
          <span className="undo__state-icon" aria-hidden="true">
            <IconUndo size={30} />
          </span>
          <h2 className="undo__state-title">No runs recorded yet</h2>
          <p className="undo__state-body">
            AutoTidy groups everything a single scan does into one run. A run turns up here as soon
            as a scan actually moves or copies a file — dry runs change nothing, and deletions have
            nothing to reverse, so neither creates one.
          </p>
          <div className="btn-row undo__state-actions">
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => void scan()}
              disabled={scanDisabled}
              title={
                scanDisabled
                  ? "The engine is busy — wait for the current scan to finish"
                  : "Run a single pass over every enabled folder now"
              }
            >
              <IconRefresh />
              Run a scan now
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => void loadRuns()}
              disabled={runsLoading}
            >
              Check again
            </button>
          </div>
          <p className="undo__state-foot">
            A scan uses the rules you already have. If dry run is on in Settings it will still
            change nothing.
          </p>
        </div>
      </div>
    );
  } else {
    body = (
      <>
        {/* A refresh failed but the previous list is still on screen: warn in
            place rather than replacing data the user can still act on. */}
        {runsError !== null && (
          <div className="undo__banner" role="alert">
            <IconWarning />
            <div className="notice__body">
              <span className="notice__title">Could not refresh the run list</span>
              <span>
                This is the last list AutoTidy read successfully — it may be out of date.{" "}
                {runsError}
              </span>
            </div>
            <span className="spacer" />
            <button
              type="button"
              className="btn btn--sm"
              onClick={() => void loadRuns()}
              disabled={runsLoading}
            >
              Try again
            </button>
          </div>
        )}

        <div className="undo">
        <div className="undo__runs">
          <div className="undo__runs-head">Runs</div>
          <div className="undo__runs-scroll">
            {runsLoading && <Loading label="Reading run history…" />}

            {!runsLoading &&
              runs?.map((run) => (
                <button
                  key={run.run_id}
                  type="button"
                  className="runrow"
                  aria-current={run.run_id === selectedRun ? "true" : undefined}
                  onClick={() => setSelectedRun(run.run_id)}
                >
                  <span className="runrow__time">{formatTimestamp(run.start_time)}</span>
                  <span className="runrow__meta">
                    <span>{pluralise(run.action_count, "action")}</span>
                    <span>·</span>
                    <span>{relativeTime(run.start_time)}</span>
                  </span>
                </button>
              ))}
          </div>
        </div>

        <div className="undo__detail">
          {selectedRun === null ? (
            <div className="view__scroll">
              <EmptyState
                icon={<IconUndo size={30} />}
                title="Select a run"
                body="Pick a run on the left to see what AutoTidy did, then undo the whole batch or a single file."
              />
            </div>
          ) : (
            <>
              <div className="undo__detail-head">
                <div className="view__heading">
                  <h2 className="section-title" ref={detailHeadingRef} tabIndex={-1}>
                    Run {selectedRun}
                  </h2>
                  <span className="page-subtitle">
                    {currentRun ? formatTimestamp(currentRun.start_time) : ""} ·{" "}
                    {annotated.length} recorded ·{" "}
                    {undoableCount === 0 ? "none reversible" : `${undoableCount} reversible`}
                  </span>
                </div>
                <span className="spacer" />
                <button
                  type="button"
                  className="btn btn--danger"
                  onClick={confirmUndoRun}
                  disabled={working || undoableCount === 0}
                  title={
                    undoableCount === 0
                      ? "Nothing in this run can be reversed"
                      : `Reverse ${pluralise(undoableCount, "action")} — you will see the full detail before anything happens`
                  }
                >
                  <IconUndo />
                  Undo whole run
                </button>
              </div>

              <div className="undo__detail-scroll">
                {actionsLoading && <Loading label="Loading actions…" />}

                {actionsError && (
                  <ErrorNotice
                    title="Could not load this run"
                    message={actionsError}
                    onRetry={() => void loadActions(selectedRun)}
                  />
                )}

                {lastResult && lastResult.run_id === selectedRun && (
                  <div
                    className={
                      lastResult.failure_count > 0 ? "notice notice--warn" : "notice notice--ok"
                    }
                    role="status"
                  >
                    <div className="notice__body">
                      <span className="notice__title">
                        Undo result: {lastResult.success_count} succeeded,{" "}
                        {lastResult.failure_count} failed
                      </span>
                      {lastResult.messages.length > 0 && (
                        <ul style={{ marginTop: 4 }}>
                          {lastResult.messages.map((message, i) => (
                            <li key={i} className="mono">
                              {message}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                )}

                {actions && actions.length === 0 && !actionsLoading && (
                  <EmptyState
                    title="This run recorded no actions"
                    body="It may have been interrupted, or every file was skipped."
                  />
                )}

                {annotated.length > 0 && (
                  <>
                    <div className="undo__filter">
                      <span className="undo__filter-label" id="undo-filter-label">
                        Show
                      </span>
                      <div
                        className="undo__filter-group"
                        role="group"
                        aria-labelledby="undo-filter-label"
                      >
                        {(
                          [
                            ["all", `All ${annotated.length}`],
                            ["reversible", `Reversible ${undoableCount}`],
                            ["blocked", `Blocked ${blockedCount}`],
                          ] as Array<[RowFilter, string]>
                        ).map(([value, label]) => (
                          <button
                            key={value}
                            type="button"
                            className="undo__filter-btn"
                            aria-pressed={rowFilter === value}
                            onClick={() => setRowFilter(value)}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                      <span className="spacer" />
                      <span className="undo__filter-count" role="status">
                        {pluralise(visibleRows.length, "row")} shown
                      </span>
                    </div>

                    {visibleRows.length === 0 ? (
                      <EmptyState
                        title={
                          rowFilter === "reversible"
                            ? "Nothing in this run can be reversed"
                            : "Every action in this run can be reversed"
                        }
                        body={
                          rowFilter === "reversible"
                            ? "Every recorded action was a deletion, a dry run or a failure."
                            : "There is nothing blocked to look at."
                        }
                        action={
                          <button
                            type="button"
                            className="btn"
                            onClick={() => setRowFilter("all")}
                          >
                            Show all {annotated.length}
                          </button>
                        }
                      />
                    ) : (
                      <div className="undo__actions-wrap">
                        <table className="undo__actions">
                          <caption className="visually-hidden">
                            Actions recorded in this run
                          </caption>
                          <thead>
                            <tr>
                              <th scope="col">Time</th>
                              <th scope="col">Action</th>
                              <th scope="col">Original</th>
                              <th scope="col">Destination</th>
                              <th scope="col">Status</th>
                              <th scope="col">Undo</th>
                            </tr>
                          </thead>
                          <tbody>
                            {visibleRows.map(({ record, undoable, reason }, index) => (
                              <tr
                                key={`${record.timestamp}-${record.original_path}-${index}`}
                                className={undoable ? undefined : "is-blocked"}
                              >
                                <td style={{ whiteSpace: "nowrap" }}>
                                  {formatTimestamp(record.timestamp)}
                                </td>
                                <td>{historyActionLabel(record.action_taken)}</td>
                                <td className="undo__path">{record.original_path}</td>
                                <td className="undo__path">{record.destination_path ?? "—"}</td>
                                <td>
                                  <span
                                    className={
                                      record.status === "SUCCESS"
                                        ? "badge badge--ok"
                                        : record.status === "FAILURE"
                                          ? "badge badge--danger"
                                          : "badge badge--warn"
                                    }
                                  >
                                    {record.status}
                                  </span>
                                </td>
                                <td>
                                  {undoable ? (
                                    <button
                                      type="button"
                                      className="btn btn--sm"
                                      disabled={working}
                                      onClick={() => confirmUndoOne(record)}
                                    >
                                      <IconUndo />
                                      Undo
                                    </button>
                                  ) : (
                                    <span className="undo__reason">{reason}</span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </>
                )}
              </div>
            </>
          )}
        </div>
        </div>
      </>
    );
  }

  return (
    <div className="view">
      {header}
      {body}
      <ConfirmDialog request={confirmRequest} onClose={() => setConfirmRequest(null)} />
    </div>
  );
}
