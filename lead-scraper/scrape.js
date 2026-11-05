#!/usr/bin/env node
// Lead scraper Hirostampe: Google Maps → sito web → Instagram → CSV.
// Esempi:
//   node scrape.js --cerca "box crossfit" --citta "Milano,Venezia" --max 40
//   node scrape.js --instagram lista.txt          (solo profili Instagram)
const fs = require('fs');
const path = require('path');
const { runPipeline, summary, COLUMNS } = require('./src/pipeline');
const { writeCsv } = require('./src/csv');
const { log } = require('./src/util');

function parseArgs(argv) {
  const a = { cerca: [], citta: [], max: 30, sito: true, instagram: true, out: '', visibile: false, igFile: '' };
  const list = (v) => v.split(',').map((s) => s.trim()).filter(Boolean);
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    const v = argv[i + 1];
    if (k === '--cerca' || k === '-q') { a.cerca.push(...list(v)); i++; }
    else if (k === '--citta' || k === '-c') { a.citta.push(...list(v)); i++; }
    else if (k === '--max' || k === '-n') { a.max = parseInt(v, 10) || a.max; i++; }
    else if (k === '--out' || k === '-o') { a.out = v; i++; }
    else if (k === '--instagram') { a.igFile = v; i++; }
    else if (k === '--no-sito') a.sito = false;
    else if (k === '--no-instagram') a.instagram = false;
    else if (k === '--visibile') a.visibile = true;
    else if (k === '--help' || k === '-h') a.help = true;
  }
  return a;
}

function slug(s) {
  return s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

async function main() {
  const a = parseArgs(process.argv.slice(2));
  if (a.help || (!a.cerca.length && !a.igFile)) {
    console.log(fs.readFileSync(path.join(__dirname, 'README.md'), 'utf8').split('## Come si usa')[1]?.split('\n## ')[0] || 'Vedi README.md');
    process.exit(a.help ? 0 : 1);
  }
  const handles = a.igFile ? fs.readFileSync(a.igFile, 'utf8').split(/\r?\n/) : [];
  const rows = await runPipeline({ ...a, handles });

  const outDir = path.join(__dirname, 'output');
  fs.mkdirSync(outDir, { recursive: true });
  const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');
  const name = a.out || path.join(outDir, `${slug(a.igFile ? 'instagram' : a.cerca.concat(a.citta).join(' '))}-${stamp}.csv`);
  writeCsv(name, rows, COLUMNS);
  const s = summary(rows);
  log(`\nFatto: ${s.lead} lead → ${name}`);
  log(`  con telefono: ${s.telefono} (cellulari WhatsApp: ${s.cellulari})`);
  log(`  con email: ${s.email} · con Instagram: ${s.instagram}`);
}

main().catch((e) => {
  console.error('Errore:', e.message);
  process.exit(1);
});
