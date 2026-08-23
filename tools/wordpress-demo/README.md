# WordPress publish demo

A one-shot publisher that pushes a single finished article to a WordPress site
through the **AIOS Publisher plugin's own endpoint** — no AIOS backend, no database,
no queue. It exists to prove the plugin's publish path end to end against a real
site, independently of the platform.

| File | Role |
|---|---|
| `push-to-wordpress.ps1` | the publisher |
| `best-ai-agents-for-seo-agencies-2026.html` | the article body it posts |
| `best-ai-agents-featured.png` | that article's featured image |

**These three are one artefact.** The script reads the HTML by
`Join-Path $PSScriptRoot`, so they must stay side by side. They previously sat loose
at the repository root, where a reference check that filtered by file extension
reported the HTML as unreferenced — it came within one command of being deleted as
litter while the script that reads it sat two lines away.

## Running it

```powershell
pwsh ./push-to-wordpress.ps1
```

Edit `$Endpoint` and `$ApiKey` first. It posts as a **draft** by default; set
`$Status = "publish"` to go live immediately.

## Before you run it

Build the plugin from source — `wordpress-plugin/aios-publisher/` — rather than from
any committed zip. The zip that used to live at the repo root was plugin v1.4.0
missing the entire `includes/` directory, while source was v1.7.0; installing it put
a broken plugin on a client's site. It has been deleted for that reason.

## Scope

Demo and diagnostic tooling. Not part of the product, not deployed, not on any
schedule. The platform's real publish path is the content module
(`backend/app/modules/` and `workers/tasks/content.py`), which handles credentials,
capability discovery, the four-transport cascade and the human review gate — none of
which this script has or needs.
