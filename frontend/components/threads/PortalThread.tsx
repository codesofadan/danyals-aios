"use client";

import { useState } from "react";
import { usePortalThread, usePostPortalMessage } from "@/lib/hooks/threads";

// The CLIENT side of a conversation on their own request.
//
// There is no visibility control, because a client has no such choice: everything they
// write is for the agency, and everything they READ has already been filtered by
// `portal_thread_messages` at the database — a message marked internal is never
// selected, so this component is not the thing keeping it hidden and does not have to
// be trusted to.
//
// Collapsed by default. A request list where every row is an open transcript is
// unreadable; the count on the toggle is what tells the client there is something to
// read.
export default function PortalThread({ code }: { code: string }) {
  const [open, setOpen] = useState(false);
  const thread = usePortalThread(open ? code : null);
  const post = usePostPortalMessage(code);
  const [body, setBody] = useState("");

  const messages = thread.data ?? [];
  const canSend = body.trim().length > 0 && !post.isPending;

  function send() {
    if (!canSend) return;
    post.mutate(body.trim(), { onSuccess: () => setBody("") });
  }

  if (!open) {
    return (
      <button type="button" className="cl-req-thread-open" onClick={() => setOpen(true)}>
        <span className="material-symbols-rounded">forum</span>
        View conversation &amp; reply
      </button>
    );
  }

  return (
    <div className="th-panel portal">
      <div className="th-head">
        <span className="material-symbols-rounded">forum</span>
        <span className="th-title">Conversation</span>
        <button type="button" className="mini-btn" onClick={() => setOpen(false)}>Hide</button>
      </div>

      <div className="th-list">
        {thread.isLoading && <div className="th-state">Loading…</div>}
        {thread.isError && !thread.isLoading && (
          <div className="th-state err" role="alert">
            Couldn&apos;t load the conversation.
            <button type="button" className="mini-btn" onClick={() => void thread.refetch()}>
              Retry
            </button>
          </div>
        )}
        {!thread.isLoading && !thread.isError && messages.length === 0 && (
          <div className="th-state">No replies yet — add a message below and we&apos;ll pick it up.</div>
        )}
        {messages.map((m) => (
          <div className={`th-msg ${m.authorKind === "client" ? "mine" : ""}`} key={m.id}>
            <div className="th-msg-top">
              <span className="th-author">{m.authorKind === "client" ? "You" : m.author}</span>
              <span className="th-when">{m.ago}</span>
            </div>
            <div className="th-body">{m.body}</div>
          </div>
        ))}
      </div>

      {post.error instanceof Error && (
        <div className="th-state err" role="alert">Couldn&apos;t send — {post.error.message}</div>
      )}

      <div className="th-composer">
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Add to this request…"
          rows={3}
          aria-label="Your message"
        />
        <div className="th-actions">
          <button type="button" className="primary-btn" disabled={!canSend} onClick={send}>
            <span className="material-symbols-rounded">send</span>
            {post.isPending ? "Sending…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}
