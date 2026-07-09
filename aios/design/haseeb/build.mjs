// Build the Haseeb client-document pack: inject font + base CSS into every
// *.template.html, write the final self-contained HTML next to it.
// Usage: node build.mjs           (builds all)
import { readFileSync, writeFileSync, readdirSync } from 'node:fs';

const DIR  = 'C:/Users/adan/Desktop/danyals-aios/aios/design/haseeb';
const FONT = 'C:/Users/adan/.claude/assets/bricolage-grotesque.css';

const font = readFileSync(FONT, 'utf8');
const logoURI = `data:image/png;base64,${readFileSync(`${DIR}/xegents-logo.png`).toString('base64')}`;
const base = readFileSync(`${DIR}/base.css`, 'utf8').replaceAll('__XEGENTS_LOGO__', logoURI);

const templates = readdirSync(DIR).filter(f => f.endsWith('.template.html'));
for (const t of templates) {
  const tpl = readFileSync(`${DIR}/${t}`, 'utf8');
  const out = tpl.replace('/*FONTCSS*/', font).replace('/*BASECSS*/', base);
  const name = t.replace('.template.html', '.html');
  writeFileSync(`${DIR}/${name}`, out, 'utf8');
  console.log(`built ${name}  (${out.length} bytes)`);
}
console.log(`done — ${templates.length} document(s)`);
