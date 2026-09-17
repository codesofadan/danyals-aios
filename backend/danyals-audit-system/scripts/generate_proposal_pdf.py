"""
Branded one-off PDF generator (proposals, justifications, white-papers).

Takes a single Markdown file and renders it with the SEO-AUDIT-OS visual brand:
navy header band, sky-blue accents, white cards, running footer with page numbers.

Used for: API investment proposals, capability decks, scope-of-work memos.

Usage:
    python scripts/generate_proposal_pdf.py <markdown_path> [options]

Example:
    python scripts/generate_proposal_pdf.py docs/proposals/api-investment-proposal.md \\
      --title "API Investment Proposal" \\
      --subtitle "Reviewed for AM Sofa Studio" \\
      --out Client_API_Investment_Proposal.pdf
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import markdown


PALETTE = {
    "navy_dark": "#0E2A47",
    "navy_mid": "#15355C",
    "blue_accent": "#0EA5E9",
    "blue_link": "#2563EB",
    "page_bg": "#FFFFFF",
    "card_bg": "#FFFFFF",
    "card_border": "#E2E8F0",
    "text_body": "#1F2937",
    "text_muted": "#64748B",
    "text_label": "#475569",
    "delta_green": "#16A34A",
    "delta_green_bg": "#DCFCE7",
}


CSS = f"""
@page {{
  size: A4;
  margin: 20mm 16mm 22mm 16mm;
}}
* {{ box-sizing: border-box; }}
html, body {{
  font-family: 'Inter', 'Segoe UI', -apple-system, Roboto, Arial, sans-serif;
  font-size: 10.5pt;
  line-height: 1.6;
  color: {PALETTE['text_body']};
  margin: 0;
  padding: 0;
  background: {PALETTE['page_bg']};
}}
h1, h2, h3, h4 {{
  color: {PALETTE['navy_dark']};
  margin: 0;
  padding: 0;
  font-weight: 700;
}}
h1 {{
  font-size: 20pt;
  border-bottom: 3px solid {PALETTE['navy_dark']};
  padding-bottom: 6pt;
  margin: 18pt 0 12pt 0;
  page-break-after: avoid;
}}
h2 {{
  font-size: 14pt;
  margin: 16pt 0 8pt 0;
  border-left: 5px solid {PALETTE['blue_accent']};
  padding-left: 10pt;
  page-break-after: avoid;
}}
h3 {{
  font-size: 11.5pt;
  margin: 12pt 0 6pt 0;
  page-break-after: avoid;
}}
h4 {{
  font-size: 10.5pt;
  color: {PALETTE['text_label']};
  margin: 8pt 0 4pt 0;
}}
p {{ margin: 6pt 0 8pt 0; }}
ul, ol {{ margin: 6pt 0 10pt 22pt; padding: 0; }}
li {{ margin: 3pt 0; }}
strong {{ color: {PALETTE['navy_dark']}; font-weight: 700; }}
a {{ color: {PALETTE['blue_link']}; text-decoration: none; }}
hr {{
  border: none;
  border-top: 1px solid {PALETTE['card_border']};
  margin: 18pt 0;
}}
code {{
  font-family: "JetBrains Mono", Consolas, Menlo, monospace;
  font-size: 9pt;
  background: #EEF2F7;
  padding: 1pt 5pt;
  border-radius: 3pt;
  color: {PALETTE['navy_dark']};
}}
pre {{
  background: {PALETTE['navy_dark']};
  color: #E2E8F0;
  padding: 12pt;
  border-radius: 6pt;
  font-size: 9pt;
  overflow-x: auto;
  page-break-inside: avoid;
}}
table {{
  border-collapse: separate;
  border-spacing: 0;
  width: 100%;
  margin: 10pt 0 14pt 0;
  font-size: 9.5pt;
  page-break-inside: avoid;
  background: {PALETTE['card_bg']};
  border: 1px solid {PALETTE['card_border']};
  border-radius: 8pt;
  overflow: hidden;
}}
th {{
  background: {PALETTE['navy_dark']};
  color: #FFFFFF;
  text-align: left;
  padding: 8pt 12pt;
  font-weight: 600;
  font-size: 9.5pt;
}}
td {{
  border-bottom: 1px solid {PALETTE['card_border']};
  padding: 7pt 12pt;
  vertical-align: top;
  background: {PALETTE['card_bg']};
}}
tr:last-child td {{ border-bottom: none; }}
tr:nth-child(even) td {{ background: #F8FAFC; }}
blockquote {{
  border-left: 4px solid {PALETTE['blue_accent']};
  margin: 10pt 0;
  padding: 8pt 16pt;
  color: {PALETTE['text_label']};
  background: #F8FAFC;
  border-radius: 0 6pt 6pt 0;
  font-style: italic;
}}

/* COVER */
.cover {{
  page-break-after: always;
}}
.cover-hero {{
  background: linear-gradient(135deg, {PALETTE['navy_dark']} 0%, {PALETTE['navy_mid']} 100%);
  color: #FFFFFF;
  padding: 56pt 40pt 48pt 40pt;
  border-radius: 14pt;
  margin-bottom: 20pt;
}}
.cover-eyebrow {{
  color: {PALETTE['blue_accent']};
  font-size: 9pt;
  letter-spacing: 2pt;
  font-weight: 600;
  text-transform: uppercase;
  margin-bottom: 12pt;
}}
.cover-title {{
  font-size: 32pt;
  font-weight: 800;
  line-height: 1.1;
  margin: 0 0 12pt 0;
  color: #FFFFFF;
}}
.cover-sub {{
  font-size: 12pt;
  color: #CBD5E1;
  margin: 0 0 24pt 0;
}}
.cover-tag {{
  display: inline-block;
  background: rgba(14, 165, 233, 0.18);
  border: 1px solid rgba(14, 165, 233, 0.55);
  color: #FFFFFF;
  padding: 6pt 14pt;
  border-radius: 999pt;
  font-size: 9pt;
  letter-spacing: 1.2pt;
  text-transform: uppercase;
  font-weight: 600;
}}
.cover-meta {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12pt;
  margin-top: 18pt;
}}
.cover-meta-card {{
  background: #FFFFFF;
  border: 1px solid {PALETTE['card_border']};
  border-radius: 8pt;
  padding: 12pt 14pt;
}}
.cover-meta-label {{
  font-size: 7.5pt;
  letter-spacing: 1.4pt;
  text-transform: uppercase;
  color: {PALETTE['text_muted']};
  font-weight: 600;
  margin-bottom: 4pt;
}}
.cover-meta-value {{
  font-size: 12pt;
  font-weight: 700;
  color: {PALETTE['navy_dark']};
}}
"""


HEADER_HTML_TEMPLATE = """
<div style="font-family: 'Inter', 'Segoe UI', Arial, sans-serif; width: 100%; height: 14mm; padding: 0 16mm; box-sizing: border-box; font-size: 9.5pt; color: #FFFFFF; background: __NAVY__; -webkit-print-color-adjust: exact; display: flex; justify-content: center; align-items: center;">
  <div style="font-weight: 700; letter-spacing: 1.2pt; text-transform: uppercase;">__HEADING__</div>
</div>
"""

FOOTER_HTML_TEMPLATE = """
<div style="font-family: 'Inter', 'Segoe UI', Arial, sans-serif; width: 100%; height: 16mm; padding: 0 16mm; box-sizing: border-box; font-size: 8pt; color: #FFFFFF; background: __NAVY__; -webkit-print-color-adjust: exact; display: flex; justify-content: space-between; align-items: center;">
  <div style="font-weight: 700; letter-spacing: 0.5pt;"><span style="color: __ACCENT__;">__BRAND__</span> __BRAND_SUFFIX__</div>
  <div style="opacity: 0.85; font-size: 7.5pt;">__FOOTER_CENTER__</div>
  <div style="opacity: 0.9; font-size: 7.5pt;"><span class="pageNumber"></span> / <span class="totalPages"></span></div>
</div>
"""


def _find_chromium_executable() -> str | None:
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    candidates = []
    if base.exists():
        candidates.extend(base.glob("chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"))
        candidates.extend(base.glob("chromium-*/chrome-win64/chrome.exe"))
        candidates.extend(base.glob("chromium-*/chrome-win/chrome.exe"))
    return str(candidates[0]) if candidates else None


def build_cover(title: str, subtitle: str, prepared_for: str, prepared_by: str,
                date_str: str, eyebrow: str, tag: str) -> str:
    return f"""
<div class="cover">
  <div class="cover-hero">
    <div class="cover-eyebrow">{eyebrow}</div>
    <div class="cover-title">{title}</div>
    <div class="cover-sub">{subtitle}</div>
    <span class="cover-tag">{tag}</span>
  </div>
  <div class="cover-meta">
    <div class="cover-meta-card">
      <div class="cover-meta-label">Prepared For</div>
      <div class="cover-meta-value">{prepared_for}</div>
    </div>
    <div class="cover-meta-card">
      <div class="cover-meta-label">Prepared By</div>
      <div class="cover-meta-value">{prepared_by}</div>
    </div>
    <div class="cover-meta-card">
      <div class="cover-meta-label">Date</div>
      <div class="cover-meta-value">{date_str}</div>
    </div>
    <div class="cover-meta-card">
      <div class="cover-meta-label">Document Type</div>
      <div class="cover-meta-value">{tag.title()}</div>
    </div>
  </div>
</div>
"""


def render(html_path: Path, pdf_path: Path, header_html: str, footer_html: str) -> bool:
    from playwright.sync_api import sync_playwright
    exe = _find_chromium_executable()
    try:
        with sync_playwright() as pw:
            launch_kwargs = {"headless": True}
            if exe:
                launch_kwargs["executable_path"] = exe
                print(f"[info] using chromium at {exe}")
            browser = pw.chromium.launch(**launch_kwargs)
            page = browser.new_page()
            page.goto(html_path.as_uri(), wait_until="load")
            try:
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(800)
            except Exception:
                pass
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "20mm", "right": "16mm", "bottom": "22mm", "left": "16mm"},
                display_header_footer=True,
                header_template=header_html,
                footer_template=footer_html,
            )
            browser.close()
        return True
    except Exception as exc:
        print(f"[err] render failed: {exc}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("markdown_path")
    parser.add_argument("--title", required=True)
    parser.add_argument("--subtitle", default="")
    parser.add_argument("--eyebrow", default="Proposal Document")
    parser.add_argument("--tag", default="Investment Brief")
    parser.add_argument("--prepared-for", default="Client")
    parser.add_argument("--prepared-by", default="SEO-AUDIT-OS")
    parser.add_argument("--date", default="20 May 2026")
    parser.add_argument("--header-left", default="SEO-AUDIT-OS")
    parser.add_argument("--header-sub", default="MULTI-AGENT SEO AUDIT SYSTEM")
    parser.add_argument("--header-right", default="API Investment Proposal")
    parser.add_argument("--brand", default="SEO-AUDIT")
    parser.add_argument("--brand-suffix", default="· OS Audit Engine")
    parser.add_argument("--footer-center", default="API Investment Proposal")
    parser.add_argument("--out", default=None, help="Output PDF path (defaults to repo root)")
    args = parser.parse_args()

    md_path = Path(args.markdown_path)
    if not md_path.exists():
        print(f"markdown not found: {md_path}", file=sys.stderr)
        return 1

    md_text = md_path.read_text(encoding="utf-8")
    body_html = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "sane_lists", "toc", "attr_list"],
    )

    cover_html = build_cover(
        title=args.title,
        subtitle=args.subtitle,
        prepared_for=args.prepared_for,
        prepared_by=args.prepared_by,
        date_str=args.date,
        eyebrow=args.eyebrow,
        tag=args.tag,
    )

    full_html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{args.title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap">
<style>{CSS}</style>
</head>
<body>
{cover_html}
<div class="page-content">
{body_html}
</div>
</body>
</html>
"""

    repo_root = Path(__file__).resolve().parent.parent
    html_path = repo_root / "_proposal_render.html"
    html_path.write_text(full_html, encoding="utf-8")

    if args.out:
        pdf_path = Path(args.out)
        if not pdf_path.is_absolute():
            pdf_path = repo_root / pdf_path
    else:
        pdf_path = repo_root / f"{args.title.replace(' ', '_')}.pdf"

    header_html = (HEADER_HTML_TEMPLATE
        .replace("__NAVY__", PALETTE["navy_dark"])
        .replace("__HEADING__", args.header_right or args.title)
    )
    footer_html = (FOOTER_HTML_TEMPLATE
        .replace("__NAVY__", PALETTE["navy_dark"])
        .replace("__ACCENT__", PALETTE["blue_accent"])
        .replace("__BRAND__", args.brand)
        .replace("__BRAND_SUFFIX__", args.brand_suffix)
        .replace("__FOOTER_CENTER__", args.footer_center)
    )

    if render(html_path, pdf_path, header_html, footer_html):
        print(f"[ok] wrote {pdf_path}")
        try:
            html_path.unlink()
        except OSError:
            pass
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
