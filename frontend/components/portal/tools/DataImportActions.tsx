"use client";

import { useState } from "react";
import {
  IMPORT_SOURCE_LABELS,
  useCommitImport,
  useUploadImport,
  type ImportSourceType,
} from "@/lib/hooks/tools";
import { ActionCard, ClientSelect, PermNote, ToolActionResult } from "./shared";
import type { ToolActionProps } from "./registry";

const SOURCE_TYPES = Object.keys(IMPORT_SOURCE_LABELS) as ImportSourceType[];

/** Data Import — upload a CSV/TSV/XLSX export (multipart), then commit the mapped
 *  run into its target table. Upload sniffs the columns and suggests a mapping;
 *  committing streams the file in behind the same allow-list the validator enforces. */
export default function DataImportActions({ accent }: ToolActionProps) {
  const [clientId, setClientId] = useState("");
  const [sourceType, setSourceType] = useState<ImportSourceType>("keywords");
  const [file, setFile] = useState<File | null>(null);
  const upload = useUploadImport();
  const commit = useCommitImport();

  const uploaded = upload.data?.run ?? null;
  const canUpload = !!file && !upload.isPending;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canUpload || !file) return;
    upload.mutate({ file, source_type: sourceType, client_id: clientId || undefined });
  };

  return (
    <ActionCard
      title="Import a file"
      subtitle="Upload a CSV / TSV / XLSX export, then commit it into the platform."
      icon="upload_file"
      accent={accent}
    >
      <form onSubmit={submit}>
        <div className="fld-row">
          <div className="fld">
            <label>Source type</label>
            <select value={sourceType} onChange={(e) => setSourceType(e.target.value as ImportSourceType)}>
              {SOURCE_TYPES.map((s) => (
                <option key={s} value={s}>
                  {IMPORT_SOURCE_LABELS[s]}
                </option>
              ))}
            </select>
          </div>
          <ClientSelect value={clientId} onChange={setClientId} label="Client (optional)" allowNone />
        </div>
        <div className="fld">
          <label>File (.csv, .tsv, .xlsx)</label>
          <input
            type="file"
            accept=".csv,.tsv,.xlsx"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>
        <button type="submit" className="primary-btn wide" disabled={!canUpload}>
          <span className="material-symbols-rounded">upload_file</span>
          {upload.isPending ? "Uploading…" : "Upload & map"}
        </button>
      </form>

      {uploaded && (
        <div className="fld" style={{ marginTop: 14 }}>
          <label>Commit {uploaded.filename}</label>
          <button
            type="button"
            className="primary-btn"
            onClick={() => commit.mutate(uploaded.id)}
            disabled={commit.isPending}
          >
            <span className="material-symbols-rounded">database</span>
            {commit.isPending ? "Importing…" : "Run import"}
          </button>
        </div>
      )}

      <ToolActionResult
        error={upload.error ?? commit.error}
        success={
          commit.isSuccess
            ? commit.data.queued
              ? "Import queued — rows are being written into the platform now."
              : `Import not re-queued: ${commit.data.reason ?? "already running"}.`
            : upload.isSuccess && uploaded
              ? `Uploaded "${uploaded.filename}" and mapped its columns. Run the import to write the rows in.`
              : null
        }
      />
      <PermNote>Importing client data needs owner / admin / manager access.</PermNote>
    </ActionCard>
  );
}
