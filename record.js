/**
 * record.js
 * =========
 * Rendert eine lokale HTML-Datei mit Playwright (headless Chromium),
 * nimmt Screenshots in regelmäßigen Abständen auf (page.screenshot),
 * konvertiert das Ergebnis via FFmpeg zu MP4 (optional mit Audio).
 *
 * Aufruf:
 *   node record.js <html_path> <mp4_path> [width] [height] [duration_sec] [audio_path]
 *
 * Abhängigkeiten (im CI installiert):
 *   npm install playwright
 *   npx playwright install --with-deps chromium
 *   sudo apt-get install -y ffmpeg
 */

const { chromium } = require('playwright');
const { execSync }  = require('child_process');
const fs            = require('fs');
const path          = require('path');

// ─── Argumente ────────────────────────────────────────────────────────────────

const [,, htmlPath, mp4Path, widthArg, heightArg, durationArg, audioPath] = process.argv;

if (!htmlPath || !mp4Path) {
  console.error('Usage: node record.js <html_path> <mp4_path> [width] [height] [duration_sec] [audio_path]');
  process.exit(1);
}

const WIDTH    = parseInt(widthArg    || '420', 10);
const HEIGHT   = parseInt(heightArg   || '660', 10);
const DURATION = parseInt(durationArg || '8',   10);
const FPS      = 8;   // 8 fps genügt für animierte Newskarten

const absHtml  = path.resolve(htmlPath);
const absMp4   = path.resolve(mp4Path);
const absAudio = audioPath ? path.resolve(audioPath) : null;
const hasAudio = absAudio && fs.existsSync(absAudio);

if (!fs.existsSync(absHtml)) {
  console.error(`HTML file not found: ${absHtml}`);
  process.exit(1);
}

fs.mkdirSync(path.dirname(absMp4), { recursive: true });

// ─── Haupt-Funktion ──────────────────────────────────────────────────────────

(async () => {
  console.log(`[record.js] Start: ${path.basename(absHtml)} → ${path.basename(absMp4)}`);
  console.log(`            Viewport: ${WIDTH}×${HEIGHT}, Dauer: ${DURATION}s, ${FPS}fps${hasAudio ? ', +Audio' : ''}`);

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
    deviceScaleFactor: 1,
  });

  const page = await context.newPage();

  const fileUrl = `file://${absHtml.replace(/\\/g, '/')}`;
  await page.goto(fileUrl, { waitUntil: 'networkidle', timeout: 30000 });

  // Kurz warten bis Animationen anlaufen
  await page.waitForTimeout(300);

  // ─── Frame-Verzeichnis anlegen ───────────────────────────────────────────
  const frameDir = path.join(path.dirname(absMp4), `_frames_${Date.now()}`);
  fs.mkdirSync(frameDir, { recursive: true });

  const totalFrames = DURATION * FPS;
  const intervalMs  = Math.round(1000 / FPS);

  console.log(`[record.js] Capturing ${totalFrames} frames @ ${FPS}fps (interval ${intervalMs}ms)...`);

  // ─── Screenshots aufnehmen ────────────────────────────────────────────────
  for (let i = 0; i < totalFrames; i++) {
    const framePath = path.join(frameDir, `frame_${String(i).padStart(6, '0')}.jpg`);
    const buf = await page.screenshot({ type: 'jpeg', quality: 85 });
    fs.writeFileSync(framePath, buf);
    if (i < totalFrames - 1) {
      await page.waitForTimeout(intervalMs);
    }
  }

  await browser.close();

  // Prüfen ob Frames wirklich da sind
  const frameFiles = fs.readdirSync(frameDir).filter(f => f.endsWith('.jpg'));
  console.log(`[record.js] Frames gespeichert: ${frameFiles.length} (erwartet: ${totalFrames})`);

  if (frameFiles.length === 0) {
    console.error('[record.js] Keine Frames — Abbruch.');
    fs.rmSync(frameDir, { recursive: true, force: true });
    process.exit(1);
  }

  // ─── FFmpeg: Frames → MP4 (optional mit Audio) ──────────────────────────
  const ffmpegArgs = [
    'ffmpeg', '-y',
    '-framerate', String(FPS),
    '-i', path.join(frameDir, 'frame_%06d.jpg'),
    ...(hasAudio ? ['-i', absAudio] : []),
    '-vf', `scale=${WIDTH}:${HEIGHT}`,
    '-c:v', 'libx264',
    '-preset', 'fast',
    '-crf', '23',
    '-pix_fmt', 'yuv420p',
    '-movflags', '+faststart',
    '-t', String(DURATION),
    ...(hasAudio ? ['-c:a', 'aac', '-b:a', '128k'] : []),
    absMp4,
  ];

  const ffmpegCmd = ffmpegArgs.join(' ');
  console.log(`[record.js] FFmpeg: ${ffmpegCmd}`);

  try {
    // stdio: 'pipe' → stderr wird captured → echter FFmpeg-Fehler sichtbar
    execSync(ffmpegCmd, { stdio: ['pipe', 'pipe', 'pipe'] });
  } catch (err) {
    const ffmpegErr = err.stderr ? err.stderr.toString('utf8') : '';
    console.error('[record.js] FFmpeg fehlgeschlagen!');
    console.error('[record.js] FFmpeg stderr:');
    console.error(ffmpegErr.slice(-3000));
    fs.rmSync(frameDir, { recursive: true, force: true });
    process.exit(1);
  }

  // ─── Aufräumen ──────────────────────────────────────────────────────────
  fs.rmSync(frameDir, { recursive: true, force: true });

  const stat = fs.statSync(absMp4);
  console.log(`[record.js] ✓ MP4 fertig: ${absMp4} (${(stat.size / 1024).toFixed(1)} KB)`);

})().catch((err) => {
  console.error('[record.js] Ungefangener Fehler:', err);
  process.exit(1);
});
