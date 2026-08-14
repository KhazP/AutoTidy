import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
  type Column,
  type ColumnFiltersState,
  type FilterFn,
  type SortingState,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";

import { historyPage, revealInExplorer } from "../lib/api";
import { errorMessage } from "../lib/errors";
import { basename, formatTimestamp, historyActionLabel, statusTone } from "../lib/format";
import type { HistoryRecord } from "../lib/types";
import { useConfig } from "../state/ConfigProvider";
import { useEngine } from "../state/EngineProvider";
import { useToasts } from "../state/ToastProvider";
import { EmptyState, ErrorNotice } from "../components/common";
import { useNavigation } from "../components/Navigation";
import { IconExternal, IconHistory, IconRefresh, IconRules, IconScan, IconSearch } from "../components/icons";
import "./HistoryView.css";

/**
 * 1.5.0 loaded the last 500 records and offered a "Load All Entries" button
 * that froze the window on a large log. Here the table pulls the next chunk as
 * the viewport approaches the end of what is loaded, and only the rows on
 * screen are ever in the DOM.
 */
const PAGE_SIZE = 400;
const ROW_HEIGHT = 28;
const PREFETCH_ROWS = 40;

/**
 * Long enough that reading a local JSONL file — the overwhelmingly common
 * case — never flashes a skeleton, short enough that a slow read never shows a
 * blank rectangle. Anything under this threshold reads as instant anyway.
 */
const SKELETON_DELAY_MS = 180;
const SKELETON_ROWS = 14;
/** One entry per grid track in `--hist-cols`, including the trailing actions cell. */
const SKELETON_WIDTHS = ["116px", "84px", "54px", "82%", "72%", "56%", "34px"];

const STATUS_OPTIONS = ["SUCCESS", "FAILURE", "SKIPPED"];

const columnHelper = createColumnHelper<HistoryRecord>();

const globalFilterFn: FilterFn<HistoryRecord> = (row, _columnId, filterValue) => {
  const query = String(filterValue ?? "")
    .trim()
    .toLowerCase();
  if (query === "") return true;
  const r = row.original;
  return `${r.original_path} ${r.destination_path ?? ""} ${r.action_taken} ${r.details} ${r.run_id}`
    .toLowerCase()
    .includes(query);
};

/** Column-level presentation, read back off `columnDef.meta` when rendering cells. */
function cellClass(column: Column<HistoryRecord, unknown>): string {
  const meta = column.columnDef.meta as { className?: string } | undefined;
  return meta?.className ? `hist__td ${meta.className}` : "hist__td";
}

/**
 * `components/icons.tsx` has no clipboard glyph and is owned by another part of
 * the tree, so this one lives here rather than growing the shared set.
 */
function IconCopy({ size = 14 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.4}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable={false}
    >
      <rect x="5.7" y="5.7" width="7.5" height="7.5" rx="1.1" />
      <path d="M10.6 3.7V3a1.1 1.1 0 0 0-1.1-1.1H3.9A1.1 1.1 0 0 0 2.8 3v5.6a1.1 1.1 0 0 0 1.1 1.1h.7" />
    </svg>
  );
}

/** What a row's two actions point at. Never a destination that does not exist. */
function rowTarget(record: HistoryRecord) {
  const destination = record.destination_path;
  const hasDestination = typeof destination === "string" && destination.trim() !== "";
  const subject = basename(record.original_path) || record.original_path;
  return {
    path: hasDestination ? destination : record.original_path,
    hasDestination,
    subject,
  };
}

export function HistoryView() {
  const { dataRevision, scan, busy, status } = useEngine();
  const { config } = useConfig();
  const { push } = useToasts();
  const { navigate } = useNavigation();

  const [records, setRecords] = useState<HistoryRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState(-1);

  const [sorting, setSorting] = useState<SortingState>([{ id: "timestamp", desc: true }]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [globalFilter, setGlobalFilter] = useState("");

  const inFlight = useRef(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const wantsFocus = useRef(false);

  const fetchPage = useCallback(async (offset: number, replace: boolean) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setLoading(true);
    try {
      const page = await historyPage(offset, PAGE_SIZE);
      setRecords((prev) => (replace ? page.records : [...prev, ...page.records]));
      // An empty page means the backend has nothing more at this offset. Believe
      // that over the reported total, or the prefetch effect would re-request
      // the same offset forever.
      const loaded = offset + page.records.length;
      setTotal(page.records.length === 0 ? offset : Math.max(page.total, loaded));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
      inFlight.current = false;
    }
  }, []);

  const reload = useCallback(() => {
    setSelected(-1);
    setRecords([]);
    setError(null);
    void fetchPage(0, true);
  }, [fetchPage]);

  // Load on mount, and again whenever a scan finishes. Event-driven, not polled.
  useEffect(() => {
    reload();
  }, [reload, dataRevision]);

  const columns = useMemo(
    () => [
      columnHelper.accessor((r) => r.timestamp, {
        id: "timestamp",
        header: "Timestamp",
        meta: { className: "hist__td--time" },
        cell: (info) => formatTimestamp(info.getValue()),
      }),
      columnHelper.accessor((r) => r.action_taken, {
        id: "action_taken",
        header: "Action",
        filterFn: "equalsString",
        cell: (info) => historyActionLabel(info.getValue()),
      }),
      columnHelper.accessor((r) => r.status, {
        id: "status",
        header: "Status",
        filterFn: "equalsString",
        cell: (info) => {
          const tone = statusTone(info.getValue());
          return <span className={tone ? `badge badge--${tone}` : "badge"}>{info.getValue()}</span>;
        },
      }),
      columnHelper.accessor((r) => r.original_path, {
        id: "original_path",
        header: "Original path",
        meta: { className: "hist__td--path" },
        cell: (info) => info.getValue(),
      }),
      columnHelper.accessor((r) => r.destination_path ?? "", {
        id: "destination_path",
        header: "Destination",
        meta: { className: "hist__td--path" },
        cell: (info) => info.getValue() || "—",
      }),
      columnHelper.accessor((r) => r.details, {
        id: "details",
        header: "Details",
        cell: (info) => info.getValue() || "—",
      }),
    ],
    [],
  );

  const table = useReactTable({
    data: records,
    columns,
    state: { sorting, columnFilters, globalFilter },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onGlobalFilterChange: setGlobalFilter,
    globalFilterFn,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const rows = table.getRowModel().rows;

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 14,
  });

  const virtualItems = virtualizer.getVirtualItems();
  const lastVisibleIndex =
    virtualItems.length > 0 ? (virtualItems[virtualItems.length - 1]?.index ?? -1) : -1;

  // Pull the next chunk once the viewport nears the end of what is loaded.
  useEffect(() => {
    if (loading || error !== null) return;
    if (records.length >= total) return;
    if (lastVisibleIndex >= rows.length - PREFETCH_ROWS) {
      void fetchPage(records.length, false);
    }
  }, [lastVisibleIndex, rows.length, records.length, total, loading, error, fetchPage]);

  // Runs after every render on purpose: the ref guard makes it a no-op except
  // on the render where a keyboard-selected row finally exists in the DOM.
  useEffect(() => {
    if (!wantsFocus.current) return;
    const el = scrollRef.current?.querySelector<HTMLElement>(`[data-rowindex="${selected}"]`);
    if (el) {
      wantsFocus.current = false;
      el.focus();
    }
  });

  const selectedRecord = selected >= 0 ? rows[selected]?.original : undefined;

  const reveal = useCallback(
    (path: string | null | undefined) => {
      if (!path) return;
      void revealInExplorer(path).catch((err: unknown) => {
        push("error", "Could not open that location", errorMessage(err));
      });
    },
    [push],
  );

  const copyPath = useCallback(
    (path: string | null | undefined) => {
      if (!path) return;
      const write = navigator.clipboard?.writeText(path);
      if (!write) {
        push("error", "Could not copy the path", "The clipboard is not available.");
        return;
      }
      write.then(
        () => push("success", "Path copied", path),
        (err: unknown) => push("error", "Could not copy the path", errorMessage(err)),
      );
    },
    [push],
  );

  function moveTo(index: number) {
    const clamped = Math.min(rows.length - 1, Math.max(0, index));
    setSelected(clamped);
    virtualizer.scrollToIndex(clamped, { align: "auto" });
    // Roving tabindex only works if focus follows selection; the row may not be
    // mounted yet, so the effect below picks it up once the virtualiser renders it.
    wantsFocus.current = true;
  }

  function onRowKeyDown(event: KeyboardEvent<HTMLTableRowElement>, index: number) {
    // Enter/Space belong to whichever row action has focus, not to the row.
    const onControl =
      event.target instanceof HTMLElement && event.target.closest("button") !== null;

    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      moveTo(index + (event.key === "ArrowDown" ? 1 : -1));
    } else if (event.key === "Home") {
      event.preventDefault();
      moveTo(0);
    } else if (event.key === "End") {
      event.preventDefault();
      moveTo(rows.length - 1);
    } else if (event.key === "Enter" && !onControl) {
      event.preventDefault();
      const record = rows[index]?.original;
      if (record) reveal(rowTarget(record).path);
    }
  }

  const filterValue = (id: string) => String(columnFilters.find((f) => f.id === id)?.value ?? "");

  const setFilter = (id: string, value: string) =>
    setColumnFilters((prev) => {
      const rest = prev.filter((f) => f.id !== id);
      return value === "" ? rest : [...rest, { id, value }];
    });

  const knownActions = useMemo(() => {
    const set = new Set<string>();
    for (const record of records) set.add(record.action_taken);
    return [...set].sort();
  }, [records]);

  const statusFilter = filterValue("status");
  const actionFilter = filterValue("action_taken");
  const search = globalFilter.trim();
  const filtersActive = columnFilters.length > 0 || search !== "";
  const allLoaded = records.length >= total;

  function clearFilters() {
    setColumnFilters([]);
    setGlobalFilter("");
  }

  /** Named, individually removable — the no-results state lists these verbatim. */
  const activeFilters: Array<{ key: string; label: string; clear: () => void }> = [];
  if (search !== "") {
    activeFilters.push({
      key: "search",
      label: `search “${search}”`,
      clear: () => setGlobalFilter(""),
    });
  }
  if (statusFilter !== "") {
    activeFilters.push({
      key: "status",
      label: `status ${statusFilter}`,
      clear: () => setFilter("status", ""),
    });
  }
  if (actionFilter !== "") {
    activeFilters.push({
      key: "action",
      label: `action “${historyActionLabel(actionFilter)}”`,
      clear: () => setFilter("action_taken", ""),
    });
  }

  // -- which of the four body states are we in? ------------------------------
  //
  // These are mutually exclusive on purpose. In particular the error state is
  // never dressed up as an empty one: an unreadable log looks nothing like a
  // log with no entries, because confusing the two reads as data loss.

  const initialLoad = loading && records.length === 0 && error === null;
  const fatalError = error !== null && records.length === 0;
  const zeroState = !initialLoad && !fatalError && records.length === 0;
  const noResults = !initialLoad && !fatalError && records.length > 0 && rows.length === 0;

  const [showSkeleton, setShowSkeleton] = useState(false);
  useEffect(() => {
    if (!initialLoad) {
      setShowSkeleton(false);
      return;
    }
    const timer = window.setTimeout(() => setShowSkeleton(true), SKELETON_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [initialLoad]);

  const hasEnabledRules = config?.folders.some((rule) => rule.enabled) ?? false;
  const scanDisabled = busy || status === "scanning" || status === "stopping";

  return (
    <div className="view">
      <div className="view__header">
        <div className="view__heading">
          <h1 className="page-title">History</h1>
          <p className="page-subtitle">Every action AutoTidy has taken, newest first.</p>
        </div>
        <div className="view__actions">
          <button type="button" className="btn" onClick={reload} disabled={loading}>
            <IconRefresh />
            Refresh
          </button>
        </div>
      </div>

      <div className="hist">
        <div className="hist__filters">
          <div className="field hist__search">
            <label className="field__label" htmlFor="hist-search">
              Search
            </label>
            <input
              id="hist-search"
              type="search"
              className="input"
              data-filtered={search !== "" ? "true" : undefined}
              placeholder="Path, action, details or run id…"
              value={globalFilter}
              onChange={(e) => setGlobalFilter(e.target.value)}
            />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="hist-status">
              Status
            </label>
            <select
              id="hist-status"
              className="select"
              data-filtered={statusFilter !== "" ? "true" : undefined}
              style={{ width: 150 }}
              value={statusFilter}
              onChange={(e) => setFilter("status", e.target.value)}
            >
              <option value="">All statuses</option>
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label className="field__label" htmlFor="hist-action">
              Action
            </label>
            <select
              id="hist-action"
              className="select"
              data-filtered={actionFilter !== "" ? "true" : undefined}
              style={{ width: 190 }}
              value={actionFilter}
              onChange={(e) => setFilter("action_taken", e.target.value)}
            >
              <option value="">All actions</option>
              {knownActions.map((a) => (
                <option key={a} value={a}>
                  {historyActionLabel(a)}
                </option>
              ))}
            </select>
          </div>

          {filtersActive && (
            <button type="button" className="btn" onClick={clearFilters}>
              Clear filters
            </button>
          )}

          <span className="spacer" />
          <span className="hist__count">
            {rows.length.toLocaleString()} shown · {records.length.toLocaleString()} loaded
            {total > 0 ? ` of ${total.toLocaleString()}` : ""}
          </span>
          {/* Announced only while filtering, so infinite scroll stays quiet. */}
          <span className="visually-hidden" role="status">
            {filtersActive ? `${rows.length} entries match the current filters.` : ""}
          </span>
        </div>

        {fatalError ? (
          <div className="hist__state hist__state--error">
            <div className="hist__state-inner">
              <ErrorNotice
                title="Could not read the history log"
                message={error}
                onRetry={reload}
                retryLabel="Try again"
              />
              <p className="hist__state-note">
                This is a read failure, not an empty history — nothing has been deleted. AutoTidy
                reads <code>autotidy_history.jsonl</code> from its app-data folder; if another
                program is holding that file open, close it and try again.
              </p>
            </div>
          </div>
        ) : zeroState ? (
          <EmptyState
            icon={<IconHistory size={30} />}
            title="No history yet"
            body={
              hasEnabledRules
                ? "Every file AutoTidy moves, copies or deletes gets a row here — including dry-run simulations, which are logged but change nothing on disk. Run a scan to fill it in."
                : "Every file AutoTidy moves, copies or deletes gets a row here — including dry-run simulations. Nothing can be logged yet because no folder is being watched."
            }
            action={
              <>
                {hasEnabledRules ? (
                  <button
                    type="button"
                    className="btn btn--primary"
                    onClick={() => void scan()}
                    disabled={scanDisabled}
                  >
                    <IconScan />
                    Run a scan now
                  </button>
                ) : (
                  <button type="button" className="btn btn--primary" onClick={() => navigate("rules")}>
                    <IconRules />
                    Add your first rule
                  </button>
                )}
                <button type="button" className="btn" onClick={reload} disabled={loading}>
                  <IconRefresh />
                  Check again
                </button>
              </>
            }
          />
        ) : noResults ? (
          <EmptyState
            icon={<IconSearch size={30} />}
            title="No entries match these filters"
            body={
              <>
                None of the {records.length.toLocaleString()} loaded{" "}
                {records.length === 1 ? "entry matches" : "entries match"}{" "}
                {activeFilters.map((f) => f.label).join(" and ")}.
                {!allLoaded &&
                  ` ${(total - records.length).toLocaleString()} older entries are still being read in — a match may yet turn up.`}
              </>
            }
            action={
              <>
                {activeFilters.map((f) => (
                  <button key={f.key} type="button" className="btn btn--sm" onClick={f.clear}>
                    Clear {f.label}
                  </button>
                ))}
                {activeFilters.length > 1 && (
                  <button type="button" className="btn btn--primary" onClick={clearFilters}>
                    Clear all filters
                  </button>
                )}
              </>
            }
          />
        ) : (
          <div className="hist__scroll" ref={scrollRef}>
            {/*
              Real table elements keep `scope="col"` and native semantics, while
              explicit ARIA roles survive the CSS `display` overrides that
              virtualisation needs.
            */}
            <table className="hist__table" role="table" aria-rowcount={rows.length} aria-label="Action history">
              <thead className="hist__head" role="rowgroup">
                {table.getHeaderGroups().map((headerGroup) => (
                  <tr className="hist__headrow" role="row" key={headerGroup.id}>
                    {headerGroup.headers.map((header) => {
                      const sorted = header.column.getIsSorted();
                      const label = String(header.column.columnDef.header ?? header.id);
                      return (
                        <th
                          key={header.id}
                          className="hist__th"
                          role="columnheader"
                          scope="col"
                          aria-sort={
                            sorted === "asc"
                              ? "ascending"
                              : sorted === "desc"
                                ? "descending"
                                : "none"
                          }
                        >
                          <button
                            type="button"
                            className="hist__sort"
                            title={
                              sorted === "asc"
                                ? `Sorted by ${label}, oldest first. Click to reverse.`
                                : sorted === "desc"
                                  ? `Sorted by ${label}, newest first. Click to reverse.`
                                  : `Sort by ${label}`
                            }
                            onClick={header.column.getToggleSortingHandler()}
                          >
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            <span aria-hidden="true">
                              {sorted === "asc" ? "▲" : sorted === "desc" ? "▼" : ""}
                            </span>
                          </button>
                        </th>
                      );
                    })}
                    {/*
                      Rendered outside the column model: it carries no data, so
                      it must never be sortable, filterable or searchable.
                    */}
                    <th className="hist__th hist__th--actions" role="columnheader" scope="col">
                      Actions
                    </th>
                  </tr>
                ))}
              </thead>

              {showSkeleton ? (
                <tbody
                  key="skeleton"
                  className="hist__body hist__body--skeleton"
                  role="rowgroup"
                  aria-hidden="true"
                  style={{ height: SKELETON_ROWS * ROW_HEIGHT }}
                >
                  {Array.from({ length: SKELETON_ROWS }, (_, i) => (
                    <tr
                      key={i}
                      className="hist__row hist__row--skeleton"
                      role="row"
                      style={{ height: ROW_HEIGHT, transform: `translateY(${i * ROW_HEIGHT}px)` }}
                    >
                      {SKELETON_WIDTHS.map((width, c) => (
                        <td key={c} role="cell" className="hist__td">
                          <span className="hist__sk" style={{ width }} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              ) : (
                <tbody
                  key="rows"
                  className="hist__body"
                  role="rowgroup"
                  style={{ height: virtualizer.getTotalSize() }}
                >
                  {virtualItems.map((virtualRow) => {
                    const row = rows[virtualRow.index];
                    if (!row) return null;
                    const isSelected = virtualRow.index === selected;
                    // One tab stop per row, not per button: the row and its two
                    // actions share the roving tabindex, so Tab reaches the
                    // actions of the current row and nothing else.
                    const tabbable = isSelected || (selected === -1 && virtualRow.index === 0);
                    const target = rowTarget(row.original);
                    return (
                      <tr
                        key={row.id}
                        className="hist__row"
                        role="row"
                        data-rowindex={virtualRow.index}
                        aria-rowindex={virtualRow.index + 1}
                        aria-current={isSelected ? "true" : undefined}
                        tabIndex={tabbable ? 0 : -1}
                        style={{ height: ROW_HEIGHT, transform: `translateY(${virtualRow.start}px)` }}
                        onClick={() => setSelected(virtualRow.index)}
                        onDoubleClick={() => reveal(target.path)}
                        onKeyDown={(e) => onRowKeyDown(e, virtualRow.index)}
                      >
                        {row.getVisibleCells().map((cell) => {
                          const raw = cell.getValue();
                          return (
                            <td
                              key={cell.id}
                              role="cell"
                              className={cellClass(cell.column)}
                              title={typeof raw === "string" && raw !== "" ? raw : undefined}
                            >
                              {flexRender(cell.column.columnDef.cell, cell.getContext())}
                            </td>
                          );
                        })}
                        <td role="cell" className="hist__td hist__td--actions">
                          <button
                            type="button"
                            className="hist__rowbtn"
                            tabIndex={tabbable ? 0 : -1}
                            aria-label={
                              target.hasDestination
                                ? `Show where “${target.subject}” was put, in Explorer`
                                : `Show “${target.subject}” in Explorer`
                            }
                            title={`Show in Explorer\n${target.path}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelected(virtualRow.index);
                              reveal(target.path);
                            }}
                          >
                            <IconExternal size={14} />
                          </button>
                          <button
                            type="button"
                            className="hist__rowbtn"
                            tabIndex={tabbable ? 0 : -1}
                            aria-label={
                              target.hasDestination
                                ? `Copy the destination path for “${target.subject}”`
                                : `Copy the path of “${target.subject}”`
                            }
                            title={`Copy path\n${target.path}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelected(virtualRow.index);
                              copyPath(target.path);
                            }}
                          >
                            <IconCopy />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              )}
            </table>

            {showSkeleton && (
              <p className="hist__loading" role="status">
                <span className="hist__spinner" aria-hidden="true" />
                Reading the history log…
              </p>
            )}
          </div>
        )}

        {selectedRecord && (
          <div className="hist__detail">
            <div className="btn-row">
              <strong>{basename(selectedRecord.original_path)}</strong>
              <span className="spacer" />
              <button
                type="button"
                className="btn btn--sm"
                onClick={() => reveal(selectedRecord.original_path)}
              >
                <IconExternal />
                Show original
              </button>
              <button
                type="button"
                className="btn btn--sm"
                onClick={() => reveal(selectedRecord.destination_path)}
                disabled={!selectedRecord.destination_path}
              >
                <IconExternal />
                Show destination
              </button>
              <button
                type="button"
                className="btn btn--sm"
                onClick={() => copyPath(rowTarget(selectedRecord).path)}
              >
                <IconCopy />
                Copy path
              </button>
              <button type="button" className="btn btn--sm" onClick={() => setSelected(-1)}>
                Close
              </button>
            </div>
            <dl className="hist__detailgrid">
              <dt>Original</dt>
              <dd>{selectedRecord.original_path}</dd>
              <dt>Destination</dt>
              <dd>{selectedRecord.destination_path ?? "—"}</dd>
              <dt>Monitored folder</dt>
              <dd>{selectedRecord.monitored_folder ?? "—"}</dd>
              <dt>Rule</dt>
              <dd>
                {selectedRecord.rule_use_regex ? "regex" : "glob"} “{selectedRecord.rule_pattern}”,
                min age {selectedRecord.rule_age_days}d, {selectedRecord.rule_action_config}
              </dd>
              <dt>Details</dt>
              <dd>{selectedRecord.details || "—"}</dd>
              <dt>Run</dt>
              <dd>{selectedRecord.run_id || "(pre-dates run grouping)"}</dd>
            </dl>
          </div>
        )}

        <div className="hist__footer">
          <span className="hist__footstat">
            {loading && (
              <span className="hist__spinner hist__spinner--sm" aria-hidden="true" />
            )}
            {loading
              ? records.length === 0
                ? "Reading the history log…"
                : `Loading more — ${records.length.toLocaleString()} of ${total.toLocaleString()} read.`
              : total === 0
                ? "Nothing logged yet."
                : allLoaded
                  ? `All ${total.toLocaleString()} entries loaded.`
                  : `Scroll for more — ${(total - records.length).toLocaleString()} not loaded yet.`}
          </span>
          {error && records.length > 0 && (
            <span style={{ color: "var(--danger)" }}>{error}</span>
          )}
          <span className="spacer" />
          {rows.length > 0 && (
            <span>Enter or double-click opens a row in Explorer; Tab reaches its actions.</span>
          )}
        </div>
      </div>
    </div>
  );
}
