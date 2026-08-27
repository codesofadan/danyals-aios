import TopBar from "@/components/TopBar";
import SearchWorkspace from "@/components/search/SearchWorkspace";

export default function SearchPage() {
  return (
    <>
      <TopBar eyebrow="Work" title="Search" hideSearch />
      <div className="main-pad" style={{ padding: "0 26px 26px" }}>
        <SearchWorkspace />
      </div>
    </>
  );
}
