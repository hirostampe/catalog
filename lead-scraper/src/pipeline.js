// Motore unico: Maps → siti → Instagram. Usato da scrape.js (Terminale) e worker.js (telefono/Sheet).
const { chromium } = require('playwright');
const { scrapeMaps } = require('./maps');
const { scrapeWebsite } = require('./website');
const { scrapeInstagram } = require('./instagram');
const { log, sleep } = require('./util');

const COLUMNS = [
  'nome', 'categoria', 'indirizzo', 'telefono', 'cellulare', 'whatsapp_link', 'email', 'sito', 'sito_ok',
  'instagram', 'instagram_url', 'ig_follower', 'ig_seguiti', 'ig_post', 'ig_stato',
  'facebook', 'tiktok', 'rating', 'recensioni', 'ricerca', 'maps_url', 'lat', 'lng',
];

// Numero italiano → cellulare? + link WhatsApp pronto da cliccare.
function phoneInfo(tel) {
  let d = String(tel || '').replace(/[^\d+]/g, '');
  if (!d) return { cellulare: '', whatsapp_link: '' };
  if (d.startsWith('00')) d = '+' + d.slice(2);
  if (!d.startsWith('+')) d = '+39' + d;
  const mobile = /^\+393\d{8,9}$/.test(d);
  return { cellulare: mobile ? 'si' : 'no', whatsapp_link: mobile ? `https://wa.me/${d.slice(1)}` : '' };
}

function cleanHandle(l) {
  return String(l).trim().replace(/^@/, '').replace(/^https?:\/\/(www\.)?instagram\.com\//i, '').replace(/[/?].*$/, '').toLowerCase();
}

/**
 * opts: { cerca: [], citta: [], max, sito, instagram, visibile, handles: [] }
 * Se "handles" è pieno → modalità solo Instagram.
 */
async function runPipeline(opts) {
  const o = { cerca: [], citta: [], max: 30, sito: true, instagram: true, visibile: false, handles: [], ...opts };
  let rows = [];
  if (o.handles.length) {
    rows = [...new Set(o.handles.map(cleanHandle).filter(Boolean))].map((h) => ({ instagram: h }));
  } else {
    const queries = o.citta.length ? o.cerca.flatMap((q) => o.citta.map((c) => `${q} ${c}`)) : o.cerca;
    const browser = await chromium.launch({ headless: !o.visibile });
    try {
      const context = await browser.newContext({ locale: 'it-IT', viewport: { width: 1280, height: 900 } });
      // Non scaricare immagini e font: molto più veloce.
      await context.route('**/*', (route) =>
        ['image', 'font', 'media'].includes(route.request().resourceType()) ? route.abort() : route.continue()
      );
      const seen = new Set();
      for (const q of queries) {
        for (const p of await scrapeMaps(context, q, o.max)) {
          const key = p.maps_url || `${p.nome}|${p.indirizzo}`;
          if (seen.has(key)) continue;
          seen.add(key);
          rows.push({ ...p, ...phoneInfo(p.telefono) });
        }
      }
    } finally {
      await browser.close();
    }

    if (o.sito) {
      log(`\nSiti web: analizzo ${rows.filter((r) => r.sito).length} siti…`);
      for (const [i, r] of rows.entries()) {
        if (!r.sito) continue;
        Object.assign(r, await scrapeWebsite(r.sito));
        log(`  [${i + 1}/${rows.length}] ${r.nome}: ${[r.email, r.instagram && '@' + r.instagram].filter(Boolean).join(' · ') || '—'}`);
      }
    }
  }

  if (o.instagram) {
    const todo = rows.filter((r) => r.instagram);
    log(`\nInstagram: leggo ${todo.length} profili…`);
    let blocked = 0;
    for (const [i, r] of todo.entries()) {
      if (blocked >= 3) { r.ig_stato = 'saltato (Instagram chiede login)'; continue; }
      let res = await scrapeInstagram(r.instagram);
      if (res.ig_stato === 'richiede login') {
        await sleep(30000); // pausa e un solo nuovo tentativo
        res = await scrapeInstagram(r.instagram);
      }
      blocked = res.ig_stato === 'richiede login' ? blocked + 1 : 0;
      Object.assign(r, res);
      log(`  [${i + 1}/${todo.length}] @${r.instagram}: ${r.ig_stato === 'ok' ? r.ig_follower + ' follower' : r.ig_stato}`);
    }
    if (blocked >= 3) log('  Instagram ha iniziato a chiedere il login: profili rimanenti saltati (handle e link restano).');
  }
  for (const r of rows) {
    if (r.instagram) r.instagram_url = `https://www.instagram.com/${r.instagram}/`;
    if (!r.nome && r.ig_nome) r.nome = r.ig_nome;
  }
  return rows;
}

function summary(rows) {
  const n = (f) => rows.filter(f).length;
  return {
    lead: rows.length,
    telefono: n((r) => r.telefono),
    cellulari: n((r) => r.cellulare === 'si'),
    email: n((r) => r.email),
    instagram: n((r) => r.instagram),
  };
}

module.exports = { runPipeline, summary, phoneInfo, COLUMNS };
