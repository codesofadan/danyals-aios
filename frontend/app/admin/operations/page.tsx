import TopBar from "@/components/TopBar";
import "./operations.css";
import OperationsWorkspace from "@/components/operations/OperationsWorkspace";

export default function Operations() {
  return (
    <>
      <TopBar
        eyebrow="Platform · Operations"
        title="Operations"
        searchPlaceholder="Search jobs, clients, queues…"
        hideSearch
      />

      <OperationsWorkspace />
    </>
  );
}
