import TopBar from "@/components/TopBar";
import SettingsWorkspace from "@/components/settings/SettingsWorkspace";

export default function Settings() {
  return (
    <>
      <TopBar
        eyebrow="Platform · Administration"
        title="Settings"
        searchPlaceholder="Search settings…"
      />

      <SettingsWorkspace />
    </>
  );
}
