import TopBar from "@/components/TopBar";
import "./tasks.css";
import TaskManager from "@/components/tasks/TaskManager";

export default function TasksPage() {
  return (
    <>
      <TopBar
        eyebrow="Delivery · Task Manager"
        title="Task Manager"
        searchPlaceholder="Search tasks, clients, assignees…"
        hideSearch
      />
      <TaskManager />
    </>
  );
}
