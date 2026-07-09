import type { Metadata } from "next";
import TopBar from "@/components/TopBar";
import FeatureBubbles from "@/components/FeatureBubbles";

export const metadata: Metadata = {
  title: "Features · AIOS",
  description: "Every capability across the five AIOS modules — Audit, Content, Off-page, Portal and Policy Radar.",
};

export default function FeaturesIndex() {
  return (
    <>
      <TopBar eyebrow="AIOS · Platform" title="Features" searchPlaceholder="Search features…" />
      <p className="feat-lede">
        Everything AIOS does, grouped by module. Hover a bubble for its full name — click any bubble to open its page.
      </p>
      <div className="feat-page">
        <FeatureBubbles />
      </div>
    </>
  );
}
