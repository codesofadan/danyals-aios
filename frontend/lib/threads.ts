// ============================================================
// AIOS · discussion threads (migration 0098)
//
// One primitive for every conversation about work: a thread hangs off a task or a
// client request, and carries messages. Before this there was none — a task had no
// comment field, a ticket had a single `reply` column, and team↔client was a void.
//
// TWO SHAPES, NOT ONE, and the difference is the whole safety property:
//
//   ThreadMessage  — the STAFF view. Carries `visibility`, so a team member can see
//                    at a glance whether a note is internal or something the client
//                    can read.
//   PortalMessage  — the CLIENT view. Has NO `visibility` field, because the backend
//                    view it comes from (`portal_thread_messages`) never selects an
//                    internal row. The field would be a constant; its absence is a
//                    second, independent statement of the boundary.
//
// Both are contract-locked to their response models (test_contract_lock).
// ============================================================

/** What a thread can hang off. A closed set — each value implies a tenancy rule. */
export type ThreadEntity = "task" | "ticket";

/** Internal notes never leave the staff surface. */
export type MessageVisibility = "internal" | "client_visible";

/** Who wrote it. `author_id` is never sent to either audience. */
export type MessageAuthorKind = "staff" | "client";

/** One message, staff view — internal notes included. */
export type ThreadMessage = {
  id: string;
  author: string;
  authorKind: MessageAuthorKind;
  body: string;
  visibility: MessageVisibility;
  createdAt: string;
  ago: string;
};

/** One message, client view. No `visibility`, by construction. */
export type PortalMessage = {
  id: string;
  author: string;
  authorKind: MessageAuthorKind;
  body: string;
  createdAt: string;
  ago: string;
};

export const VISIBILITY_META: Record<
  MessageVisibility,
  { label: string; hint: string; icon: string; cls: string }
> = {
  internal: {
    label: "Internal note",
    hint: "Only the team sees this",
    icon: "lock",
    cls: "mut",
  },
  client_visible: {
    label: "Reply to client",
    hint: "The client will see this in their portal",
    icon: "send",
    cls: "ok",
  },
};
