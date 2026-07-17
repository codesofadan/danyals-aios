---
name: data-import
description: Maps an uploaded CSV/TSV/XLSX file's columns onto a client's real data fields and commits the rows, reporting rejected rows honestly. Use when an operator wants to import or upload keywords, rankings, backlinks, citations, or Search Console data, asks which columns a file type accepts, wants to fix or save a column mapping, or asks why rows were rejected from an import. Keyless (no provider spend). Committing WRITES rows to the client's data; a partial import means rows were rejected, never rounded up to success.
argument-hint: "[client] [source-type]"
arguments: [client, source_type]
model: sonnet
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py:*), Read
---

# Map and Commit a Data Import

**Purpose.** Take an uploaded file's detected columns, map them onto the **published allow-list**
of real target fields for its `$source_type`, commit the rows, and report exactly what landed and
what was rejected.

**Who runs it.** Reading needs `view_reports`. Uploading, setting a mapping, committing, and
saving a mapping template need **`manage_clients`** (owner/admin/manager). Every route needs the
`data_import` feature grant. Lacking either → 403 → report which one and STOP.

## Required inputs / keys
- `$client` — the client name, resolved to a real `client_id`. Never invent an id. A `rankings`
  import **requires** a client; the other types may be agency-global.
- `$source_type` — one of `search_console`, `keywords`, `rankings`, `backlinks`, `citations`,
  `custom`.
- `AIOS_BASE_URL` (default `http://localhost:8000/api/v1`) and `AIOS_SKILL_TOKEN`.
- **Keyless — no provider key, no spend, no cost dial.** It does need one server-side config
  value, `import_artifact_dir`; unset → `POST /data-import/uploads` returns **503 "File imports
  are not configured (no import root)"**. That is a filesystem root, not a provider key.
- **The upload itself is `multipart/form-data`** (`file` + `sourceType` + optional `clientId`).
  The shared client sends **JSON only**, so it **cannot perform the upload**. The operator uploads
  through the dashboard; this skill picks the run up from `GET /data-import/runs` and drives the
  mapping and the commit. Say so rather than pretending the upload happened.

**Trigger.** Importing / uploading keywords, rankings, backlinks, citations, or Search Console
data; "which columns does this file type accept"; fixing or saving a column mapping; "why were
rows rejected".

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Resolve the client (resolve-client), if the import is client-scoped
- [ ] Step 2: Read the published allow-list for the source type (NEVER invent a target column)
- [ ] Step 3: Find the uploaded run + its detected columns
- [ ] Step 4: Set the column map (only allow-list fields); fix any 400 by re-reading the list
- [ ] Step 5: Commit; then read the run detail and report the rejects honestly
```

1. **Resolve the client.** Run `python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py
   resolve-client --client "$client"` → `GET /clients` (name match). Capture `client_id`.

2. **Read the allow-list.** Run `aios_client.py get "/data-import/fields?sourceType=$source_type"`
   → `GET /data-import/fields`. It returns `{sourceType, fields, required}` — **`fields` is the
   complete set of legal targets, and nothing outside it may ever appear in a `column_map`.**
   Reusable templates: `aios_client.py get "/data-import/mappings?sourceType=$source_type"` →
   `GET /data-import/mappings`.

3. **Find the run.** Run `aios_client.py get "/data-import/runs?clientId=<id>&status=uploaded"` →
   `GET /data-import/runs`, then `aios_client.py get /data-import/runs/<run_id>` →
   `GET /data-import/runs/{run_id}` for `detectedColumns` and `errorSample`. (The upload route is
   `POST /data-import/uploads`; it is multipart and out of this client's reach — see above.)

4. **Set the column map.** Run `aios_client.py post /data-import/runs/<run_id>/mapping --json
   '{"columnMap":{"<file column>":"<allow-list field>"}}'` → `POST /data-import/runs/{run_id}/mapping`.
   Every value MUST come from Step 2's `fields`. Save a reusable template on request:
   `aios_client.py post /data-import/mappings --json '{"name":"…","sourceType":"$source_type","columnMap":{…}}'`
   → `POST /data-import/mappings`.

5. **Commit and report.** Run `aios_client.py post /data-import/runs/<run_id>/commit` →
   `POST /data-import/runs/{run_id}/commit` (202). Then re-read `GET /data-import/runs/{run_id}`
   for the final `status`, `rows`, `mapped`, `errors`, and `errorSample`. Agency totals:
   `aios_client.py get /data-import/stats` → `GET /data-import/stats`. Render the **Output format**.

## Decision points
- If the client exits **2** with `status: 400` and `'X' is not an importable field for <type>` →
  **STOP and re-read `GET /data-import/fields`.** A target column that is not on the allow-list
  does not exist. **Never invent a target column**, never map to a server-derived column
  (`client_id`, `client_name`, `import_run_id`, `source`), and never guess a near-miss name.
  The error message lists the legal set — use it.
- If the final `status` is **`partial`** → **some rows were REJECTED and some landed.** Report
  `mapped` landed, `errors` rejected, and the `errorSample` rows verbatim (it is capped at **50
  entries at rest**, so say "showing N of `errors`" when `errors` exceeds the sample). **Never
  round a partial up to a success** and never report `rows` as if it were `mapped`.
- If the final `status` is **`failed`** → nothing landed. Two distinct causes: "the file has no
  data rows", or **every row was rejected** (which is `failed`, **not** `partial`). A fatal error
  is appended INTO `errorSample` as a synthetic `{row: 0, …}` entry — there is no top-level
  failure field. Report the reason from there.
- If `$source_type` is **`custom`** → its allow-list is **EMPTY by construction**, so every
  non-empty `column_map` is a 400 and a commit always fails. `custom` stages a file; it has no
  target fields. Say that instead of trying to map it.
- If a required field is unmapped → **400** `'X' is required for a <type> import`. `keywords` and
  `rankings` require `keyword`; `backlinks` requires `ref_domain`; `citations` requires
  `directory`; `search_console` requires nothing (a row needs a `query` or a `page` to be importable).
- If the commit returns `queued: false, reason: "the import is already running"` → an honest
  **no-op, not an error**. The run is mid-flight; re-read it rather than re-committing.
- If a mapping/commit returns **409 "This import is already <status>"** → the run is terminal
  (`imported` / `partial` / `failed`). It cannot be re-mapped. A new file needs a new upload.
- If a `rankings` import has no client → **400 "A rankings import requires a client"**. Resolve one.

## Common Pitfalls
- "The file has a `search_volume` column, so I'll map it to `search_volume`." → Only the
  allow-list's names exist (`volume` for `keywords`). Map the file's column ONTO an allow-list
  field; never invent the target.
- "`status: partial` — the import worked." → Partial means rows were **rejected**. Report the
  count and the sample. Rounding it up hides real data loss from the operator.
- Reporting `rows` as the number imported → `rows` is the file's row count. **`mapped`** landed
  and **`errors`** were rejected. There is no `rows_ok` / `rows_rejected` field.
- "Every row was rejected, so it's partial." → That is **`failed`**, not partial. Partial requires
  at least one row to land.
- Re-committing after `reason: "the import is already running"` → it is a no-op by design. Re-read.
- Mapping to `client_id` / `client_name` / `source` → server-derived, never mappable.
- Quoting `errorSample` as the complete reject list → it is **capped at 50**. `errors` is the true
  total; state both.
- Reporting `created` as a timestamp → it is a **humanised display string** (`"Today · 09:14"`),
  not ISO. Do not parse it.
- Claiming the skill uploaded the file → the upload is multipart and this client is JSON-only. The
  operator uploads; the skill maps and commits.

## Output format
Emit verbatim (values copied from the endpoints; never from memory):

```
DATA IMPORT — <client|agency-global> · <sourceType> (<sourceLabel>)
Run: <id>   File: <file>   Uploaded: <created>   Status: <uploaded|mapping|validating|importing|imported|partial|failed>

Allow-list for <sourceType> (from GET /data-import/fields — the ONLY legal targets):
  fields:   <fields>
  required: <required or "(none)">

Detected columns: <detectedColumns>
Column map applied:
  "<file column>" -> <target field>
  ...
  <or "none set yet">

RESULT: <status>
  Rows in file: <rows>     Landed (mapped): <mapped>     REJECTED (errors): <errors>
  <partial  -> "PARTIAL: <errors> row(s) were REJECTED. This is not a clean import.">
  <failed   -> "FAILED: nothing landed. Reason: <the synthetic errorSample row 0 reason>">
  <imported -> "All <mapped> row(s) landed.">

Rejected rows (errorSample — capped at 50 at rest; showing <len(errorSample)> of <errors>):
  row <row>  field=<field>  value="<value>"  reason: <reason>
  ...
  <or "none">

Agency totals: imports30d=<imports30d>  rowsMapped=<rowsMapped>  rowsError=<rowsError>
Upload note: the file upload is multipart/form-data and is performed by the operator in the
  dashboard; this skill drove the mapping and the commit only.
```

Exact response fields, the per-source_type allow-list, and the partial/failed rules:
`reference/part8-output-formats.md` §7.
