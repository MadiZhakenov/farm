/**
 * Agent CLI — talk to Farm Flow via CDP + extension service worker.
 *
 * Commands:
 *   node agent.mjs status
 *   node agent.mjs logs [N]
 *   node agent.mjs clear-logs
 *   node agent.mjs scrape
 *   node agent.mjs shot [file]
 *   node agent.mjs start "prompt text" [--aspect 16:9] [--model "Nano Banana 2"] [--ref path.png]
 *   node agent.mjs stop
 *   node agent.mjs watch [seconds]
 *   node agent.mjs eval "JS expression on Flow page"
 *   node agent.mjs open-panel
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.FARM_CDP_PORT || 9222);
const OUT = path.join(__dirname, "out");
const PROFILE = path.join(__dirname, "profile");
const KNOWN_EXT = "elidfapcjaamaoggpdogaenmjcibabla";

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (!next || next.startsWith("--")) args[key] = true;
      else {
        args[key] = next;
        i++;
      }
    } else args._.push(a);
  }
  return args;
}

function readExtIdFromProfile() {
  try {
    const prefPath = path.join(PROFILE, "Default", "Preferences");
    const j = JSON.parse(fs.readFileSync(prefPath, "utf8"));
    const settings = j?.extensions?.settings || {};
    for (const [id, meta] of Object.entries(settings)) {
      const p = String(meta?.path || "").replace(/\\/g, "/").toLowerCase();
      if (p.endsWith("/extension") || p.includes("/farm/extension")) return id;
      if (meta?.manifest?.name === "Farm Flow") return id;
    }
  } catch (_) {}
  return process.env.FARM_EXT_ID || KNOWN_EXT;
}

async function connect() {
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`);
  return browser;
}

async function getExtensionId(browser) {
  for (const ctx of browser.contexts()) {
    for (const sw of ctx.serviceWorkers()) {
      const m = sw.url().match(/^chrome-extension:\/\/([a-z]{32})\//);
      if (m) return m[1];
    }
    for (const page of ctx.pages()) {
      const m = page.url().match(/^chrome-extension:\/\/([a-z]{32})\//);
      if (m) return m[1];
    }
  }
  return readExtIdFromProfile();
}

async function ensureServiceWorker(browser, extId) {
  for (const ctx of browser.contexts()) {
    for (const sw of ctx.serviceWorkers()) {
      if (sw.url().includes(extId)) return sw;
    }
  }
  // Wake SW by opening a tiny extension page
  const ctx = browser.contexts()[0];
  const page = await ctx.newPage();
  try {
    await page.goto(`chrome-extension://${extId}/panel.html`, {
      waitUntil: "domcontentloaded",
      timeout: 8000
    });
  } catch (_) {}
  await page.waitForTimeout(500);
  for (let i = 0; i < 20; i++) {
    for (const c of browser.contexts()) {
      for (const sw of c.serviceWorkers()) {
        if (sw.url().includes(extId)) {
          await page.close().catch(() => {});
          return sw;
        }
      }
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  await page.close().catch(() => {});
  return null;
}

async function swCall(sw, action, payload = {}) {
  return sw.evaluate(
    async ({ action, payload }) => {
      return await chrome.runtime.sendMessage({ action, ...payload });
    },
    { action, payload }
  );
}

/** Fallback: evaluate chrome.storage from an extension page */
async function storageViaPanel(browser, extId) {
  const ctx = browser.contexts()[0];
  const page = await ctx.newPage();
  await page.goto(`chrome-extension://${extId}/panel.html`, {
    waitUntil: "domcontentloaded",
    timeout: 10000
  });
  const data = await page.evaluate(
    () =>
      new Promise((resolve) => {
        chrome.storage.local.get(null, resolve);
      })
  );
  await page.close().catch(() => {});
  return data;
}

async function messageViaPanel(browser, extId, message) {
  const ctx = browser.contexts()[0];
  const page = await ctx.newPage();
  await page.goto(`chrome-extension://${extId}/panel.html`, {
    waitUntil: "domcontentloaded",
    timeout: 10000
  });
  const result = await page.evaluate(
    async (msg) => chrome.runtime.sendMessage(msg),
    message
  );
  await page.close().catch(() => {});
  return result;
}

async function withExt(fn) {
  const browser = await connect();
  try {
    let extId = await getExtensionId(browser);
    if (!extId) {
      // Wait a bit for SW registration after launch
      for (let i = 0; i < 15 && !extId; i++) {
        await new Promise((r) => setTimeout(r, 400));
        extId = await getExtensionId(browser);
      }
    }
    if (!extId) {
      throw new Error(
        "Extension ID not found. Is Farm Flow loaded? Re-run npm run launch after rebuilding."
      );
    }
    let sw = await ensureServiceWorker(browser, extId);
    return await fn({ browser, extId, sw });
  } finally {
    // Don't close browser — it's the user's lab window
    await browser.close().catch(() => {});
  }
}

async function callAgent(browser, extId, sw, action, payload = {}) {
  if (sw) {
    try {
      return await swCall(sw, action, payload);
    } catch (e) {
      // SW may be dead; fall through
    }
  }
  return messageViaPanel(browser, extId, { action, ...payload });
}

function findFlowPage(browser) {
  for (const ctx of browser.contexts()) {
    for (const page of ctx.pages()) {
      const u = page.url();
      if (u.includes("labs.google") || u.includes("flow.google.com")) return page;
    }
  }
  return null;
}

async function cmdStatus(args) {
  await withExt(async ({ browser, extId, sw }) => {
    const state = await callAgent(browser, extId, sw, "AGENT_GET_STATE");
    console.log(JSON.stringify({ extId, ...state }, null, 2));
  });
}

async function cmdLogs(args) {
  const n = Number(args._[1] || args.tail || 120);
  await withExt(async ({ browser, extId, sw }) => {
    const res = await callAgent(browser, extId, sw, "AGENT_GET_LOGS", {
      tail: n
    });
    console.log(res?.text || "(no logs)");
  });
}

async function cmdClearLogs() {
  await withExt(async ({ browser, extId, sw }) => {
    console.log(await callAgent(browser, extId, sw, "AGENT_CLEAR_LOGS"));
  });
}

async function cmdScrape() {
  await withExt(async ({ browser, extId, sw }) => {
    const res = await callAgent(browser, extId, sw, "AGENT_SCRAPE");
    fs.mkdirSync(OUT, { recursive: true });
    const file = path.join(OUT, `scrape-${Date.now()}.json`);
    fs.writeFileSync(file, JSON.stringify(res, null, 2));
    console.log(JSON.stringify(res, null, 2));
    console.log(`[lab] wrote ${file}`);
  });
}

async function cmdShot(args) {
  await withExt(async ({ browser }) => {
    const page = findFlowPage(browser);
    if (!page) throw new Error("No Flow tab open");
    fs.mkdirSync(OUT, { recursive: true });
    const file = path.resolve(args._[1] || path.join(OUT, `shot-${Date.now()}.png`));
    await page.screenshot({ path: file, fullPage: false });
    console.log(`[lab] screenshot → ${file}`);
  });
}

async function cmdEval(args) {
  const expr = args._.slice(1).join(" ");
  if (!expr) throw new Error('Usage: agent eval "document.title"');
  await withExt(async ({ browser }) => {
    const page = findFlowPage(browser);
    if (!page) throw new Error("No Flow tab open");
    const result = await page.evaluate((e) => {
      // eslint-disable-next-line no-eval
      return eval(e);
    }, expr);
    console.log(JSON.stringify(result, null, 2));
  });
}

function fileToDataUrl(filePath) {
  const abs = path.resolve(filePath);
  const buf = fs.readFileSync(abs);
  const ext = path.extname(abs).toLowerCase();
  const mime =
    ext === ".jpg" || ext === ".jpeg"
      ? "image/jpeg"
      : ext === ".webp"
        ? "image/webp"
        : "image/png";
  return `data:${mime};base64,${buf.toString("base64")}`;
}

async function cmdStart(args) {
  const prompt = args._.slice(1).join(" ").trim() || args.prompt;
  if (!prompt) throw new Error('Usage: agent start "make the suit pink" [--ref img.png]');
  await withExt(async ({ browser, extId, sw }) => {
    const payload = {
      prompts: [prompt],
      aspectRatio: args.aspect || "16:9",
      batchSize: args.batch || "x1",
      model: args.model || "Nano Banana 2",
      restDelay: args.rest || "3",
      iterations: Number(args.iterations || 1)
    };
    if (args.ref) {
      payload.refImage = fileToDataUrl(args.ref);
      await callAgent(browser, extId, sw, "AGENT_SET_REF", {
        refImage: payload.refImage
      });
    }
    const res = await callAgent(browser, extId, sw, "AGENT_START", payload);
    console.log(JSON.stringify(res, null, 2));
  });
}

async function cmdStop() {
  await withExt(async ({ browser, extId, sw }) => {
    console.log(await callAgent(browser, extId, sw, "AGENT_STOP"));
  });
}

async function cmdWatch(args) {
  const seconds = Number(args._[1] || 180);
  const end = Date.now() + seconds * 1000;
  let last = "";
  await withExt(async ({ browser, extId, sw }) => {
    while (Date.now() < end) {
      const res = await callAgent(browser, extId, sw, "AGENT_GET_LOGS", {
        tail: 40
      });
      const text = res?.text || "";
      if (text !== last) {
        const fresh = text.startsWith(last) ? text.slice(last.length) : text;
        process.stdout.write(fresh.endsWith("\n") ? fresh : fresh + "\n");
        last = text;
      }
      const state = await callAgent(browser, extId, sw, "AGENT_GET_STATE");
      if (state?.storage && !state.storage.isAutomating && last.includes("Queue finished")) {
        console.log("[lab] queue finished");
        break;
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
  });
}

async function cmdOpenPanel() {
  await withExt(async ({ browser, extId }) => {
    const ctx = browser.contexts()[0];
    const page = await ctx.newPage();
    await page.goto(`chrome-extension://${extId}/panel.html`, {
      waitUntil: "domcontentloaded"
    });
    console.log(`[lab] opened panel.html for ${extId} (keep this tab or use side panel)`);
  });
}

const args = parseArgs(process.argv.slice(2));
const cmd = args._[0] || "status";

const map = {
  status: cmdStatus,
  logs: cmdLogs,
  "clear-logs": cmdClearLogs,
  scrape: cmdScrape,
  shot: cmdShot,
  eval: cmdEval,
  start: cmdStart,
  stop: cmdStop,
  watch: cmdWatch,
  "open-panel": cmdOpenPanel
};

if (!map[cmd]) {
  console.error(`Unknown command: ${cmd}`);
  console.error(Object.keys(map).join(", "));
  process.exit(1);
}

map[cmd](args).catch((e) => {
  console.error("[agent]", e.message || e);
  process.exit(1);
});
