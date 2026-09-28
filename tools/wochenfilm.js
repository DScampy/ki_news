#!/usr/bin/env node
/*
 * Wochenfilm als MP4 (28.09.26, Auftrag 4).
 *
 * Rendert wochenfilm.html (window.__film = {dauer, render(t), ready}) Bild fuer Bild
 * mit Playwright und baut per ffmpeg ein MP4 fuer Reels (1080x1920, H.264, yuv420p,
 * faststart). Deterministisch: render(t) zeichnet fuer dieselbe Zeit dasselbe Bild.
 * Aufgenommen wird die ganze Buehne (#px-film-frame: Canvas + Text-Ebenen), nicht nur
 * das Canvas - Titel und Quellen liegen als HTML darueber. CSS-Uebergaenge sind
 * waehrend der Aufnahme aus, sonst haengt ein Bild davon ab, wie schnell der Rechner ist.
 * Postet NICHTS - erst das Test-MP4 fuer Daniel.
 *
 * Aufruf (vom Repo-Root):
 *   node tools/wochenfilm.js [--out wochenfilm.mp4] [--fps 30] [--crf 20] [--sekunden 45]
 * Braucht: playwright (npm) mit Chromium, ffmpeg mit libx264 (Pfad ueber FFMPEG=...).
 * KI_ROUTE_EXTERN=1 laedt externe Poster ueber Node statt ueber den Browser.
 */
"use strict";
const http = require("http");
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");

function lade(modul, reserve) {
  try { return require(modul); } catch (e) { return require(reserve); }
}
const { chromium } = lade("playwright", process.env.PLAYWRIGHT_PATH || "/opt/node22/lib/node_modules/playwright");

const arg = (name, standard) => {
  const i = process.argv.indexOf("--" + name);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : standard;
};
const ROOT = path.resolve(__dirname, "..");
const OUT = path.resolve(ROOT, arg("out", "wochenfilm.mp4"));
const FPS = Number(arg("fps", "30"));
const CRF = String(arg("crf", "20"));
const FFMPEG = process.env.FFMPEG || "ffmpeg";

const TYPEN = { ".html": "text/html; charset=utf-8", ".json": "application/json", ".js": "text/javascript", ".css": "text/css",
  ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".mp4": "video/mp4" };

// Kleiner statischer Server fuer das Repo (fetch() der Seite braucht HTTP)
function server() {
  return new Promise(resolve => {
    const s = http.createServer((req, res) => {
      const p = decodeURIComponent(req.url.split("?")[0]);
      const datei = path.join(ROOT, p === "/" ? "index.html" : p);
      if (!datei.startsWith(ROOT) || !fs.existsSync(datei) || fs.statSync(datei).isDirectory()) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { "Content-Type": TYPEN[path.extname(datei)] || "application/octet-stream" });
      fs.createReadStream(datei).pipe(res);
    });
    s.listen(0, "127.0.0.1", () => resolve(s));
  });
}

(async () => {
  const s = await server();
  const url = `http://127.0.0.1:${s.address().port}/wochenfilm.html`;
  const browser = await chromium.launch();
  // Buehnenbreite messen, dann mit passendem Skalierungsfaktor neu oeffnen -> 1080 px breit
  const mess = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await mess.goto(url, { waitUntil: "load" });
  const breiteCss = await mess.evaluate(() => document.getElementById("px-film-frame").getBoundingClientRect().width);
  await mess.close();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1080 / breiteCss });
  const page = await ctx.newPage();
  // Optional: externe Bilder ueber Node laden (Umgebungen, deren Browser externem
  // HTTPS nicht vertraut, z.B. hinter einem TLS-Proxy). KI_ROUTE_EXTERN=1 setzen.
  if (process.env.KI_ROUTE_EXTERN === "1") {
    await page.route(u => !/^https?:\/\/127\.0\.0\.1/.test(u.href), async r => {
      try { await r.fulfill({ response: await r.fetch() }); } catch (e) { await r.abort(); }
    });
  }
  const fehler = [];
  page.on("pageerror", e => fehler.push(e.message));
  await page.goto(url, { waitUntil: "load" });
  const info = await page.evaluate(async () => {
    const f = window.__film;
    if (!f) throw new Error("window.__film fehlt");
    const r = await f.ready;
    if (typeof f.pause === "function") f.pause();
    const st = document.createElement("style");
    st.textContent = "*,*::before,*::after{transition:none!important;animation:none!important}";
    document.head.appendChild(st);
    return Object.assign({ dauer: f.dauer, breite: f.breite, hoehe: f.hoehe }, r || {});
  });
  const dauer = Number(arg("sekunden", String(info.dauer)));
  const frames = Math.round(dauer * FPS);
  console.log(`wochenfilm: ${info.breite}x${info.hoehe}, ${dauer} s, ${FPS} fps = ${frames} Bilder, Szenen: ${info.szenen}, Poster: ${info.poster}`);
  if (info.fehler) console.log("wochenfilm: WARNUNG - die Seite meldet fehlende Daten, der Film zeigt nur die Rahmen.");

  const ff = spawn(FFMPEG, ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "mjpeg", "-i", "-",
    "-vf", "scale=1080:1920:flags=lanczos,setsar=1", "-c:v", "libx264", "-preset", "medium", "-crf", CRF, "-pix_fmt", "yuv420p", "-r", String(FPS), "-movflags", "+faststart", OUT],
    { stdio: ["pipe", "inherit", "inherit"] });
  const fertig = new Promise((ok, nein) => ff.on("close", c => (c === 0 ? ok() : nein(new Error("ffmpeg Exit " + c)))));

  const buehne = page.locator("#px-film-frame");
  await buehne.scrollIntoViewIfNeeded();
  const start = Date.now();
  for (let i = 0; i < frames; i++) {
    await page.evaluate(t => window.__film.render(t), i / FPS);
    const puffer = await buehne.screenshot({ type: "jpeg", quality: 92, animations: "disabled", caret: "hide" });
    if (!ff.stdin.write(puffer)) await new Promise(r => ff.stdin.once("drain", r));
    if (i % (FPS * 5) === 0) process.stdout.write(`  ${Math.round(i / FPS)} s von ${dauer} s\r`);
  }
  ff.stdin.end();
  await fertig;
  await browser.close();
  s.close();
  const groesse = fs.statSync(OUT).size;
  console.log(`\nwochenfilm: ${path.relative(ROOT, OUT)} geschrieben, ${(groesse / 1e6).toFixed(1)} MB, ${((Date.now() - start) / 1000).toFixed(0)} s Renderzeit`
    + (fehler.length ? `, Seitenfehler: ${fehler.slice(0, 3).join(" | ")}` : ""));
})().catch(e => { console.error("wochenfilm: FEHLER", e.message); process.exit(1); });
