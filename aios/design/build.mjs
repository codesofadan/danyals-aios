// Inline the base64 Bricolage font into the template, write final HTML.
import { readFileSync, writeFileSync } from 'node:fs';

const DIR = 'C:/Users/adan/Desktop/danyals-aios/aios/design';
const FONT = 'C:/Users/adan/.claude/assets/bricolage-grotesque.css';

const tpl = readFileSync(`${DIR}/architecture.template.html`, 'utf8');
const font = readFileSync(FONT, 'utf8');
const out = tpl.replace('/*FONTCSS*/', font);
writeFileSync(`${DIR}/architecture.html`, out, 'utf8');
console.log('inlined font, wrote architecture.html', out.length, 'bytes');
