// Team Portal — pure task-flow helpers shared by the queue and
// deliver views. Keeps the member-facing state machine in one place.
import { TASK_ACTION, type Task, type TaskStatus, type TaskType } from "@/lib/data";

// A reviewer's decision at the content review gate.
export type ReviewAction = "approve" | "reject";

// Content drafts pass through the human review gate before they're
// done; every other job type is delivered straight to done.
const REVIEW_TYPES: TaskType[] = ["Content Sprint"];
export const needsReview = (t: Task): boolean => REVIEW_TYPES.includes(t.type);

// The next state a member moves a task into by acting on it.
export function nextStatus(t: Task): TaskStatus | null {
  switch (t.status) {
    case "todo": return "in_progress";
    case "in_progress": return needsReview(t) ? "review" : "done";
    case "review": return "done"; // reviewer sign-off only
    default: return null;
  }
}

// The primary action button a member sees on a task card.
export function cardAction(t: Task): { label: string; icon: string } | null {
  if (t.status === "todo") return { label: "Start", icon: "play_arrow" };
  if (t.status === "in_progress") {
    const a = TASK_ACTION[t.type];
    return { label: a.deliver, icon: a.icon };
  }
  return null; // review = awaiting sign-off, done = delivered
}
