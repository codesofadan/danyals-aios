# Access & Accounts deliverable — source

Regenerates `docs/deliverables/danyal-aios-access-requirements.{pdf,xlsx}` (revision 2).

```
python build_pdf2.py                 # -> access-requirements-v2.html
node C:/Users/adan/.claude/assets/render-pdf.mjs access-requirements-v2.html ../../danyal-aios-access-requirements.pdf
../../../../backend/.venv/Scripts/python.exe build_xlsx2.py   # writes the .xlsx in place
```

`dirs.json`, `web2.json` and `integrations.json` are snapshots of the live registry and
integration status, read on 12 September 2026. Re-pull them before a new revision.

`data2.py` holds every editorial decision for revision 2 (what is needed, what was removed
and why) — change it there, not in the two builders.
