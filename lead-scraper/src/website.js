// Sito web: cerca email, Instagram, Facebook, TikTok, WhatsApp nella home e nella pagina contatti.
const { fetchText } = require('./util');

const BAD_EMAIL = /\.(png|jpe?g|gif|webp|svg|css|js)$|@(sentry|wixpress|example|domain|email|sentry-next)\.|^(nome|name|your|tuo|mail)@|@2x|u003e/i;
const IG_RESERVED = new Set(['p', 'reel', 'reels', 'explore', 'accounts', 'stories', 'tv', 'about', 'developer', 'legal', 'direct']);

// Email offuscate da Cloudflare (data-cfemail).
function decodeCf(hex) {
  const key = parseInt(hex.slice(0, 2), 16);
  let s = '';
  for (let i = 2; i < hex.length; i += 2) s += String.fromCharCode(parseInt(hex.slice(i, i + 2), 16) ^ key);
  return s;
}

function igHandleFromUrl(u) {
  const m = String(u).match(/instagram\.com\/([A-Za-z0-9._]{1,30})/i);
  if (!m) return '';
  const h = m[1].replace(/\.$/, '').toLowerCase();
  return IG_RESERVED.has(h) ? '' : h;
}

function extract(html) {
  const text = html.replace(/&#64;|&#x40;|\[at\]|\(at\)/gi, '@');
  const emails = new Set();
  for (const m of text.matchAll(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g)) {
    const e = m[0].toLowerCase().replace(/^\.+|\.+$/g, '');
    if (!BAD_EMAIL.test(e)) emails.add(e);
  }
  for (const m of html.matchAll(/data-cfemail="([0-9a-f]+)"/gi)) emails.add(decodeCf(m[1]).toLowerCase());

  const pick = (re) => [...new Set([...html.matchAll(re)].map((m) => m[0]))];
  const instagram = [...new Set(pick(/https?:\/\/(www\.)?instagram\.com\/[A-Za-z0-9._]+/gi).map(igHandleFromUrl).filter(Boolean))];
  const facebook = pick(/https?:\/\/(www\.|it-it\.|m\.)?facebook\.com\/(?!sharer|share|plugins|tr\b|dialog)[A-Za-z0-9.\-_/]+/gi).slice(0, 1);
  const tiktok = pick(/https?:\/\/(www\.)?tiktok\.com\/@[A-Za-z0-9._]+/gi).slice(0, 1);
  const whatsapp = pick(/https?:\/\/(wa\.me\/\d+|api\.whatsapp\.com\/send\?phone=\d+)/gi).slice(0, 1);

  const contactLinks = [...html.matchAll(/href="([^"#]+)"[^>]*>([^<]{0,60})</gi)]
    .filter((m) => /contatt|contact|chi-siamo|chi siamo|about|dove-siamo/i.test(m[1] + ' ' + m[2]))
    .map((m) => m[1]);
  return { emails: [...emails], instagram, facebook, tiktok, whatsapp, contactLinks };
}

async function scrapeWebsite(site) {
  const empty = { email: '', instagram: '', facebook: '', tiktok: '', whatsapp: '', sito_ok: '' };
  if (!site) return empty;
  // A volte su Maps il "sito" è direttamente Instagram o Facebook.
  if (/instagram\.com/i.test(site)) return { ...empty, instagram: igHandleFromUrl(site) };
  if (/facebook\.com/i.test(site)) return { ...empty, facebook: site };

  const home = await fetchText(site);
  if (!home.ok) return { ...empty, sito_ok: `no (${home.status || home.error || 'errore'})` };
  const found = extract(home.html);
  const base = new URL(home.url);
  const extra = [...new Set(found.contactLinks.map((h) => { try { return new URL(h, base).href; } catch { return ''; } }))]
    .filter((u) => u && new URL(u).hostname === base.hostname)
    .slice(0, 2);
  for (const u of extra) {
    const r = await fetchText(u);
    if (!r.ok) continue;
    const f = extract(r.html);
    for (const k of ['emails', 'instagram', 'facebook', 'tiktok', 'whatsapp']) found[k] = [...new Set([...found[k], ...f[k]])];
  }
  // Preferisci email dello stesso dominio del sito.
  const domain = base.hostname.replace(/^www\./, '');
  found.emails.sort((a, b) => (b.endsWith(domain) ? 1 : 0) - (a.endsWith(domain) ? 1 : 0));
  return {
    email: found.emails.slice(0, 3).join(' | '),
    instagram: found.instagram[0] || '',
    facebook: found.facebook[0] || '',
    tiktok: found.tiktok[0] || '',
    whatsapp: found.whatsapp[0] || '',
    sito_ok: 'si',
  };
}

module.exports = { scrapeWebsite, extract, igHandleFromUrl };
