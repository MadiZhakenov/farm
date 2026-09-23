/**
 * Launch Chrome with Farm Flow loaded + remote debugging on :9222.
 * Persistent profile → log in once, reuse forever.
 *
 * Usage: npm run launch
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import http from "node:http";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const EXT = path.resolve(ROOT, "extension");
const PROFILE = path.resolve(__dirname, "profile");
const PORT = Number(process.env.FARM_CDP_PORT || 9222);
const START_URL =
  process.env.FARM_START_URL || "https://labs.google/fx/tools/flow";

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"
].filter(Boolean);

function findChrome() {
  for (const p of CHROME_CANDIDATES) {
    if (fs.existsSync(p)) return p;
  }
  throw new Error("Chrome/Edge not found. Set CHROME_PATH.");
}

function cdpAlive() {
  return new Promise((resolve) => {
    const req = http.get(
      { host: "127.0.0.1", port: PORT, path: "/json/version", timeout: 800 },
      (res) => {
        res.resume();
        resolve(res.statusCode === 200);
      }
    );
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function main() {
  if (!(await cdpAlive())) {
    fs.mkdirSync(PROFILE, { recursive: true });
    const chrome = findChrome();
    const args = [
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${PROFILE}`,
      `--disable-extensions-except=${EXT}`,
      `--load-extension=${EXT}`,
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-features=ChromeWhatsNewUI",
      START_URL
    ];
    console.log(`[lab] Chrome: ${chrome}`);
    console.log(`[lab] Extension: ${EXT}`);
    console.log(`[lab] Profile: ${PROFILE}`);
    console.log(`[lab] CDP: http://127.0.0.1:${PORT}`);
    console.log(`[lab] Starting…`);
    const child = spawn(chrome, args, {
      detached: true,
      stdio: "ignore"
    });
    child.unref();
    for (let i = 0; i < 40; i++) {
      await new Promise((r) => setTimeout(r, 500));
      if (await cdpAlive()) break;
    }
    if (!(await cdpAlive())) {
      throw new Error(`CDP not up on :${PORT}`);
    }
    console.log(`[lab] Ready. Log into Google in that window, then open a Flow project.`);
  } else {
    console.log(`[lab] Already running on :${PORT}`);
  }

  // Write marker for agent
  fs.writeFileSync(
    path.join(__dirname, "cdp.json"),
    JSON.stringify(
      {
        port: PORT,
        profile: PROFILE,
        extension: EXT,
        startedAt: new Date().toISOString()
      },
      null,
      2
    )
  );
}

main().catch((e) => {
  console.error("[lab]", e.message || e);
  process.exit(1);
});
