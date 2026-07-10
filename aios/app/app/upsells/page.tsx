import TopBar from "@/components/TopBar";
import "./upsells.css";
import UpsellsWorkspace from "@/components/upsells/UpsellsWorkspace";

export default function UpsellsModule() {
  return (
    <>
      <TopBar
        eyebrow="Revenue · Upsell Manager"
        title="Upsells"
        searchPlaceholder="Search gigs, titles…"
      />
      <UpsellsWorkspace />
    </>
  );
}
