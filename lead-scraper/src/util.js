const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const rand = (a, b) => Math.floor(a + Math.random() * (b - a));
const log = (...a) => console.error(...a);
const UA =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36';

async function fetchText(url, timeoutMs = 15000, ua = UA) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      headers: { 'User-Agent': ua, 'Accept-Language': 'it-IT,it;q=0.9,en;q=0.8' },
      redirect: 'follow',
      signal: ctrl.signal,
    });
    const type = res.headers.get('content-type') || '';
    if (!res.ok || !/html|text/.test(type)) return { ok: false, status: res.status, url: res.url, html: '' };
    return { ok: true, status: res.status, url: res.url, html: await res.text() };
  } catch (e) {
    return { ok: false, status: 0, url, html: '', error: e.message };
  } finally {
    clearTimeout(t);
  }
}

// Identificativo onesto per le pagine pubbliche di Instagram.
const BOT_UA = 'Mozilla/5.0 (compatible; HirostampeLeadScraper/1.0)';

module.exports = { sleep, rand, log, fetchText, UA, BOT_UA };
