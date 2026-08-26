"use client";

// One table, instead of thirty-three.
//
// There were 33 raw `<table>` elements across 32 files and no shared component,
// so every board re-implemented the same three-branch body by hand — 20 verbatim
// copies of:
//
//     {q.isError && !q.isLoading && (<tr>…error row…</tr>)}
//     {!q.isLoading && !q.isError && rows.map(…)}
//     {!q.isLoading && !q.isError && rows.length === 0 && (<tr>…empty row…</tr>)}
//
// That pattern is CORRECT — it is the shape this component preserves. The
// problem was that it existed 20 times, which is exactly why 24 OTHER files
// never got it and silently render an empty table when the request failed.
//
// TWO BUGS THE COPY-PASTE KEPT PRODUCING:
//   - `colSpan` is written by hand and drifts from the column count, so a
//     "no rows" message stops spanning the table the moment a column is added.
//     Here it is derived.
//   - A clickable row done as `<tr onClick>` is unreachable by keyboard;
//     Web2CampaignBoard.tsx shipped exactly that. `onRowClick` wires
//     tabIndex/role/Enter/Space, so a row cannot be made mouse-only by accident.
//
// RESPONSIVE BY CONSTRUCTION. Not one `@media` rule in this codebase touches a
// table, `thead`, `th` or `td` — mobile coverage for admin boards is entirely a
// matter of whether the author remembered `.tbl-wrap` (overflow-x: auto), and
// most did not. Rendering the wrapper here means every adopter scrolls instead
// of forcing the page sideways.

import type { ReactNode } from "react";

export type Column<Row> = {
  /** Stable identity for the column; also the React key. */
  key: string;
  header: ReactNode;
  cell: (row: Row) => ReactNode;
  /** Right-aligns via the existing `.num` convention. Use for figures. */
  numeric?: boolean;
  /** Extra class on the cell, for the per-board treatments already in the CSS. */
  className?: string;
};

/** The parts of a react-query result this needs. Structural, so tests can fake it. */
export type TableQuery = {
  isLoading?: boolean;
  isPending?: boolean;
  isError?: boolean;
};

export type DataTableProps<Row> = {
  columns: Column<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  /** Drives the loading and failure branches. Omit for a table over local data. */
  query?: TableQuery;
  /** The subject, in the operator's words: "backlinks", "gated calls". */
  label: string;
  /** Shown when the request SUCCEEDED and returned nothing. */
  empty?: ReactNode;
  /** Makes rows activatable by mouse AND keyboard. */
  onRowClick?: (row: Row) => void;
  /** Extra classes on the <table>, e.g. the board's own `op-tbl`. */
  tableClassName?: string;
  caption?: string;
};

export default function DataTable<Row>({
  columns,
  rows,
  rowKey,
  query,
  label,
  empty,
  onRowClick,
  tableClassName,
  caption,
}: DataTableProps<Row>) {
  const loading = Boolean(query?.isLoading ?? query?.isPending);
  const failed = Boolean(query?.isError);
  const span = columns.length; // derived, so it cannot drift from the columns

  return (
    <div className="tbl-wrap">
      <table className={tableClassName ? `tbl ${tableClassName}` : "tbl"}>
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={c.numeric ? "num" : undefined} scope="col">
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading && !failed ? (
            <tr>
              <td colSpan={span} className="op-empty" role="status">
                Loading {label}…
              </td>
            </tr>
          ) : null}

          {/* FAILURE OUTRANKS EMPTY. Showing "nothing here" for a failed read is
              the exact lie the honesty work removed from the KPI tiles. */}
          {failed ? (
            <tr>
              <td colSpan={span} className="op-empty" role="alert">
                Couldn&apos;t load {label} — these rows are unavailable, not absent.
              </td>
            </tr>
          ) : null}

          {!loading && !failed
            ? rows.map((row) => {
                const key = rowKey(row);
                const clickable = Boolean(onRowClick);
                return (
                  <tr
                    key={key}
                    className={clickable ? "row-clickable" : undefined}
                    style={clickable ? { cursor: "pointer" } : undefined}
                    tabIndex={clickable ? 0 : undefined}
                    role={clickable ? "button" : undefined}
                    onClick={clickable ? () => onRowClick?.(row) : undefined}
                    onKeyDown={
                      clickable
                        ? (e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              onRowClick?.(row);
                            }
                          }
                        : undefined
                    }
                  >
                    {columns.map((c) => (
                      <td
                        key={c.key}
                        className={[c.numeric ? "num" : null, c.className]
                          .filter(Boolean)
                          .join(" ") || undefined}
                      >
                        {c.cell(row)}
                      </td>
                    ))}
                  </tr>
                );
              })
            : null}

          {!loading && !failed && rows.length === 0 ? (
            <tr>
              <td colSpan={span} className="op-empty" role="status">
                {empty ?? `No ${label} yet.`}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}
