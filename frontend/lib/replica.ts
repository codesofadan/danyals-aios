// ============================================================
// AIOS · Design Replicator types
// Backs the Design Replicator card on the admin WordPress screen off
// POST /replica + GET /replica/{job_id} (staff-only, publish_content).
// The wire shapes mirror the backend contract EXACTLY — snake_case, no aliases.
// ============================================================

/** Every state a replica job can report. queued/running are worker-active; the
 * rest are terminal (the poll stops on them). */
export type ReplicaStatus =
  | "queued"
  | "running"
  | "completed"
  | "degraded"
  | "blocked"
  | "failed"
  | "cancelled";

/** POST /replica body. `owner_confirmed_source` is REQUIRED true: the rebuild
 * carries the source site's own copy and imagery, so the caller must assert the
 * client owns it (the server 400s on false — the UI never sends false). */
export type ReplicaCreateInput = {
  client_id: string;
  url: string;
  owner_confirmed_source: boolean;
  title?: string;
  slug?: string;
};

/** POST /replica → 202. */
export type ReplicaCreateResponse = {
  job_id: string;
  status: "queued";
};

/** GET /replica/{job_id} → the job's live state. preview_url/post_id/sections/
 * widgets stay null until the pipeline produces them; `notes` carries the honest
 * account of anything skipped, degraded, or refused. */
export type ReplicaJob = {
  job_id: string;
  status: ReplicaStatus;
  preview_url: string | null;
  post_id: number | null;
  sections: number | null;
  widgets: number | null;
  notes: string[];
};

/** Worker-owned in-flight states — the poll stays alive only while the job sits
 * in one of these. */
export function isReplicaActive(status: ReplicaStatus): boolean {
  return status === "queued" || status === "running";
}
