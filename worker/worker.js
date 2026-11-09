/* TickerChatter news fetcher (Cloudflare Worker).

   Browsers aren't allowed to read news feeds from other sites directly,
   so the website asks this tiny server instead:

     GET https://<your-worker>.workers.dev/?q=Micron&symbol=MU

   It does step 1 of the pipeline (collect headlines) and returns JSON.
   Everything else runs in the visitor's browser.

   To get counts for every day, it asks Google News once per day for the
   last 15 days (each search returns at most 100 results), plus Yahoo
   Finance for the symbol. Results are cached for 20 minutes. */

const DAYS = 15;
const CACHE_SECONDS = 1200;

export default {
  async fetch(request, env, ctx) {
    const cors = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Content-Type": "application/json; charset=utf-8",
    };
    if (request.method === "OPTIONS") return new Response(null, { headers: cors });

    const url = new URL(request.url);
    const q = (url.searchParams.get("q") || "").trim();
    const symbol = (url.searchParams.get("symbol") || "").trim().toUpperCase();
    if (!/^[\w .&'-]{1,40}$/.test(q) || (symbol && !/^[A-Z.]{1,6}$/.test(symbol))) {
      return new Response(JSON.stringify({ error: "Type a company name or ticker, letters only." }), { status: 400, headers: cors });
    }

    const cacheKey = new Request(`https://cache.tickerchatter/${encodeURIComponent(q.toLowerCase())}/${symbol}`);
    const cached = await caches.default.match(cacheKey);
    if (cached) return cached;

    const feeds = [];
    const today = new Date();
    for (let d = 0; d < DAYS; d++) {
      const after = isoDay(addDays(today, -d - 1));
      const before = isoDay(addDays(today, -d + 1));
      const terms = symbol && symbol !== q.toUpperCase() ? `"${q}" OR "${symbol} stock"` : `"${q}"`;
      const search = encodeURIComponent(`${terms} after:${after} before:${before}`);
      feeds.push(`https://news.google.com/rss/search?q=${search}&hl=en-US&gl=US&ceid=US:en`);
    }
    if (symbol) feeds.push(`https://feeds.finance.yahoo.com/rss/2.0/headline?s=${symbol}&region=US&lang=en-US`);

    const results = await Promise.allSettled(feeds.map((f) => getFeed(f)));
    const items = results.flatMap((r) => (r.status === "fulfilled" ? r.value : []));
    const failed = results.filter((r) => r.status === "rejected").length;

    const body = JSON.stringify({ query: q, symbol, days: DAYS, fetched_at: new Date().toISOString(), feeds: feeds.length, failed, items });
    const response = new Response(body, { headers: { ...cors, "Cache-Control": `public, max-age=${CACHE_SECONDS}` } });
    if (items.length) ctx.waitUntil(caches.default.put(cacheKey, response.clone()));
    return response;
  },
};

async function getFeed(url) {
  const res = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0 (TickerChatter)" }, cf: { cacheTtl: CACHE_SECONDS } });
  if (!res.ok) throw new Error(`${res.status}`);
  return parseRss(await res.text());
}

// Workers have no XML parser, and RSS is simple enough to read with regex.
function parseRss(xml) {
  const items = [];
  for (const block of xml.match(/<item>[\s\S]*?<\/item>/g) || []) {
    const title = decode(tag(block, "title"));
    const date = new Date(tag(block, "pubDate"));
    if (!title || isNaN(date)) continue;
    const source = decode(tag(block, "source")) || "Yahoo Finance";
    items.push({
      title: source && title.endsWith(` - ${source}`) ? title.slice(0, -source.length - 3) : title,
      link: decode(tag(block, "link")),
      source,
      published: date.toISOString().replace(/\.\d{3}Z$/, "+00:00"),
    });
  }
  return items;
}

function tag(block, name) {
  const m = block.match(new RegExp(`<${name}[^>]*>([\\s\\S]*?)<\\/${name}>`));
  return m ? m[1].replace(/^<!\[CDATA\[|\]\]>$/g, "").trim() : "";
}

function decode(s) {
  return s.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'").replace(/&#(\d+);/g, (_, n) => String.fromCharCode(n));
}

const addDays = (d, n) => new Date(d.getTime() + n * 86400000);
const isoDay = (d) => d.toISOString().slice(0, 10);
