const { spawn } = require('node:child_process');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('/Users/jason0706.kim/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function writeFrame(stream, jpeg) {
  const header = Buffer.allocUnsafe(4);
  header.writeUInt32BE(jpeg.length, 0);
  if (!stream.write(header)) {
    await new Promise((resolve) => stream.once('drain', resolve));
  }
  if (!stream.write(jpeg)) {
    await new Promise((resolve) => stream.once('drain', resolve));
  }
}

async function main() {
  const [htmlPath, outputPath, encoderPath] = process.argv.slice(2);
  if (!htmlPath || !outputPath || !encoderPath) {
    throw new Error('usage: node record_realtime.js input.html output.mp4 encoder');
  }

  const width = 1920;
  const height = 1080;
  const fps = 30;
  const duration = Number(process.env.DURATION_SECONDS || 142);
  const totalFrames = Math.round(duration * fps);

  const encoder = spawn(encoderPath, [outputPath, String(width), String(height), String(fps)], {
    stdio: ['pipe', 'inherit', 'inherit'],
  });
  const browser = await chromium.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
    args: [
      '--hide-scrollbars',
      '--disable-background-timer-throttling',
      '--disable-renderer-backgrounding',
      '--force-device-scale-factor=1',
    ],
  });

  try {
    const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
    await page.goto(pathToFileURL(path.resolve(htmlPath)).href, { waitUntil: 'load' });
    await page.evaluate(() => {
      playing = false;
      document.querySelector('#ui')?.classList.add('hide');
      document.querySelector('#hint')?.classList.add('hide');
      fit();
      T = 0;
      render(0);
    });

    let latestFrame = await page.screenshot({
      type: 'jpeg',
      quality: 94,
      clip: { x: 0, y: 0, width, height },
    });
    const cdp = await page.context().newCDPSession(page);
    cdp.on('Page.screencastFrame', async (event) => {
      latestFrame = Buffer.from(event.data, 'base64');
      await cdp.send('Page.screencastFrameAck', { sessionId: event.sessionId });
    });
    await cdp.send('Page.startScreencast', {
      format: 'jpeg',
      quality: 94,
      maxWidth: width,
      maxHeight: height,
      everyNthFrame: 1,
    });

    await page.evaluate(() => {
      T = 0;
      last = 0;
      playing = true;
    });
    const startedAt = performance.now();
    for (let frame = 0; frame < totalFrames; frame += 1) {
      const target = startedAt + (frame * 1000) / fps;
      const remaining = target - performance.now();
      if (remaining > 0) {
        await delay(remaining);
      }
      await writeFrame(encoder.stdin, latestFrame);
      if (frame > 0 && frame % (fps * 10) === 0) {
        process.stderr.write(`captured ${frame / fps}s\n`);
      }
    }
    await page.evaluate(() => { playing = false; });
    await cdp.send('Page.stopScreencast');
    encoder.stdin.end();
  } finally {
    await browser.close();
  }

  const exitCode = await new Promise((resolve, reject) => {
    encoder.once('error', reject);
    encoder.once('close', resolve);
  });
  if (exitCode !== 0) {
    throw new Error(`encoder exited with code ${exitCode}`);
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});

