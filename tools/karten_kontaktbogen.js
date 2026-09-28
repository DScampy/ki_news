/**
 * Kontaktbogen-Renderer (Auftrag 6, 28.09.2026) - von tools/karten_kontaktbogen.py aufgerufen.
 * Liest <ordner>/kontaktbogen.json, rendert je Karte ein Poster-PNG bei t = 6 s (wie make_poster
 * in generate_news_cards.py) und fuer markierte Karten ein MP4 ohne Ton (bildgenau ueber
 * KI_RENDER_AT, 24 fps, 840x1320 wie record.js mit CARD_SCALE=2). Schreibt <ordner>/index.html.
 * Env: FFMPEG=<pfad> (sonst ffmpeg aus PATH), KI_ROUTE_EXTERN=1 laedt Schriften ueber Node.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
function lade(modul, reserve) { try { return require(modul); } catch (e) { return require(reserve); } }
const { chromium } = lade("playwright", process.env.PLAYWRIGHT_PATH || "/opt/node22/lib/node_modules/playwright");

const ORDNER = path.resolve(process.argv[2] || "_vorschau");
const FFMPEG = process.env.FFMPEG || "ffmpeg";
const FPS = 24, POSTER_T = 6;
const liste = JSON.parse(fs.readFileSync(path.join(ORDNER, "kontaktbogen.json"), "utf8"));
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function seite(ctx, rel) {
  const page = await ctx.newPage();
  const fehler = [];
  page.on("pageerror", e => fehler.push(e.message));
  await page.goto("file://" + path.join(ORDNER, rel) + "?rec=1", { waitUntil: "load", timeout: 30000 });
  await page.evaluate(() => document.fonts.ready);
  return { page, fehler };
}

(async () => {
  const browser = await chromium.launch({ args: ["--no-sandbox"] });
  const ctx = await browser.newContext({ viewport: { width: 420, height: 660 }, deviceScaleFactor: 2 });
  if (process.env.KI_ROUTE_EXTERN === "1") {
    await ctx.route(u => /^https?:/.test(u.href), async r => {
      try { await r.fulfill({ response: await r.fetch() }); } catch (e) { await r.abort(); }
    });
  }
  fs.mkdirSync(path.join(ORDNER, "png"), { recursive: true });
  fs.mkdirSync(path.join(ORDNER, "mp4"), { recursive: true });
  const probleme = [];
  for (const e of liste) {
    for (const art of ["alt", "neu"]) {
      const { page, fehler } = await seite(ctx, e[art].html);
      const t0 = Date.now();
      await page.evaluate(t => window.KI_RENDER_AT(t), POSTER_T);
      e[art].ms = Date.now() - t0;
      await page.screenshot({ path: path.join(ORDNER, e[art].png) });
      if (e[art].mp4) {
        const ff = spawn(FFMPEG, ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "mjpeg", "-i", "-",
          "-vf", "scale=840:1320", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart",
          path.join(ORDNER, e[art].mp4)], { stdio: ["pipe", "inherit", "inherit"] });
        const fertig = new Promise((ok, nein) => ff.on("close", c => (c === 0 ? ok() : nein(new Error("ffmpeg Exit " + c)))));
        const n = e.dauer * FPS, tr = Date.now();
        for (let i = 0; i < n; i++) {
          await page.evaluate(t => window.KI_RENDER_AT(t), i / FPS);
          const bild = await page.screenshot({ type: "jpeg", quality: 92 });
          if (!ff.stdin.write(bild)) await new Promise(r => ff.stdin.once("drain", r));
        }
        ff.stdin.end();
        await fertig;
        e[art].mp4_s = Math.round((Date.now() - tr) / 100) / 10;
        console.log("  MP4 " + e[art].mp4 + " (" + e[art].mp4_s + " s)");
      }
      if (fehler.length) probleme.push(e[art].html + ": " + fehler.join(" | "));
      await page.close();
    }
    console.log("  " + e.id.slice(0, 60) + "  alt " + e.alt.stil + " / neu " + e.neu.stil);
  }
  await browser.close();

  const zeilen = liste.map((e, i) => `
  <section class="z">
    <div class="meta"><b>${String(i + 1).padStart(2, "0")}</b> ${esc(e.titel)}<span>${esc(e.quelle)} · Motiv ${esc(e.motiv)}</span></div>
    <figure><img src="${e.alt.png}" alt="alt ${esc(e.alt.stil)}" loading="lazy"><figcaption>alt · ${esc(e.alt.stil)}</figcaption></figure>
    <figure>${e.neu.mp4 ? `<video src="${e.neu.mp4}" poster="${e.neu.png}" controls muted loop playsinline></video>`
      : `<img src="${e.neu.png}" alt="neu ${esc(e.neu.stil)}" loading="lazy">`}<figcaption>neu · ${esc(e.neu.stil)}${e.neu.mp4 ? " · MP4" : ""}</figcaption></figure>
  </section>`).join("");
  fs.writeFileSync(path.join(ORDNER, "index.html"), `<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Kontaktbogen Karten</title>
<style>
:root{--bg:#f4f2ec;--ink:#17171a;--sub:#6b6a66;--line:#dcd8cc}
@media (prefers-color-scheme:dark){:root{--bg:#111114;--ink:#ecebe6;--sub:#9a9993;--line:#2a2a30}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:24px;margin:0 0 4px}p.l{color:var(--sub);margin:0 0 24px}
.z{display:grid;grid-template-columns:1fr 1fr;gap:12px 16px;padding:18px 0;border-top:1px solid var(--line)}
.meta{grid-column:1/-1;font-weight:600}.meta b{font-family:ui-monospace,monospace;margin-right:6px}
.meta span{display:block;font-weight:400;color:var(--sub);font-size:13px}
figure{margin:0}img,video{width:100%;height:auto;display:block;border-radius:6px;background:#000}
figcaption{font:12px ui-monospace,monospace;color:var(--sub);margin-top:6px}
</style></head><body><main>
<h1>Kontaktbogen: Karten alt und neu</h1>
<p class="l">${liste.length} echte Meldungen aus cards.json. Links wie live gerendert, rechts gleiches Motiv in einem neuen Stil
(neon, typo, riso reihum). Standbild bei 6 s wie das Poster der Pipeline. Nichts davon ist live geschaltet.</p>
${zeilen}
</main></body></html>
`);
  fs.writeFileSync(path.join(ORDNER, "kontaktbogen.json"), JSON.stringify(liste, null, 1));
  if (probleme.length) { console.error("JS-Fehler:\n" + probleme.join("\n")); process.exit(2); }
  console.log("  fertig: " + path.join(ORDNER, "index.html"));
})().catch(e => { console.error(e); process.exit(1); });
