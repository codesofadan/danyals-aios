"use client";

import { useState } from "react";
import {
  VISIBILITY_META,
  type MessageVisibility,
  type ThreadEntity,
  type ThreadMessage,
} from "@/lib/threads";
import { usePostMessage, useThread } from "@/lib/hooks/threads";

// The staff side of a discussion thread — on a task, or on a client request.
//
// THE COMPOSER'S DEFAULT IS AN INTERNAL NOTE, and the control that changes it is a
// visible, two-state choice rather than a checkbox tucked under the box. Writing to
// the client is the consequential action here: an internal note posted as a reply
// reaches someone it was never meant for, and cannot be recalled — `thread_messages`
// is append-only at the database.
//
// So the send button says which of the two it is doing, and the composer changes
// colour with the choice. The label is the confirmation.
export default function ThreadPanel({
  entity,
  code,
  clientLinked,
}: {
  entity: ThreadEntity;
  code: string;
  /** Whether the entity has a client. With none, "reply to client" reaches nobody. */
  clientLinked?: boolean;
}) {
  const thread = useThread(entity, code);
  const post = usePostMessage(entity, code);
  const [body, setBody] = useState("");
  const [visibility, setVisibility] = useState<MessageVisibility>("internal");

  const messages = thread.data ?? [];
  const canSend = body.trim().length > 0 && !post.isPending;

  // Addressing the client is only offered where a client can actually read it.
  //
  // A TASK thread never reaches one: `portal_threads` filters `entity_type='ticket'`,
  // so a task's discussion is agency-internal by construction even when the task is
  // about a client's account. Offering "Reply to client" there would be a control
  // that silently does nothing - the message would be filed as client-visible and no
  // client would ever see it, which is worse than not offering it.
  const canAddressClient = entity === "ticket" && clientLinked !== false;

  function send() {
    if (!canSend) return;
    post.mutate(
      { body: body.trim(), visibility },
      { onSuccess: () => setBody("") },
    );
  }

  return (
    <div className={`th-panel${visibility === "client_visible" ? " to-client" : ""}`}>
      <div className="th-head">
        <span className="material-symbols-rounded">forum</span>
        <span className="th-title">Discussion</span>
        <span className="th-count">{messages.length}</span>
      </div>

      <div className="th-list">
        {thread.isLoading && <div className="th-state">Loading the conversation…</div>}
        {thread.isError && !thread.isLoading && (
          <div className="th-state err" role="alert">
            Couldn&apos;t load the discussion — {(thread.error as Error)?.message ?? "try again"}.
            <button type="button" className="mini-btn" onClick={() => void thread.refetch()}>
              Retry
            </button>
          </div>
        )}
        {!thread.isLoading && !thread.isError && messages.length === 0 && (
          <div className="th-state">
            Nothing here yet — start the conversation.
          </div>
        )}
        {messages.map((m) => (
          <Message key={m.id} message={m} />
        ))}
      </div>

      {post.error instanceof Error && (
        <div className="th-state err" role="alert">
          Couldn&apos;t post — {post.error.message}
        </div>
      )}

      <div className="th-composer">
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder={
            visibility === "internal"
              ? "Add an internal note for the team…"
              : "Write a reply the client will see…"
          }
          rows={3}
          aria-label={VISIBILITY_META[visibility].label}
          onKeyDown={(e) => {
            // Ctrl/Cmd+Enter sends; a bare Enter must not, or a half-typed reply to a
            // client goes out on a stray keystroke and cannot be taken back.
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              send();
            }
          }}
        />

        <div className="th-actions">
          {canAddressClient && (
            <div className="seg th-vis" role="tablist" aria-label="Who can see this message">
              {(["internal", "client_visible"] as MessageVisibility[]).map((v) => (
                <button
                  key={v}
                  type="button"
                  role="tab"
                  aria-selected={visibility === v}
                  className={visibility === v ? "on" : ""}
                  onClick={() => setVisibility(v)}
                  title={VISIBILITY_META[v].hint}
                >
                  <span className="material-symbols-rounded">{VISIBILITY_META[v].icon}</span>
                  {VISIBILITY_META[v].label}
                </button>
              ))}
            </div>
          )}

          <button type="button" className="primary-btn" disabled={!canSend} onClick={send}>
            <span className="material-symbols-rounded">
              {visibility === "client_visible" ? "send" : "lock"}
            </span>
            {post.isPending
              ? "Posting…"
              : visibility === "client_visible"
                ? "Send to client"
                : "Add internal note"}
          </button>
        </div>

        <div className="th-hint">{VISIBILITY_META[visibility].hint}. Messages cannot be edited or deleted once posted.</div>
      </div>
    </div>
  );
}

function Message({ message }: { message: ThreadMessage }) {
  const meta = VISIBILITY_META[message.visibility];
  return (
    <div className={`th-msg ${message.visibility}`}>
      <div className="th-msg-top">
        <span className="th-author">{message.author}</span>
        {message.authorKind === "client" && <span className="th-who">Client</span>}
        <span className={`th-vis-tag ${meta.cls}`} title={meta.hint}>
          <span className="material-symbols-rounded">{meta.icon}</span>
          {meta.label}
        </span>
        <span className="th-when">{message.ago}</span>
      </div>
      <div className="th-body">{message.body}</div>
    </div>
  );
}
