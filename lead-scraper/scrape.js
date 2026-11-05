#!/usr/bin/env node
// Lead scraper Hirostampe: Google Maps → sito web → Instagram → CSV.
// Esempi:
//   node scrape.js --cerca "box crossfit" --citta "Milano,Venezia" --max 40
//   node scrape.js --instagram lista.txt          (solo profili Instagram)
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');
const { scrapeMaps } = require('./src/maps');
const { scrapeWebsite } = require('./src/website');
const { scrapeInstagram } = require('./src/instagram');
const { writeCsv } = require('./src/csv');
const { log } = require('./src/util');

const COLUMNS = [
  'nome', 'categoria', 'indirizzo', 'telefono', 'cellulare', 'whatsapp_link', 'email', 'sito', 'sito_ok',
  'instagram', 'instagram_url', 'ig_follower', 'ig_seguiti', 'ig_post', 'ig_stato',
  'facebook', 'tiktok', 'rating', 'recensioni', 'ricerca', 'maps_url', 'lat', 'lng',
];

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

// Numero italiano → cellulare? + link WhatsApp pronto da cliccare.
function phoneInfo(tel) {
  let d = String(tel || '').replace(/[^\d+]/g, '');
  if (!d) return { cellulare: '', whatsapp_link: '' };
  if (d.startsWith('00')) d = '+' + d.slice(2);
  if (!d.startsWith('+')) d = '+39' + d;
  const mobile = /^\+393\d{8,9}$/.test(d);
  return { cellulare: mobile ? 'si' : 'no', whatsapp_link: mobile ? `https://wa.me/${d.slice(1)}` : '' };
}

function slug(s) {
  return s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

async function main() {
  const a = parseArgs(process.argv.slice(2));
  if (a.help || (!a.cerca.length && !a.igFile)) {
    console.log(fs.readFileSync(path.join(__dirname, 'README.md'), 'utf8').split('## Come si usa')[1] || 'Vedi README.md');
    process.exit(a.help ? 0 : 1);
  }
  const outDir = path.join(__dirname, 'output');
  fs.mkdirSync(outDir, { recursive: true });
  const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');

  let rows = [];
  if (a.igFile) {
    // Modalità solo Instagram: un handle o link per riga.
    const handles = fs.readFileSync(a.igFile, 'utf8').split(/\r?\n/)
      .map((l) => l.trim().replace(/^@/, '').replace(/^https?:\/\/(www\.)?instagram\.com\//i, '').replace(/[/?].*$/, ''))
      .filter(Boolean);
    rows = handles.map((h) => ({ instagram: h.toLowerCase() }));
  } else {
    const queries = a.citta.length ? a.cerca.flatMap((q) => a.citta.map((c) => `${q} ${c}`)) : a.cerca;
    const browser = await chromium.launch({ headless: !a.visibile });
    const context = await browser.newContext({ locale: 'it-IT', viewport: { width: 1280, height: 900 } });
    // Non scaricare immagini e font: molto più veloce.
    await context.route('**/*', (route) =>
      ['image', 'font', 'media'].includes(route.request().resourceType()) ? route.abort() : route.continue()
    );
    const seen = new Set();
    for (const q of queries) {
      for (const p of await scrapeMaps(context, q, a.max)) {
        const key = p.maps_url || `${p.nome}|${p.indirizzo}`;
        if (seen.has(key)) continue;
        seen.add(key);
        rows.push({ ...p, ...phoneInfo(p.telefono) });
      }
    }
    await browser.close();

    if (a.sito) {
      log(`\nSiti web: analizzo ${rows.filter((r) => r.sito).length} siti…`);
      for (const [i, r] of rows.entries()) {
        if (!r.sito) continue;
        Object.assign(r, await scrapeWebsite(r.sito));
        log(`  [${i + 1}/${rows.length}] ${r.nome}: ${[r.email, r.instagram && '@' + r.instagram].filter(Boolean).join(' · ') || '—'}`);
      }
    }
  }

  if (a.instagram) {
    const todo = rows.filter((r) => r.instagram);
    log(`\nInstagram: leggo ${todo.length} profili…`);
    let blocked = 0;
    for (const [i, r] of todo.entries()) {
      if (blocked >= 3) { r.ig_stato = 'saltato (Instagram chiede login)'; continue; }
      let res = await scrapeInstagram(r.instagram);
      if (res.ig_stato === 'richiede login') {
        await new Promise((ok) => setTimeout(ok, 30000)); // pausa e un solo nuovo tentativo
        res = await scrapeInstagram(r.instagram);
      }
      blocked = res.ig_stato === 'richiede login' ? blocked + 1 : 0;
      Object.assign(r, res);
      log(`  [${i + 1}/${todo.length}] @${r.instagram}: ${r.ig_stato === 'ok' ? r.ig_follower + ' follower' : r.ig_stato}`);
    }
    if (blocked >= 3) log('  Instagram ha iniziato a chiedere il login: profili rimanenti saltati (handle e link restano nel CSV).');
  }
  for (const r of rows) if (r.instagram) r.instagram_url = `https://www.instagram.com/${r.instagram}/`;

  const name = a.out || path.join(outDir, `${slug(a.igFile ? 'instagram' : a.cerca.concat(a.citta).join(' '))}-${stamp}.csv`);
  writeCsv(name, rows, COLUMNS);
  const n = (f) => rows.filter(f).length;
  log(`\nFatto: ${rows.length} lead → ${name}`);
  log(`  con telefono: ${n((r) => r.telefono)} (cellulari WhatsApp: ${n((r) => r.cellulare === 'si')})`);
  log(`  con email: ${n((r) => r.email)} · con Instagram: ${n((r) => r.instagram)}`);
}

main().catch((e) => {
  console.error('Errore:', e.message);
  process.exit(1);
});
