/**
 * record.js
 * =========
 * Rendert eine lokale HTML-Datei mit Playwright (headless Chromium),
 * nimmt einen Screen-Recording auf (WebM via CDP),
 * konvertiert das Ergebnis via FFmpeg zu MP4.
 *
 * Aufruf:
 *   node record.js <html_path> <mp4_path> [width] [height] [duration_sec]
 *
 * Abhängigkeiten (im CI installiert):
 *   npm install playwright
 *   npx playwright install --with-deps chromium
 *   sudo apt-get install -y ffmpeg
 */

const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs            = require('fs');
const path          = require('path');

// ─── Argumente ────────────────────────────────────────────────────────────────

const [,, htmlPath, mp4Path, widthArg, heightArg, durationArg] = process.argv;

if (!htmlPath || !mp4Path) {
  console.error('Usage: node record.js <html_path> <mp4_path> [width] [height] [duration_sec]');
  process.exit(1);
}

const WIDTH    = parseInt(widthArg  || '420',  10);
const HEIGHT   = parseInt(heightArg || '660',  10);
const DURATION = parseInt(durationArg || '8', 10);   // Sekunden

const absHtml  = path.resolve(htmlPath);
const absMp4   = path.resolve(mp4Path);
const tmpWebm  = absMp4.replace(/\.mp4$/i, '_tmp.webm');

if (!fs.existsSync(absHtml)) {
  console.error(`HTML file not found: ${absHtml}`);
  process.exit(1);
}

// Sicherstellen dass Output-Verzeichnis existiert
fs.mkdirSync(path.dirname(absMp4), { recursive: true });

// ─── Haupt-Funktion ──────────────────────────────────────────────────────────

(async () => {
  console.log(`[record.js] Start: ${path.basename(absHtml)} → ${path.basename(absMp4)}`);
  console.log(`            Viewport: ${WIDTH}×${HEIGHT}, Dauer: ${DURATION}s`);

  const browser = await chromium.launch({
    headless: true,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-gpu',
      '--disable-web-security',
    ],
  });

  const context = await browser.newContext({
    viewport: { width: WIDTH, height: HEIGHT },
    deviceScaleFactor: 2,   // 2x-Rendering → scharfe Schrift
  });

  const page = await context.newPage();

  // ─── CDP Screen Capture starten ─────────────────────────────────────────
  const cdpSession = await context.newCDPSession(page);

  await cdpSession.send('Page.enable');

  // Screencasting via CDP (JPEG frames)
  const frames = [];
  const frameTimestamps = [];

  cdpSession.on('Page.screencastFrame', async (event) => {
    frames.push(event.data);           // base64 JPEG
    frameTimestamps.push(event.metadata.timestamp);
    await cdpSession.send('Page.screencastFrameAck', { sessionId: event.sessionId });
  });

  await cdpSession.send('Page.startScreencast', {
    format: 'jpeg',
    quality: 95,            // höhere JPEG-Qualität
    maxWidth: WIDTH * 2,    // 2x für scharfe Schrift
    maxHeight: HEIGHT * 2,
    everyNthFrame: 1,
  });

  // Seite laden
  const fileUrl = `file://${absHtml.replace(/\\/g, '/')}`;
  await page.goto(fileUrl, { waitUntil: 'networkidle', timeout: 30000 });

  // Animation laufen lassen (+1s Puffer für -ss 0.5 Trim)
  await page.waitForTimeout((DURATION + 1) * 1000);

  await cdpSession.send('Page.stopScreencast');

  await browser.close();

  console.log(`[record.js] Frames gesammelt: ${frames.length}`);

  if (frames.length === 0) {
    console.error('[record.js] Keine Frames — Abbruch.');
    process.exit(1);
  }

  // ─── Frames als PNG-Sequenz in /tmp ablegen ──────────────────────────────
  const frameDir = path.join(path.dirname(tmpWebm), `_frames_${Date.now()}`);
  fs.mkdirSync(frameDir, { recursive: true });

  for (let i = 0; i < frames.length; i++) {
    const framePath = path.join(frameDir, `frame_${String(i).padStart(6, '0')}.jpg`);
    fs.writeFileSync(framePath, Buffer.from(frames[i], 'base64'));
  }

  // Durchschnittliche FPS berechnen
  let fps = 24;
  if (frameTimestamps.length > 1) {
    const totalSec = frameTimestamps[frameTimestamps.length - 1] - frameTimestamps[0];
    fps = Math.round((frames.length - 1) / totalSec) || 24;
    fps = Math.min(Math.max(fps, 6), 30);   // zwischen 6 und 30 clamp
  }
  console.log(`[record.js] Berechnete FPS: ${fps}`);

  // ─── FFmpeg: Frames → MP4 (SD + optional HD) ────────────────────────────
  const absHd = absMp4.replace(/\.mp4$/i, '_hd.mp4');

  const buildMp4 = (outPath, scaleW, scaleH, crf) => {
    const args = [
      '-y',
      '-ss', '0.5',
      '-framerate', String(fps),
      '-i', path.join(frameDir, 'frame_%06d.jpg'),
      '-vf', `scale=${scaleW}:${scaleH}`,
      '-c:v', 'libx264',
      '-preset', 'fast',
      '-crf', String(crf),
      '-pix_fmt', 'yuv420p',
      '-movflags', '+faststart',
      '-t', String(DURATION),
      outPath,
    ];
    console.log(`[record.js] FFmpeg → ${path.basename(outPath)} (${scaleW}×${scaleH})`);
    execFileSync('ffmpeg', args, { stdio: 'inherit' });
  };

try {
  // SD: 420×660 — Web-Player & Archiv
  buildMp4(absMp4, WIDTH, HEIGHT, 18);

  // HD: 1080×1698 — YouTube Shorts / Desktop (nur wenn RENDER_HD=1 gesetzt)
  if (process.env.RENDER_HD === '1') {
    buildMp4(absHd, 1080, 1698, 16);
    const hdStat = fs.statSync(absHd);
    console.log(`[record.js] ✓ HD: ${absHd} (${(hdStat.size / 1024).toFixed(1)} KB)`);
  }
} catch (err) {
  console.error('[record.js] FFmpeg fehlgeschlagen:', err.message);
  fs.rmSync(frameDir, { recursive: true, force: true });
  process.exit(1);
}

  // ─── Aufräumen ──────────────────────────────────────────────────────────
  fs.rmSync(frameDir, { recursive: true, force: true });
  if (fs.existsSync(tmpWebm)) fs.unlinkSync(tmpWebm);

  const stat = fs.statSync(absMp4);
  console.log(`[record.js] ✓ MP4 fertig: ${absMp4} (${(stat.size / 1024).toFixed(1)} KB)`);
})().catch((err) => {
  console.error('[record.js] Ungefangener Fehler:', err);
  process.exit(1);
});
