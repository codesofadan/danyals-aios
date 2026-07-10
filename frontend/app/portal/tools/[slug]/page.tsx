"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import TopBar from "@/components/TopBar";
import ToolWorkspace from "@/components/portal/ToolWorkspace";
import { usePortal } from "@/components/portal/PortalContext";
import { getToolBySlug } from "@/lib/tools";
import { memberGrants } from "@/lib/data";

export default function ToolPage() {
  const { slug } = useParams<{ slug: string }>();
  const { me } = usePortal();
  const tool = getToolBySlug(String(slug));

  // Unknown tool.
  if (!tool) {
    return (
      <>
        <TopBar eyebrow="Team Portal · Tools" title="Tool not found" />
        <div className="tw portal">
          <section className="card">
            <div className="pt-empty">
              <span className="material-symbols-rounded">help</span>
              <div className="pt-empty-t">No such tool</div>
              <div className="pt-empty-s">That tool doesn&apos;t exist. Head back to your access overview.</div>
              <Link href="/portal/access" className="primary-btn" style={{ marginTop: 14 }}>
                <span className="material-symbols-rounded">arrow_back</span>My Access
              </Link>
            </div>
          </section>
        </div>
      </>
    );
  }

  const granted = (memberGrants[me.id] ?? []).includes(tool.key);

  // Granted — the actual tool. Otherwise, a clear no-access screen.
  return (
    <>
      <TopBar eyebrow={`Team Portal · ${tool.group}`} title={tool.label} searchPlaceholder={`Search ${tool.label.toLowerCase()}…`} />
      {granted ? (
        <ToolWorkspace tool={tool} />
      ) : (
        <div className="tw portal">
          <section className="card">
            <div className="pt-empty locked">
              <span className="material-symbols-rounded">lock</span>
              <div className="pt-empty-t">You don&apos;t have access to {tool.label}</div>
              <div className="pt-empty-s">
                This tool is locked for your account. An admin can unlock it from
                {" "}<b>Team Management → Access</b>. Ask your lead if you need it.
              </div>
              <Link href="/portal/access" className="primary-btn" style={{ marginTop: 14 }}>
                <span className="material-symbols-rounded">shield_person</span>See my access
              </Link>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
