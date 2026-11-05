// Google Maps: cerca "query" e restituisce le schede attività.
const { sleep, rand, log } = require('./util');

// Banner cookie Google (compare in Italia/UE). Prova a rifiutare o accettare.
async function handleConsent(page) {
  if (!/consent\.google\./.test(page.url())) return;
  const labels = [/rifiuta tutto/i, /reject all/i, /accetta tutto/i, /accept all/i];
  for (const re of labels) {
    const btn = page.getByRole('button', { name: re }).first();
    if (await btn.count()) {
      await btn.click();
      await page.waitForURL(/google\.[a-z.]+\/maps/, { timeout: 20000 }).catch(() => {});
      return;
    }
  }
}

// Scorre la colonna dei risultati finché trova "max" schede o arriva in fondo.
async function collectPlaceLinks(page, max) {
  const feed = page.locator('div[role="feed"]');
  const hasFeed = await feed.waitFor({ timeout: 20000 }).then(() => true).catch(() => false);
  if (!hasFeed) {
    // Un solo risultato: Google apre direttamente la scheda.
    if (/\/maps\/place\//.test(page.url())) return [page.url()];
    return [];
  }
  let links = [];
  let stale = 0;
  while (links.length < max && stale < 6) {
    await feed.evaluate((el) => el.scrollBy(0, 4000));
    await sleep(rand(1200, 2000));
    const now = await page.$$eval('div[role="feed"] a[href*="/maps/place/"]', (as) =>
      [...new Set(as.map((a) => a.href))]
    );
    stale = now.length === links.length ? stale + 1 : 0;
    links = now;
    const end = await page.locator("text=/fine dell'elenco|end of the list/i").count();
    if (end) break;
  }
  return links.slice(0, max);
}

async function readPlace(page, url) {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForSelector('h1', { timeout: 20000 });
  await sleep(rand(800, 1500));
  return page.evaluate((url) => {
    const q = (s) => document.querySelector(s);
    const label = (s) => (q(s)?.getAttribute('aria-label') || '').replace(/^[^:]+:\s*/, '').trim();
    const ratingBox = q('div.F7nice');
    const ratingText = ratingBox ? ratingBox.innerText : '';
    const rating = (ratingText.match(/(\d[.,]\d)/) || [])[1] || '';
    const revLabel = [...document.querySelectorAll('[aria-label]')]
      .map((e) => e.getAttribute('aria-label')).find((s) => /^[\d.\s]+ recension/i.test(s)) || '';
    const reviews = ((ratingText.match(/\(([\d.\s]+)\)/) || [])[1] || revLabel).replace(/\D/g, '');
    const phoneEl = q('[data-item-id^="phone:tel:"]');
    const coords = (url.match(/!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)/) || []).slice(1);
    return {
      nome: q('h1')?.innerText.trim() || '',
      categoria: q('button[jsaction*="category"]')?.innerText.trim() || '',
      indirizzo: label('[data-item-id="address"]'),
      telefono: phoneEl ? phoneEl.getAttribute('data-item-id').replace('phone:tel:', '') : '',
      sito: q('a[data-item-id="authority"]')?.href || '',
      rating: rating.replace(',', '.'),
      recensioni: reviews,
      lat: coords[0] || '',
      lng: coords[1] || '',
      maps_url: url.split('?')[0],
    };
  }, url);
}

async function scrapeMaps(context, query, max) {
  const page = await context.newPage();
  const url = `https://www.google.com/maps/search/${encodeURIComponent(query)}?hl=it`;
  log(`Maps → "${query}"`);
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await handleConsent(page);
  const links = await collectPlaceLinks(page, max);
  log(`  ${links.length} schede trovate`);
  const out = [];
  for (const [i, link] of links.entries()) {
    try {
      const p = await readPlace(page, link);
      p.ricerca = query;
      out.push(p);
      log(`  [${i + 1}/${links.length}] ${p.nome}${p.telefono ? ' · ' + p.telefono : ''}`);
    } catch (e) {
      log(`  [${i + 1}/${links.length}] errore: ${e.message.split('\n')[0]}`);
    }
  }
  await page.close();
  return out;
}

module.exports = { scrapeMaps };
