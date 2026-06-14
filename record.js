/**
 * record.js
 * =========
 * Rendert eine lokale HTML-Datei mit Playwright (headless Chromium),
 * nimmt einen Screen-Recording auf (WebM via CDP),
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
  console.log(`            Viewport: ${WIDTH}×${HEIGHT}, Dauer: ${DURATION}s${hasAudio ? ', +Audio' : ''}`);

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

  // ─── CDP Screen Capture starten ─────────────────────────────────────────
  const cdpSession = await context.newCDPSession(page);
  await cdpSession.send('Page.enable');

  const frames = [];
  const frameTimestamps = [];

  cdpSession.on('Page.screencastFrame', async (event) => {
    frames.push(event.data);
    frameTimestamps.push(event.metadata.timestamp);
    await cdpSession.send('Page.screencastFrameAck', { sessionId: event.sessionId });
  });

  await cdpSession.send('Page.startScreencast', {
    format: 'jpeg',
    quality: 85,
    maxWidth: WIDTH,
    maxHeight: HEIGHT,
    everyNthFrame: 1,
  });

  const fileUrl = `file://${absHtml.replace(/\\/g, '/')}`;
  await page.goto(fileUrl, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(DURATION * 1000);

  await cdpSession.send('Page.stopScreencast');
  await browser.close();

  console.log(`[record.js] Frames gesammelt: ${frames.length}`);

  if (frames.length === 0) {
    console.error('[record.js] Keine Frames — Abbruch.');
    process.exit(1);
  }

  // ─── Frames als JPG-Sequenz ablegen ─────────────────────────────────────
  const frameDir = path.join(path.dirname(absMp4), `_frames_${Date.now()}`);
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
    fps = Math.min(Math.max(fps, 6), 30);
  }
  console.log(`[record.js] Berechnete FPS: ${fps}`);

  // ─── FFmpeg: Frames → MP4 (optional mit Audio) ──────────────────────────
  const ffmpegArgs = [
    'ffmpeg', '-y',
    '-framerate', String(fps),
    '-i', path.join(frameDir, 'frame_%06d.jpg'),
    ...(hasAudio ? ['-i', absAudio] : []),
    '-vf', `scale=${WIDTH}:${HEIGHT}:force_original_aspect_ratio=decrease,pad=${WIDTH}:${HEIGHT}:(ow-iw)/2:(oh-ih)/2`,
    '-c:v', 'libx264',
    '-preset', 'fast',
    '-crf', '23',
    '-pix_fmt', 'yuv420p',
    '-movflags', '+faststart',
    ...(hasAudio
      ? ['-c:a', 'aac', '-b:a', '128k', '-shortest']
      : ['-t', String(DURATION)]
    ),
    absMp4,
  ];

  const ffmpegCmd = ffmpegArgs.join(' ');
  console.log(`[record.js] FFmpeg: ${ffmpegCmd}`);

  try {
    execSync(ffmpegCmd, { stdio: 'inherit' });
  } catch (err) {
    console.error('[record.js] FFmpeg fehlgeschlagen:', err.message);
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
