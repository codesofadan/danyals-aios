"use client";

import { Fragment, useState, type Key, type ReactNode } from "react";

type ReadMoreProps<T> = {
  /** Full list of items — only the first `initialCount` render until expanded. */
  items: T[];
  /** Renders a single item. Receives the item and its index in the full array. */
  renderItem: (item: T, index: number) => ReactNode;
  /** Stable React key for each item; defaults to its index in `items`. */
  getKey?: (item: T, index: number) => Key;
  /** How many items show before the "Read more" control appears. Default 10. */
  initialCount?: number;
  /**
   * Render the toggle as a `<tr>` spanning this many columns — use inside a
   * `<tbody>` so the control doesn't break the table markup. Omit for
   * non-table lists (the control renders as a plain wrapping div instead).
   */
  tableColSpan?: number;
  /** Extra class merged onto the default toggle wrapper (ignored when tableColSpan is set). */
  controlClassName?: string;
  /** Override the "Read more (N more)" copy; receives the number of hidden items. */
  moreLabel?: (remaining: number) => string;
};

// Shared list-capping helper: renders only the first `initialCount` items, with a
// "Read more" control that reveals the rest (and collapses back to "Show less").
// Used wherever a list can grow unbounded — kanban columns, review queues,
// ledgers, change feeds, recommendations, vault keys, integrations — so no
// single list can dominate the page. Purely a rendering helper; callers still
// own filtering/sorting of `items` before handing them in.
export default function ReadMore<T>({
  items,
  renderItem,
  getKey,
  initialCount = 10,
  tableColSpan,
  controlClassName,
  moreLabel,
}: ReadMoreProps<T>) {
  const [expanded, setExpanded] = useState(false);
  const hasMore = items.length > initialCount;
  const visible = !hasMore || expanded ? items : items.slice(0, initialCount);
  const remaining = items.length - initialCount;

  const toggle = (
    <button type="button" className="ghostbtn read-more-btn" onClick={() => setExpanded((v) => !v)}>
      <span className="material-symbols-rounded">{expanded ? "expand_less" : "expand_more"}</span>
      {expanded ? "Show less" : moreLabel ? moreLabel(remaining) : `Read more (${remaining} more)`}
    </button>
  );

  return (
    <>
      {visible.map((item, i) => (
        <Fragment key={getKey ? getKey(item, i) : i}>{renderItem(item, i)}</Fragment>
      ))}
      {hasMore &&
        (tableColSpan ? (
          <tr className="read-more-row">
            <td colSpan={tableColSpan}>{toggle}</td>
          </tr>
        ) : (
          <div className={`read-more-control${controlClassName ? ` ${controlClassName}` : ""}`}>{toggle}</div>
        ))}
    </>
  );
}
