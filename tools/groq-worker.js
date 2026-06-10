/**
 * groq-worker.js — Cloudflare Worker als sicherer Proxy für den
 * KI-News-Chat-Bot (Startseite). Hält den Groq-API-Key serverseitig
 * und begrenzt das Volumen, damit das kostenlose Kontingent reicht.
 *
 * ── Deploy (einmalig, ~5 Minuten, alles kostenlos) ────────────────
 * 1. https://dash.cloudflare.com → Workers & Pages → Create Worker
 *    Name z.B. "ki-news-chat" → diesen Code einfügen → Deploy
 * 2. Worker → Settings → Variables → "Add secret":
 *    Name: GROQ_API_KEY, Wert: dein Key von https://console.groq.com/keys
 * 3. (Empfohlen, für echtes Tageslimit) Worker → Settings → Bindings →
 *    KV Namespace binden mit dem Namen: CHAT_KV
 * 4. Worker-URL (https://ki-news-chat.<dein-name>.workers.dev) in
 *    index.html bei CHAT_ENDPOINT eintragen.
 *
 * Limits (unten anpassbar):
 *   - max. 10 Anfragen pro IP pro Stunde
 *   - max. 300 Anfragen pro Tag insgesamt
 *   - max. 500 Zeichen pro Frage
 */

const ALLOWED_ORIGINS = ['https://ki-news.live', 'http://localhost:8000', 'http://127.0.0.1:8000'];
const MODEL = 'llama-3.3-70b-versatile';
const MAX_PER_IP_HOUR = 10;
const MAX_PER_DAY = 300;
const MAX_QUESTION_LEN = 500;

const SYSTEM_PROMPT =
  'Du bist der KI-News-Assistent auf ki-news.live, der deutschen KI-News-Seite von Daniel (@ScampyKI). ' +
  'Antworte auf Deutsch, freundlich und kurz (maximal 3 Saetze). ' +
  'Du beantwortest Fragen zu KI-Themen und zu den News im Kontext. ' +
  'Wenn du etwas nicht weisst, sag das ehrlich.';

function cors(origin) {
  const o = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    'Access-Control-Allow-Origin': o,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Content-Type': 'application/json; charset=utf-8',
  };
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get('Origin') || '';
    const headers = cors(origin);

    if (request.method === 'OPTIONS') return new Response(null, { headers });
    if (request.method !== 'POST') {
      return new Response(JSON.stringify({ error: 'POST only' }), { status: 405, headers });
    }

    // ── Rate-Limits (braucht KV-Binding CHAT_KV; ohne KV: nur Längenlimit) ──
    if (env.CHAT_KV) {
      const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
      const hour = new Date().toISOString().slice(0, 13);
      const day = hour.slice(0, 10);
      const ipKey = `ip:${ip}:${hour}`;
      const dayKey = `day:${day}`;
      const [ipCount, dayCount] = await Promise.all([
        env.CHAT_KV.get(ipKey), env.CHAT_KV.get(dayKey),
      ]);
      if (parseInt(ipCount || '0') >= MAX_PER_IP_HOUR) {
        return new Response(JSON.stringify({ reply: 'Stündliches Limit erreicht – probier es später nochmal. 🙏' }), { headers });
      }
      if (parseInt(dayCount || '0') >= MAX_PER_DAY) {
        return new Response(JSON.stringify({ reply: 'Tageslimit erreicht – der Bot ist morgen wieder da. 🌙' }), { headers });
      }
      await Promise.all([
        env.CHAT_KV.put(ipKey, String(parseInt(ipCount || '0') + 1), { expirationTtl: 3700 }),
        env.CHAT_KV.put(dayKey, String(parseInt(dayCount || '0') + 1), { expirationTtl: 90000 }),
      ]);
    }

    let body;
    try { body = await request.json(); } catch {
      return new Response(JSON.stringify({ error: 'invalid json' }), { status: 400, headers });
    }
    const question = String(body.question || '').slice(0, MAX_QUESTION_LEN).trim();
    const context = String(body.context || '').slice(0, 4000);
    if (!question) {
      return new Response(JSON.stringify({ error: 'question fehlt' }), { status: 400, headers });
    }

    const groqRes = await fetch('https://api.groq.com/openai/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${env.GROQ_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: MODEL,
        max_tokens: 300,
        temperature: 0.4,
        messages: [
          { role: 'system', content: SYSTEM_PROMPT },
          { role: 'user', content: (context ? 'Aktuelle News:\n' + context + '\n\n' : '') + 'Frage: ' + question },
        ],
      }),
    });

    if (!groqRes.ok) {
      return new Response(JSON.stringify({ reply: 'Der Bot hat gerade Schluckauf – bitte gleich nochmal versuchen.' }), { headers });
    }
    const data = await groqRes.json();
    const reply = data.choices?.[0]?.message?.content || 'Keine Antwort erhalten.';
    return new Response(JSON.stringify({ reply }), { headers });
  },
};
