import TopBar from "@/components/TopBar";
import "../tasks.css";
import TaskDetail from "@/components/tasks/TaskDetail";

export default async function TaskPage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  return (
    <>
      <TopBar eyebrow="Team · Tasks" title={code} hideSearch />
      <div className="main-pad" style={{ padding: "0 26px 26px" }}>
        <TaskDetail code={code} />
      </div>
    </>
  );
}
