const { spawn } = require('node:child_process');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('/Users/jason0706.kim/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

(async () => {
const [htmlPath, outputPath, encoderPath] = process.argv.slice(2);
if (!htmlPath || !outputPath || !encoderPath) {
  throw new Error('usage: node render_html.js input.html output.mp4 encoder');
}

const width = 1920;
const height = 1080;
const fps = 30;
const duration = Number(process.env.DURATION_SECONDS || 142);
const totalFrames = duration * fps;

const encoder = spawn(encoderPath, [outputPath, String(width), String(height), String(fps)], {
  stdio: ['pipe', 'inherit', 'inherit'],
});

const browser = await chromium.launch({
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: true,
  args: ['--hide-scrollbars', '--disable-gpu-vsync', '--force-device-scale-factor=1'],
});

try {
  const page = await browser.newPage({
    viewport: { width, height },
    deviceScaleFactor: 1,
  });
  await page.goto(pathToFileURL(path.resolve(htmlPath)).href, { waitUntil: 'load' });
  await page.evaluate(() => {
    playing = false;
    document.querySelector('#ui')?.classList.add('hide');
    document.querySelector('#hint')?.classList.add('hide');
    fit();
  });

  for (let frame = 0; frame < totalFrames; frame += 1) {
    const time = frame / fps;
    await page.evaluate((value) => {
      playing = false;
      T = value;
      render(value);
    }, time);
    const jpeg = await page.screenshot({
      type: 'jpeg',
      quality: 94,
      clip: { x: 0, y: 0, width, height },
      animations: 'disabled',
    });
    const header = Buffer.allocUnsafe(4);
    header.writeUInt32BE(jpeg.length, 0);
    if (!encoder.stdin.write(header)) {
      await new Promise((resolve) => encoder.stdin.once('drain', resolve));
    }
    if (!encoder.stdin.write(jpeg)) {
      await new Promise((resolve) => encoder.stdin.once('drain', resolve));
    }
    if (frame > 0 && frame % (fps * 10) === 0) {
      process.stderr.write(`rendered ${frame / fps}s\n`);
    }
  }
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
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
