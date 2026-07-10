import TopBar from "@/components/TopBar";
import "./vault.css";
import VaultWorkspace from "@/components/vault/VaultWorkspace";

export default function KeyVault() {
  return (
    <>
      <TopBar
        eyebrow="Admin · Key Vault"
        title="Key Vault"
        searchPlaceholder="Search keys, providers, scopes…"
      />
      <VaultWorkspace />
    </>
  );
}
