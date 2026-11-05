// Instagram: legge solo la pagina pubblica del profilo (follower, seguiti, post).
const { fetchText, sleep, rand, BOT_UA } = require('./util');

function toNumber(s) {
  if (!s) return '';
  const m = s.replace(/\s/g, '').match(/^([\d.,]+)([KkMm])?$/);
  if (!m) return '';
  let n = m[1];
  if (m[2]) {
    n = parseFloat(n.replace(',', '.')) * (/k/i.test(m[2]) ? 1e3 : 1e6);
  } else {
    n = parseInt(n.replace(/[.,]/g, ''), 10);
  }
  return String(Math.round(n));
}

function decode(s) {
  return s.replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCharCode(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => String.fromCharCode(+d))
    .replace(/&quot;/g, '"').replace(/&amp;/g, '&');
}

function parseProfile(html) {
  const meta = (p) => decode((html.match(new RegExp(`<meta[^>]+property="${p}"[^>]+content="([^"]*)"`, 'i')) || [])[1] || '');
  const desc = meta('og:description');
  const title = meta('og:title');
  const num = (re) => toNumber((desc.match(re) || [])[1]);
  return {
    ig_nome: title.replace(/\s*[(•·].*$/, '').trim(),
    ig_follower: num(/([\d.,]+[KkMm]?)\s*(Followers|follower)/i),
    ig_seguiti: num(/([\d.,]+[KkMm]?)\s*(Following|seguiti|profili seguiti)/i),
    ig_post: num(/([\d.,]+[KkMm]?)\s*(Posts|post)\b/i),
  };
}

async function scrapeInstagram(handle) {
  if (!handle) return {};
  await sleep(rand(2500, 5000)); // ritmo umano: evita blocchi
  const r = await fetchText(`https://www.instagram.com/${handle}/`, 15000, BOT_UA);
  if (!r.ok) return { ig_stato: `non letto (${r.status || 'errore'})` };
  if (/accounts\/login/.test(r.url)) return { ig_stato: 'richiede login' };
  const p = parseProfile(r.html);
  if (!p.ig_follower && !p.ig_post) return { ig_stato: 'profilo non trovato o privato' };
  return { ...p, ig_stato: 'ok' };
}

module.exports = { scrapeInstagram, parseProfile, toNumber };
