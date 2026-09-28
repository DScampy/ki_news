// og:image per Playwright rendern (28.09.26, Vorschlag zu Bunny-Entwurf og_bilder_v2).
//
// Oeffnet og-bilder-neu.html auf einem lokalen Server, ruft fuer die neuesten
// Meldungen aus news.json window.__og.render(meldung, canvas) auf und speichert
// je Meldung ein PNG 1200x630. NUR ENTWURF: schreibt nach _vorschau/og/ und ist
// nicht im Workflow. Fuer den Pipeline-Einsatz waere zu klaeren: Zielordner
// (assets/og/), welche Seiten das og:image bekommen, und Laufzeit im Workflow.
//
// Aufruf (Server muss laufen, z.B. python3 -m http.server 8765):
//   node tools/og_render.js [anzahl=6] [basis=http://localhost:8765]
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
let playwright;
try { playwright = require("playwright"); } catch (e) { playwright = require("/opt/node22/lib/node_modules/playwright"); }

const ANZAHL = parseInt(process.argv[2] || "6", 10);
const BASIS = (process.argv[3] || "http://localhost:8765").replace(/\/$/, "");
const ZIEL = path.join(__dirname, "..", "_vorschau", "og");

(async () => {
  fs.mkdirSync(ZIEL, { recursive: true });
  const browser = await playwright.chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1366, height: 900 } });
  const fehler = [];
  page.on("pageerror", (e) => fehler.push(e.message));
  // nur die eigene Seite laden, keine Drittanbieter
  await page.route("**/*", (r) => (r.request().url().startsWith(BASIS) ? r.continue() : r.abort()));
  await page.goto(BASIS + "/og-bilder-neu.html", { waitUntil: "load" });
  await page.waitForFunction(() => window.__og && window.__og.ready, null, { timeout: 15000 });

  const meldungen = await page.evaluate(async (n) => {
    const r = await fetch("news.json", { cache: "no-store" });
    const d = await r.json();
    return (d.news || []).filter((m) => m && m.title && m.link && !m.dub_von).slice(0, n);
  }, ANZAHL);

  const ergebnis = [];
  for (const m of meldungen) {
    const png = await page.evaluate(async (meldung) => {
      const c = document.createElement("canvas");
      c.width = window.__og.width;
      c.height = window.__og.height;
      const ok = await window.__og.render(meldung, c);
      return ok === false ? null : c.toDataURL("image/png");
    }, m);
    // Dateiname aus dem Link: story_id wird je Pipeline-Lauf neu vergeben
    const name = "og-" + crypto.createHash("sha1").update(m.link).digest("hex").slice(0, 12) + ".png";
    if (!png) { ergebnis.push({ link: m.link, fehler: "render false" }); continue; }
    fs.writeFileSync(path.join(ZIEL, name), Buffer.from(png.split(",")[1], "base64"));
    ergebnis.push({ link: m.link, titel: m.title, datei: "_vorschau/og/" + name });
  }
  fs.writeFileSync(path.join(ZIEL, "og.json"), JSON.stringify({ stand: new Date().toISOString(), ergebnis }, null, 1) + "\n");
  console.log(`og_render: ${ergebnis.filter((e) => e.datei).length}/${meldungen.length} Bilder nach _vorschau/og/, JS-Fehler: ${fehler.length}`);
  await browser.close();
  process.exit(fehler.length ? 1 : 0);
})();
