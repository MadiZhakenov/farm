// Farm Flow — content automation (CDP + DOM fallback, Brave-friendly)
console.log("Farm Flow: content script loaded on", location.href);

const UI = globalThis.FarmFlowUI;
if (!UI) {
  console.error("Farm Flow: flow-ui.js missing — reload extension");
}

const STORAGE_KEYS = {
  isAutomating: "flow_is_automating",
  isPaused: "flow_is_paused",
  promptsText: "flow_prompts_text",
  failedPromptsText: "flow_failed_prompts_text",
  aspectRatio: "flow_aspect_ratio",
  batchSize: "flow_batch_size",
  model: "flow_model",
  restDelay: "flow_rest_delay",
  refImage: "flow_ref_image",
  statsCompleted: "flow_stats_completed",
  statsFailed: "flow_stats_failed",
  lastError: "flow_last_error",
  jobIndex: "flow_job_index",
  jobIndexQueue: "flow_job_index_queue",
  genName: "flow_gen_name",
  workerId: "flow_worker_id",
  downloadSeq: "flow_download_seq"
};

/** Safe folder/file slug: fruits → fruits */
function sanitizeGenName(raw) {
  const s = String(raw || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 40);
  return s || "farm";
}

const PROMPT_SEP = "\n@@@FARM_NEXT@@@\n";

function parseQueueText(raw) {
  const text = String(raw || "");
  if (text.includes("@@@FARM_NEXT@@@")) {
    return text
      .split("@@@FARM_NEXT@@@")
      .map((b) => b.replace(/^\n+|\n+$/g, "").trim())
      .filter((b) => b.length > 0 && !b.startsWith("# ERR:"));
  }
  const blocks = text
    .split(/\n\s*\n/)
    .map((b) => b.trim())
    .filter((b) => b.length > 0 && !b.startsWith("# ERR:"));
  return blocks.length ? blocks : text.trim() ? [text.trim()] : [];
}

function serializeQueue(prompts) {
  return (prompts || []).join(PROMPT_SEP);
}

function quantityFromBatch(batch) {
  const m = String(batch || "x1").match(/(\d+)/);
  return Math.max(1, Math.min(4, parseInt(m?.[1] || "1", 10)));
}

function pad2(n) {
  return String(n).padStart(2, "0");
}

const REF_FILENAME = "farm-reference.png";

let isRunning = false;
let isPaused = false;
let refAttachedOnce = false;
let debuggerReady = false;
let settingsConfiguredOnce = false;

function isFlowPage() {
  const u = location.href;
  return u.includes("labs.google") || u.includes("flow.google.com");
}

function delay(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function breakableDelay(ms) {
  let elapsed = 0;
  const step = 400;
  while (elapsed < ms) {
    if (isRunning) {
      while (isPaused && isRunning) {
        await delay(400);
      }
      if (!isRunning) throw new Error("USER_STOPPED");
    }
    await delay(Math.min(step, ms - elapsed));
    elapsed += step;
  }
}

function reportError(msg) {
  console.error("Farm Flow:", msg);
  safeSendMessage({
    action: "AUTOMATION_PROGRESS",
    statusText: String(msg).slice(0, 80),
    lastError: String(msg)
  });
  safeSendMessage({
    action: "FLOW_LOG",
    text: String(msg),
    level: "err"
  });
  chrome.storage.local.set({ [STORAGE_KEYS.lastError]: String(msg) });
}

function flowLog(text, level = "info") {
  console.log("Farm Flow:", text);
  safeSendMessage({ action: "FLOW_LOG", text: String(text), level });
}

function describeEl(el) {
  if (!el) return "(null)";
  try {
    if (UI?.elementSummary) {
      const s = UI.elementSummary(el);
      const bits = [
        s.tag,
        s.aria ? `aria="${s.aria}"` : "",
        s.text ? `"${s.text.slice(0, 48)}"` : "",
        s.disabled ? "disabled" : "",
        s.checked ? `checked=${s.checked}` : "",
        s.rect ? `@${s.rect.left},${s.rect.top} ${s.rect.w}x${s.rect.h}` : ""
      ].filter(Boolean);
      return bits.join(" ");
    }
  } catch (_) {}
  const aria = el.getAttribute?.("aria-label") || "";
  const t = (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 40);
  return `${el.tagName}${aria ? `[${aria}]` : ""}${t ? ` "${t}"` : ""}`;
}

function safeSendMessage(message, callback) {
  try {
    chrome.runtime.sendMessage(message, (response) => {
      void chrome.runtime.lastError;
      if (callback) callback(response);
    });
  } catch (e) {
    console.warn("Farm Flow: sendMessage failed", e);
  }
}

function isVisible(el) {
  return UI ? UI.isVisible(el) : false;
}

/** Brave/Chrome: foreign extension iframes break debugger.attach */
function stripForeignExtensionFrames() {
  try {
    const own = chrome.runtime.getURL("");
    document
      .querySelectorAll(
        `iframe[src^="chrome-extension://"]:not([src^="${own}"]), frame[src^="chrome-extension://"]:not([src^="${own}"])`
      )
      .forEach((el) => el.remove());
  } catch (_) {}
}

function getElementByXpath(xpath, parent = document) {
  return document.evaluate(
    xpath,
    parent,
    null,
    XPathResult.FIRST_ORDERED_NODE_TYPE,
    null
  ).singleNodeValue;
}

async function findVisibleElement(xpath, timeout = 5000) {
  let elapsed = 0;
  while (elapsed < timeout) {
    if (!isRunning) throw new Error("USER_STOPPED");
    const snap = document.evaluate(
      xpath,
      document,
      null,
      XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
      null
    );
    for (let i = 0; i < snap.snapshotLength; i++) {
      const el = snap.snapshotItem(i);
      if (isVisible(el)) return el;
    }
    await breakableDelay(400);
    elapsed += 400;
  }
  throw new Error(`Timeout visible: ${xpath}`);
}

function attachDebugger() {
  return new Promise((resolve, reject) => {
    stripForeignExtensionFrames();
    chrome.runtime.sendMessage({ action: "ATTACH_DEBUGGER" }, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else if (response && !response.success) {
        reject(new Error(response.error || "Debugger attach failed"));
      } else resolve();
    });
  });
}

function detachDebugger() {
  return new Promise((resolve) => {
    debuggerReady = false;
    chrome.runtime.sendMessage({ action: "DETACH_DEBUGGER" }, () => resolve());
  });
}

function domClick(el, button = "left") {
  if (!el) return;
  el.scrollIntoView({ block: "center", inline: "nearest" });
  const r = el.getBoundingClientRect();
  const x = r.left + r.width / 2;
  const y = r.top + r.height / 2;
  const common = {
    bubbles: true,
    cancelable: true,
    view: window,
    clientX: x,
    clientY: y,
    button: button === "right" ? 2 : 0,
    buttons: button === "right" ? 2 : 1
  };
  el.dispatchEvent(new PointerEvent("pointerdown", { ...common, pointerId: 1, pointerType: "mouse" }));
  el.dispatchEvent(new MouseEvent("mousedown", common));
  el.dispatchEvent(new PointerEvent("pointerup", { ...common, pointerId: 1, pointerType: "mouse" }));
  el.dispatchEvent(new MouseEvent("mouseup", common));
  if (button === "right") {
    el.dispatchEvent(new MouseEvent("contextmenu", { ...common, button: 2 }));
  } else {
    el.dispatchEvent(new MouseEvent("click", common));
  }
}

async function cdpClickRaw(element, button = "left") {
  element.scrollIntoView({ behavior: "instant", block: "center" });
  await breakableDelay(200);
  const rect = element.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) {
    throw new Error("Target hidden / zero size");
  }
  const x = Math.round(rect.left + rect.width / 2);
  const y = Math.round(rect.top + rect.height / 2);
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ action: "CDP_CLICK", x, y, button }, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else if (response && !response.success) {
        reject(new Error(response.error || "CDP click failed"));
      } else resolve();
    });
  });
}

async function clickEl(element, button = "left") {
  if (!element) throw new Error("clickEl: no element");
  const rect = element.getBoundingClientRect?.() || { width: 0, height: 0 };
  if (rect.width < 2 || rect.height < 2) {
    flowLog(`click SKIP zero-size · ${describeEl(element)}`, "dbg");
    return;
  }
  if (isForbiddenClickTarget(element)) {
    flowLog(`click BLOCKED (forbidden) · ${describeEl(element)}`, "err");
    console.warn("Farm Flow: blocked click on forbidden target", element);
    return;
  }
  // Material / Angular buttons: prefer real DOM click (CDP often misses overlays)
  const aria = (element.getAttribute("aria-label") || "").toLowerCase();
  const preferDom =
    element.classList?.contains("mdc-button") ||
    element.classList?.contains("mdc-icon-button") ||
    element.classList?.contains("mat-mdc-button-base") ||
    element.classList?.contains("mat-button-toggle-button") ||
    element.classList?.contains("settings-trigger-button") ||
    element.classList?.contains("generate-icon-button") ||
    element.classList?.contains("add-menu-trigger") ||
    element.classList?.contains("asset-item") ||
    element.classList?.contains("detail-add-to-prompt-btn") ||
    element.getAttribute("role") === "radio" ||
    element.getAttribute("role") === "option" ||
    aria.includes("start generation") ||
    aria.includes("settings trigger") ||
    aria.includes("select model") ||
    aria.includes("add ingredients") ||
    aria.includes("settings");

  const mode = !preferDom && debuggerReady ? "CDP" : "DOM";
  flowLog(`click ${mode} → ${describeEl(element)}`, "dbg");

  if (!preferDom && debuggerReady) {
    try {
      await cdpClickRaw(element, button);
      return;
    } catch (e) {
      flowLog(`CDP click failed → DOM fallback: ${e.message}`, "dbg");
      console.warn("Farm Flow: CDP click failed, DOM fallback:", e.message);
    }
  }
  if (preferDom) {
    try {
      element.scrollIntoView({ block: "center", inline: "nearest" });
      element.click();
      return;
    } catch (_) {}
  }
  domClick(element, button);
}

async function cdpType(text) {
  if (!debuggerReady) return false;
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ action: "CDP_TYPE", text }, (response) => {
      void chrome.runtime.lastError;
      resolve(!!(response && response.success !== false));
    });
  });
}

async function cdpKey(key, opts = {}) {
  if (!debuggerReady) return false;
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(
      {
        action: "CDP_KEY",
        key,
        code: opts.code,
        keyCode: opts.keyCode,
        modifiers: opts.modifiers || 0
      },
      (response) => {
        void chrome.runtime.lastError;
        resolve(!!(response && response.success !== false));
      }
    );
  });
}

function editorPlainText(el) {
  if (UI?.editorPlainText) return UI.editorPlainText(el);
  if (!el) return "";
  return (el.innerText || el.textContent || "")
    .replace(/[\u200b\ufeff]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function promptLooksInserted(el, prompt) {
  const got = editorPlainText(el).replace(/\s+/g, " ").trim();
  if (!got) return false;
  const expect = String(prompt || "").replace(/\s+/g, " ").trim();
  if (!expect) return false;
  // Exact (normalized) match — includes() allowed "black coffeetea" to pass for "tea"
  if (got === expect) return true;
  // Allow trailing punctuation Flow sometimes adds, but not prefixed junk
  if (got.startsWith(expect) && got.length <= expect.length + 4) return true;
  return false;
}

/** Close settings popover / menus so ProseMirror can receive input. */
async function dismissFlowOverlays() {
  for (let i = 0; i < 6; i++) {
    if (!UI?.isSettingsOverlayOpen?.()) break;
    document.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Escape",
        code: "Escape",
        keyCode: 27,
        bubbles: true,
        cancelable: true
      })
    );
    await breakableDelay(220);
  }
  if (UI?.isSettingsOverlayOpen?.()) {
    const y = Math.max(80, Math.floor(window.innerHeight * 0.25));
    const x = Math.floor(window.innerWidth / 2);
    const hit = document.elementFromPoint(x, y);
    if (hit && !isForbiddenClickTarget(hit)) {
      try {
        hit.click();
      } catch (_) {}
    }
    await breakableDelay(300);
  }
}

function placeCaretInProseMirror(el) {
  if (!el) return;
  el.focus();
  try {
    const sel = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    sel.removeAllRanges();
    sel.addRange(range);
  } catch (_) {}
}

async function clearProseMirror(el) {
  if (!el) return;
  el.focus();
  await breakableDelay(80);
  for (let pass = 0; pass < 3; pass++) {
    placeCaretInProseMirror(el);
    try {
      document.execCommand("selectAll", false, null);
      document.execCommand("delete", false, null);
    } catch (_) {}
    if (debuggerReady) {
      await cdpKey("a", { code: "KeyA", keyCode: 65, modifiers: 2 });
      await breakableDelay(50);
      await cdpKey("Backspace", { code: "Backspace", keyCode: 8 });
      await breakableDelay(80);
    }
    if (!editorPlainText(el)) break;
  }
  if (editorPlainText(el)) {
    try {
      el.innerHTML = "<p><br></p>";
      el.dispatchEvent(
        new InputEvent("input", { bubbles: true, inputType: "deleteContentBackward" })
      );
    } catch (_) {}
  }
  placeCaretInProseMirror(el);
  await breakableDelay(100);
}

async function writeClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (_) {}
  if (!debuggerReady) return false;
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(
      { action: "WRITE_CLIPBOARD", text },
      (response) => {
        void chrome.runtime.lastError;
        resolve(!!(response && response.success));
      }
    );
  });
}

async function pasteViaClipboardCDP(el, text) {
  const ok = await writeClipboard(text);
  if (!ok) return false;
  placeCaretInProseMirror(el);
  await breakableDelay(120);
  if (debuggerReady) {
    await cdpKey("v", { code: "KeyV", keyCode: 86, modifiers: 2 }); // Ctrl+V
    await breakableDelay(500);
    return promptLooksInserted(el, text);
  }
  try {
    document.execCommand("paste");
  } catch (_) {}
  await breakableDelay(400);
  return promptLooksInserted(el, text);
}

async function injectTextRobust(text) {
  await dismissFlowOverlays();

  const element =
    (await waitForPromptEditor(8000)) || findPromptEditor();
  if (!element) {
    throw new Error(
      "Prompt editor not found — click «What do you want to create?», then retry"
    );
  }

  for (let i = 0; i < 8; i++) {
    if (!isRunning && i > 0) throw new Error("USER_STOPPED");
    console.log(`Farm Flow: inject attempt ${i + 1}/8`);

    await dismissFlowOverlays();
    if (UI?.isSettingsOverlayOpen?.()) {
      console.warn("Farm Flow: settings still open — cannot inject");
      await breakableDelay(400);
      continue;
    }

    element.scrollIntoView({ behavior: "instant", block: "end" });
    await breakableDelay(200);
    try {
      element.click();
    } catch (_) {}
    placeCaretInProseMirror(element);
    await breakableDelay(200);
    await clearProseMirror(element);
    await breakableDelay(150);
    const leftover = editorPlainText(element);
    if (leftover) {
      flowLog(`inject · editor not empty after clear: "${leftover.slice(0, 40)}"`, "dbg");
      await clearProseMirror(element);
      await breakableDelay(150);
    }

    // Strategy A: system clipboard + Ctrl+V (most reliable for ProseMirror)
    if (await pasteViaClipboardCDP(element, text)) {
      console.log("Farm Flow: inject OK via clipboard+Ctrl+V");
      return element;
    }

    // Strategy B: CDP insertText
    if (debuggerReady) {
      placeCaretInProseMirror(element);
      await breakableDelay(100);
      await cdpType(text);
      await breakableDelay(500);
      if (promptLooksInserted(element, text)) {
        console.log("Farm Flow: inject OK via CDP insertText");
        return element;
      }
    }

    // Strategy C: paste event
    placeCaretInProseMirror(element);
    const dt = new DataTransfer();
    dt.setData("text/plain", text);
    const pasteEv = new ClipboardEvent("paste", {
      bubbles: true,
      cancelable: true,
      composed: true
    });
    try {
      Object.defineProperty(pasteEv, "clipboardData", {
        value: dt,
        enumerable: true,
        configurable: true
      });
    } catch (_) {}
    element.dispatchEvent(pasteEv);
    await breakableDelay(400);
    if (promptLooksInserted(element, text)) {
      console.log("Farm Flow: inject OK via paste");
      return element;
    }

    // Strategy D: beforeinput + execCommand
    placeCaretInProseMirror(element);
    try {
      element.dispatchEvent(
        new InputEvent("beforeinput", {
          bubbles: true,
          cancelable: true,
          composed: true,
          inputType: "insertText",
          data: text
        })
      );
      document.execCommand("insertText", false, text);
    } catch (_) {}
    await breakableDelay(300);
    if (promptLooksInserted(element, text)) {
      console.log("Farm Flow: inject OK via execCommand");
      return element;
    }

    // Strategy E: chunked CDP
    if (debuggerReady) {
      await clearProseMirror(element);
      placeCaretInProseMirror(element);
      const chunk = 60;
      for (let p = 0; p < text.length; p += chunk) {
        await cdpType(text.slice(p, p + chunk));
        await breakableDelay(40);
      }
      await breakableDelay(400);
      if (promptLooksInserted(element, text)) {
        console.log("Farm Flow: inject OK via chunked CDP");
        return element;
      }
    }

    console.warn(
      "Farm Flow: inject attempt failed, editor plain=",
      editorPlainText(element).slice(0, 60)
    );
  }

  throw new Error(
    "Failed to insert prompt into Flow (ProseMirror rejected input). Close the settings popover, click the prompt box, then Start."
  );
}

function base64ToFile(dataUrl, filename = REF_FILENAME) {
  const arr = dataUrl.split(",");
  const mimeMatch = arr[0].match(/:(.*?);/);
  const mime = mimeMatch ? mimeMatch[1] : "image/png";
  const bstr = atob(arr[1]);
  const u8 = new Uint8Array(bstr.length);
  for (let i = 0; i < bstr.length; i++) u8[i] = bstr.charCodeAt(i);
  const ext = mime.includes("jpeg") || mime.includes("jpg") ? "jpg" : "png";
  const name =
    filename.endsWith(".png") || filename.endsWith(".jpg")
      ? filename
      : `farm-reference.${ext}`;
  return new File([u8], name, { type: mime });
}

function pasteImageIntoEditor(el, file) {
  const dt = new DataTransfer();
  dt.items.add(file);
  const ev = new ClipboardEvent("paste", {
    bubbles: true,
    cancelable: true,
    composed: true,
    clipboardData: dt
  });
  if (!ev.clipboardData) {
    try {
      Object.defineProperty(ev, "clipboardData", {
        value: dt,
        enumerable: true,
        configurable: true
      });
    } catch (_) {}
  }
  el.dispatchEvent(ev);
}

function queryAllDeep(selector, root = document) {
  return UI ? UI.queryAllDeep(selector, root) : [];
}

function findPromptEditor() {
  const el = UI ? UI.findPromptEditor() : null;
  if (el) {
    console.log(
      "Farm Flow: prompt field found",
      el.tagName,
      el.getAttribute?.("aria-label") || el.getAttribute?.("placeholder") || ""
    );
  } else {
    console.warn(
      "Farm Flow: no prompt field. editables=",
      queryAllDeep('[contenteditable="true"]').length
    );
  }
  return el;
}

async function prepareComposer() {
  const empty = UI?.findEmptyStateActivator?.();
  if (empty) {
    try {
      empty.click();
      await delay(400);
    } catch (_) {}
  }
  let editor = findPromptEditor();
  if (editor) {
    editor.scrollIntoView({ block: "end", inline: "nearest" });
    await delay(200);
    return editor;
  }
  const placeholder = Array.from(document.querySelectorAll("*")).find((n) => {
    if (!isVisible(n)) return false;
    const t = (n.textContent || "").trim().toLowerCase();
    return t.includes("what do you want to create");
  });
  if (placeholder) {
    try {
      placeholder.click();
      await delay(500);
    } catch (_) {}
  }
  editor = findPromptEditor();
  if (editor) {
    editor.focus();
    await clickEl(editor);
  }
  return editor;
}

async function waitForPromptEditor(timeoutMs = 12000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (!isRunning && timeoutMs > 3000) {
      /* allow pre-start wait without isRunning */
    }
    const el = findPromptEditor();
    if (el) return el;
    if (Date.now() - start > 1200) {
      await prepareComposer();
    }
    await delay(400);
  }
  return null;
}

function isForbiddenClickTarget(el) {
  return UI ? UI.isForbiddenClickTarget(el) : true;
}

function findSubmitButton(nearEditor = null) {
  return UI ? UI.findSubmitButton(nearEditor || findPromptEditor()) : null;
}

function submitViaEnter(el) {
  if (!el) return;
  el.focus();
  for (const type of ["keydown", "keypress", "keyup"]) {
    el.dispatchEvent(
      new KeyboardEvent(type, {
        key: "Enter",
        code: "Enter",
        keyCode: 13,
        which: 13,
        bubbles: true,
        cancelable: true
      })
    );
  }
}

async function clickPlusButton() {
  const btn = UI?.findAddImageButton?.(findPromptEditor());
  if (btn) {
    await clickEl(btn);
    return true;
  }
  return false;
}

async function clickExistingReference() {
  const names = [REF_FILENAME, "farm-reference.jpg", "reference.png"];
  const matches = Array.from(document.querySelectorAll("div, span, p, button")).filter(
    (el) => {
      if (!isVisible(el)) return false;
      return names.includes((el.textContent || "").trim());
    }
  );
  if (!matches.length) return false;
  const target = matches[matches.length - 1];
  const clickable =
    target.closest('button, [role="menuitem"], li, [role="button"]') || target;
  await clickEl(clickable);
  return true;
}

async function waitUploadSettle() {
  for (let i = 0; i < 50; i++) {
    if (!isRunning) throw new Error("USER_STOPPED");
    let spinner = false;
    for (const s of document.querySelectorAll('[role="progressbar"]')) {
      if (isVisible(s)) spinner = true;
    }
    const submit = findSubmitButton();
    const disabled =
      submit &&
      (submit.disabled || submit.getAttribute("aria-disabled") === "true");
    if (!spinner && submit && !disabled) break;
    if (!spinner && i > 16) break;
    await breakableDelay(400);
  }
  await breakableDelay(1000);
}

async function attachReference(refDataUrl) {
  if (!refDataUrl) return;
  const editor = findPromptEditor() || (await prepareComposer());
  if (!editor) throw new Error("Prompt editor not found for reference");

  const file = base64ToFile(refDataUrl);
  const before = countComposerReferenceImgs(editor);
  flowLog(`ref · start · chipsBefore=${before} · file=${file.name} ${Math.round(file.size / 1024)}KB type=${file.type}`);

  editor.focus();
  await clickEl(editor);
  await breakableDelay(150);
  placeCaretInProseMirror(editor);

  // Prefer existing uploaded asset when present (most reliable on Agent UI)
  flowLog("ref · try existing asset farm-reference.png first", "dbg");
  if (await attachViaExistingAssetChip()) {
    await waitUploadSettle();
    if (composerHasReferenceAttachment(editor, before)) {
      refAttachedOnce = true;
      flowLog(`ref · confirmed via asset · chips=${countComposerReferenceImgs(editor)}`, "ok");
      return;
    }
    flowLog("ref · asset path ran but chip not detected yet — continue", "dbg");
  } else {
    // Close picker if still open from failed lookup
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
    );
    await breakableDelay(250);
  }

  // Fresh upload via Add → Upload media (+ Rights I agree) + CDP file input
  if (!composerHasReferenceAttachment(editor, before)) {
    flowLog("ref · try Upload media", "dbg");
    const uploaded = await attachViaUploadMedia(file, refDataUrl);
    if (uploaded) {
      await waitUploadSettle();
      // After upload, pick the new farm-reference asset into the prompt
      if (await attachViaExistingAssetChip()) {
        await waitUploadSettle();
        if (composerHasReferenceAttachment(editor, before)) {
          refAttachedOnce = true;
          flowLog(
            `ref · confirmed via upload+asset · chips=${countComposerReferenceImgs(editor)}`,
            "ok"
          );
          return;
        }
      }
    }
  }

  // Strategy: ClipboardItem PNG + Ctrl+V
  flowLog("ref · try clipboard image/png + Ctrl+V", "dbg");
  if (await pasteImageViaSystemClipboard(editor, file)) {
    flowLog("ref · clipboard write+paste dispatched", "dbg");
  }

  // Strategy: paste event with File
  if (!composerHasReferenceAttachment(editor, before)) {
    flowLog("ref · try paste File event", "dbg");
    placeCaretInProseMirror(editor);
    pasteImageIntoEditor(editor, file);
    await breakableDelay(600);
  }

  // Strategy: drag-drop onto editor / composer band
  if (!composerHasReferenceAttachment(editor, before)) {
    flowLog("ref · try drag-drop on composer band", "dbg");
    const band = findComposerBandRoot(editor);
    dropFileOnElement(band || editor, file);
    await breakableDelay(600);
  }

  // Strategy: hidden input[type=file] ONLY if already in DOM — never open Add menu
  if (!composerHasReferenceAttachment(editor, before)) {
    const existingInput = document.querySelector('input[type="file"]');
    if (existingInput) {
      flowLog("ref · try existing file input (no Add menu)", "dbg");
      await attachViaFileInput(file, { openAddMenu: false });
    } else {
      flowLog("ref · skip file-input (would open Search assets)", "dbg");
    }
  }

  await waitUploadSettle();

  for (let i = 0; i < 25; i++) {
    if (composerHasReferenceAttachment(editor, before)) break;
    await breakableDelay(400);
  }

  if (!composerHasReferenceAttachment(editor, before)) {
    placeCaretInProseMirror(editor);
    flowLog("ref · final clipboard retry", "dbg");
    await pasteImageViaSystemClipboard(editor, file);
    await waitUploadSettle();
    await breakableDelay(800);
  }

  const after = countComposerReferenceImgs(editor);
  const ok = composerHasReferenceAttachment(editor, before);
  flowLog(`ref · chipsAfter=${after} (before=${before}) ok=${ok}`);
  if (!ok) {
    throw new Error(
      "Reference did not stick in the prompt box (upload may have gone to assets only). Try again."
    );
  }
  refAttachedOnce = true;
  flowLog("ref · confirmed in composer", "ok");
}

async function acceptRightsDialogIfPresent() {
  for (let round = 0; round < 4; round++) {
    const agree = Array.from(document.querySelectorAll("button")).find((b) => {
      if (!isVisible(b)) return false;
      const t = (b.textContent || "").replace(/\s+/g, " ").trim();
      return /^i agree$/i.test(t);
    });
    if (!agree) return round > 0;
    flowLog("ref · Rights dialog → I agree", "dbg");
    await clickEl(agree);
    await breakableDelay(500);
  }
  return true;
}

async function materializeRefPath(dataUrl) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(
      { action: "MATERIALIZE_REF_FILE", dataUrl },
      (res) => {
        void chrome.runtime.lastError;
        resolve(res || { success: false });
      }
    );
  });
}

async function cdpSetFileInput(path, selector = 'input[type="file"]') {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(
      { action: "CDP_SET_FILE_INPUT", path, selector },
      (res) => {
        void chrome.runtime.lastError;
        resolve(res || { success: false });
      }
    );
  });
}

async function attachViaUploadMedia(file, dataUrl) {
  const add = UI?.findAddImageButton?.();
  if (!add) return false;

  const pickerOpen = !!document.querySelector(
    ".cdk-overlay-pane button.detail-add-to-prompt-btn, .cdk-overlay-pane .asset-item, .cdk-overlay-pane button"
  );
  if (!pickerOpen) {
    await clickEl(add);
    await breakableDelay(700);
  }
  await acceptRightsDialogIfPresent();

  const uploadBtn = Array.from(document.querySelectorAll("button")).find((b) => {
    if (!isVisible(b)) return false;
    const t = (b.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
    return t.includes("upload media") || t === "upload";
  });
  if (!uploadBtn) {
    flowLog("ref · Upload media button missing", "dbg");
    return false;
  }

  flowLog(`ref · Upload media · ${describeEl(uploadBtn)}`, "dbg");
  flowLog(`ref · debuggerReady=${debuggerReady} dataUrl=${dataUrl ? dataUrl.slice(0, 30) : "none"}`, "dbg");

  // Arm CDP file-chooser intercept BEFORE clicking Upload
  let armed = false;
  if (dataUrl && debuggerReady) {
    const arm = await new Promise((resolve) => {
      chrome.runtime.sendMessage(
        { action: "CDP_ARM_FILE_UPLOAD", dataUrl },
        (res) => {
          void chrome.runtime.lastError;
          resolve(res || { success: false });
        }
      );
    });
    if (arm?.success) {
      armed = true;
      flowLog(`ref · chooser armed · ${arm.path}`, "ok");
    } else {
      flowLog(`ref · chooser arm failed: ${arm?.error || "?"}`, "dbg");
    }
  }

  await clickEl(uploadBtn);
  await breakableDelay(300);
  await acceptRightsDialogIfPresent();

  if (armed) {
    const waited = await new Promise((resolve) => {
      chrome.runtime.sendMessage(
        { action: "CDP_AWAIT_FILE_UPLOAD", timeoutMs: 14000 },
        (res) => {
          void chrome.runtime.lastError;
          resolve(res || { success: false });
        }
      );
    });
    if (waited?.success) {
      flowLog("ref · file chooser uploaded", "ok");
      await breakableDelay(1500);
      await acceptRightsDialogIfPresent();
      return true;
    }
    flowLog(`ref · file chooser await: ${waited?.error || "?"}`, "dbg");
  }

  // Fallback: DataTransfer on any file input that appeared
  let input = document.querySelector('input[type="file"]');
  for (let i = 0; i < 8 && !input; i++) {
    await breakableDelay(200);
    input = document.querySelector('input[type="file"]');
  }
  if (input) {
    flowLog("ref · DataTransfer onto file input", "dbg");
    try {
      const dt = new DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      await breakableDelay(1200);
      await acceptRightsDialogIfPresent();
      return true;
    } catch (e) {
      flowLog(`ref · DataTransfer failed: ${e.message}`, "dbg");
    }
  }

  return false;
}

async function findAssetRowByNames(names) {
  return Array.from(
    document.querySelectorAll(
      "button.asset-item, button[role='option'].asset-item, button[role='option'], .cdk-overlay-pane button"
    )
  ).find((el) => {
    if (!isVisible(el)) return false;
    if (el.tagName === "CDK-VIRTUAL-SCROLL-VIEWPORT") return false;
    const r = el.getBoundingClientRect();
    if (r.height > 120 || r.width < 40) return false;
    const t = (el.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
    if (!t || t.includes("upload media") || t === "add to prompt") return false;
    return names.some((n) => t.includes(String(n).toLowerCase()));
  });
}

/** Pick farm-reference from assets and Add to prompt — closes the panel after. */
async function attachViaExistingAssetChip() {
  const add = UI?.findAddImageButton?.();
  if (!add) {
    flowLog("ref · no Add ingredients button", "dbg");
    return false;
  }
  await clickEl(add);
  await breakableDelay(800);
  await acceptRightsDialogIfPresent();

  const names = ["farm-reference.png", "farm-reference.jpg", "farm-reference", REF_FILENAME];
  let asset = await findAssetRowByNames(names);

  if (!asset) {
    flowLog("ref · asset row farm-reference not found", "dbg");
    return false;
  }

  flowLog(`ref · select asset · ${describeEl(asset)}`, "dbg");
  await clickEl(asset);
  await breakableDelay(400);
  await acceptRightsDialogIfPresent();

  // Detail pane / Add to prompt can take a moment — poll
  let addToPrompt = null;
  for (let i = 0; i < 15; i++) {
    addToPrompt =
      document.querySelector("button.detail-add-to-prompt-btn") ||
      Array.from(document.querySelectorAll(".cdk-overlay-pane button, button")).find((b) => {
        if (!isVisible(b)) return false;
        const t = (b.textContent || "").replace(/\s+/g, " ").trim();
        return /^add to prompt$/i.test(t);
      }) ||
      null;
    if (addToPrompt) break;
    if (i === 4) {
      flowLog("ref · re-click asset to open detail", "dbg");
      await clickEl(asset);
    }
    await breakableDelay(250);
  }

  if (!addToPrompt) {
    flowLog("ref · Add to prompt missing — try dblclick asset", "dbg");
    try {
      asset.dispatchEvent(
        new MouseEvent("dblclick", { bubbles: true, cancelable: true, view: window })
      );
      await breakableDelay(800);
    } catch (_) {}
    await acceptRightsDialogIfPresent();
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
    );
    await breakableDelay(300);
    return composerHasReferenceAttachment(findPromptEditor(), 0);
  }

  flowLog(`ref · Add to prompt · ${describeEl(addToPrompt)}`, "dbg");
  await clickEl(addToPrompt);
  await breakableDelay(600);
  await acceptRightsDialogIfPresent();
  await breakableDelay(600);
  flowLog("ref · clicked Add to prompt", "ok");

  for (let i = 0; i < 3; i++) {
    const stillOpen = document.querySelector(
      ".cdk-overlay-pane .detail-add-to-prompt-btn, .cdk-overlay-pane .asset-item"
    );
    if (!stillOpen || !isVisible(stillOpen)) break;
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
    );
    await breakableDelay(250);
  }
  return true;
}

async function ensurePngBlob(file) {
  const type = (file.type || "").toLowerCase();
  if (type === "image/png" || type === "") {
    if (type === "image/png") return file instanceof Blob ? file : new Blob([await file.arrayBuffer()], { type: "image/png" });
  }
  // Chrome clipboard write often rejects image/jpeg — convert via canvas
  try {
    const buf = await file.arrayBuffer();
    const blob = new Blob([buf], { type: file.type || "image/jpeg" });
    const url = URL.createObjectURL(blob);
    const img = await new Promise((resolve, reject) => {
      const im = new Image();
      im.onload = () => resolve(im);
      im.onerror = reject;
      im.src = url;
    });
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth || img.width;
    canvas.height = img.naturalHeight || img.height;
    canvas.getContext("2d").drawImage(img, 0, 0);
    URL.revokeObjectURL(url);
    const png = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    if (png) return png;
  } catch (e) {
    flowLog(`ref · png convert failed: ${e.message}`, "dbg");
  }
  return new Blob([await file.arrayBuffer()], { type: "image/png" });
}

async function pasteImageViaSystemClipboard(el, file) {
  try {
    if (!navigator.clipboard || !window.ClipboardItem) {
      flowLog("ref · ClipboardItem unavailable", "dbg");
      return false;
    }
    const pngBlob = await ensurePngBlob(file);
    await navigator.clipboard.write([
      new ClipboardItem({ "image/png": pngBlob })
    ]);
    flowLog("ref · clipboard wrote image/png", "dbg");
    placeCaretInProseMirror(el);
    await breakableDelay(120);
    if (debuggerReady) {
      await cdpKey("v", { code: "KeyV", keyCode: 86, modifiers: 2 });
    } else {
      try {
        document.execCommand("paste");
      } catch (_) {}
    }
    await breakableDelay(700);
    return true;
  } catch (e) {
    flowLog(`ref · clipboard image failed: ${e.message}`, "dbg");
    return false;
  }
}

function dropFileOnElement(el, file) {
  if (!el) return;
  const dt = new DataTransfer();
  dt.items.add(file);
  for (const type of ["dragenter", "dragover", "drop"]) {
    try {
      el.dispatchEvent(
        new DragEvent(type, {
          bubbles: true,
          cancelable: true,
          composed: true,
          dataTransfer: dt
        })
      );
    } catch (_) {}
  }
}

async function attachViaFileInput(file, opts = {}) {
  const openAddMenu = opts.openAddMenu === true;
  const inputs = Array.from(document.querySelectorAll('input[type="file"]'));
  let input =
    inputs.find((inp) => {
      const accept = (inp.getAttribute("accept") || "").toLowerCase();
      return !accept || accept.includes("image") || accept.includes("*/*");
    }) || inputs[0];

  if (!input && openAddMenu) {
    const add = UI?.findAddImageButton?.();
    if (add) {
      await clickEl(add);
      await breakableDelay(500);
      input = document.querySelector('input[type="file"]');
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
      );
      await breakableDelay(200);
    }
  }
  if (!input) return false;
  try {
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    await breakableDelay(800);
    return true;
  } catch (e) {
    flowLog(`ref · file input failed: ${e.message}`, "dbg");
    return false;
  }
}

/** Composer strip that holds add + editor + generate (excludes gallery). */
function findComposerBandRoot(editor) {
  const ed = editor || findPromptEditor();
  if (!ed) return null;
  const add = UI?.findAddImageButton?.();
  const gen = UI?.findSubmitButton?.();
  let node = ed.parentElement;
  for (let i = 0; i < 12 && node; i++) {
    const okEd = node.contains(ed);
    const okAdd = !add || node.contains(add);
    const okGen = !gen || node.contains(gen);
    if (okEd && okAdd && okGen) return node;
    node = node.parentElement;
  }
  return ed.parentElement || ed;
}

/** Count ingredient thumbs near the prompt / generate controls (not gallery). */
function countComposerReferenceImgs(editor) {
  const ed = editor || findPromptEditor();
  const gen = findSubmitButton(ed);
  const add = UI?.findAddImageButton?.();
  const seen = new Set();
  let n = 0;

  const consider = (img) => {
    if (!img || seen.has(img) || !isVisible(img)) return;
    seen.add(img);
    const r = img.getBoundingClientRect();
    if (r.width < 16 || r.height < 16) return;
    if (r.width > 260 || r.height > 260) return;
    // Must be in lower half (composer), not gallery tiles
    if (r.top < window.innerHeight * 0.45) return;
    if (
      img.closest(
        "button.generate-icon-button, button.add-menu-trigger, button.agent-action-button, button.settings-trigger-button, .mdc-icon-button"
      )
    ) {
      return;
    }
    // Gallery tiles are large; ingredient chips are roughly square ~32–120
    const ratio = r.width / Math.max(r.height, 1);
    if (ratio < 0.5 || ratio > 2.2) return;
    n += 1;
  };

  // 1) Walk up from editor — chips are usually siblings in the same composer card
  if (ed) {
    let node = ed;
    for (let i = 0; i < 10 && node; i++) {
      node.querySelectorAll?.("img").forEach(consider);
      node = node.parentElement;
    }
  }

  // 2) Band around add / editor / send
  const anchors = [ed, gen, add].filter(Boolean);
  if (anchors.length) {
    let top = Infinity;
    let bottom = 0;
    let left = Infinity;
    let right = 0;
    for (const a of anchors) {
      const r = a.getBoundingClientRect();
      top = Math.min(top, r.top);
      bottom = Math.max(bottom, r.bottom);
      left = Math.min(left, r.left);
      right = Math.max(right, r.right);
    }
    top = Math.max(0, top - 120);
    bottom = Math.min(window.innerHeight, bottom + 60);
    left = Math.max(0, left - 80);
    right = Math.min(window.innerWidth, right + 80);
    for (const img of document.querySelectorAll("img")) {
      const r = img.getBoundingClientRect();
      if (r.bottom < top || r.top > bottom || r.right < left || r.left > right) continue;
      consider(img);
    }
  }

  return n;
}

function composerHasReferenceAttachment(editor, beforeCount = 0) {
  const now = countComposerReferenceImgs(editor);
  flowLog(`ref · chipScan count=${now} (need>${beforeCount})`, "dbg");
  if (now > beforeCount) return true;
  const ed = editor || findPromptEditor();
  if (!ed) return false;
  // Any img inside the closest card that also contains the generate button
  const gen = findSubmitButton(ed);
  let root = ed.parentElement;
  for (let i = 0; i < 12 && root; i++) {
    if (gen && root.contains(gen)) {
      const imgs = Array.from(root.querySelectorAll("img")).filter((img) => {
        if (!isVisible(img)) return false;
        const r = img.getBoundingClientRect();
        return r.width >= 20 && r.width <= 200 && r.height >= 20 && r.height <= 200;
      });
      if (imgs.length > beforeCount) {
        flowLog(`ref · chipScan via composer-card imgs=${imgs.length}`, "dbg");
        return true;
      }
      break;
    }
    root = root.parentElement;
  }
  return false;
}

/** Apply aspect / quantity / model via Settings trigger popover (cdk-overlay). No Save.
 *  Used when the live UI exposes the 🍌 chip / popover (Plus OR free+narrow). */
async function applyComposerSettings(settings, opts = {}) {
  const allowHandOff = opts.allowHandOff !== false;
  const wantAspect = settings.aspectRatio || "1:1";
  const wantQty =
    settings.batchSize === "1x" ? "x1" : settings.batchSize || "x1";
  const wantModel = settings.model || "Nano Banana 2";

  let overlay = UI?.findSettingsOverlay?.() || null;

  if (!overlay) {
    const chip =
      UI?.findVisiblePlusSettingsChip?.() ||
      (UI?.findComposerSettingsTrigger?.() &&
      isVisible(UI.findComposerSettingsTrigger())
        ? UI.findComposerSettingsTrigger()
        : null);
    if (!chip) {
      safeSendMessage({
        action: "AUTOMATION_PROGRESS",
        lastError: "Settings trigger not found (🍌 chip / popover)."
      });
      return;
    }

    // Already correct on chip? skip open
    const pre = UI.settingsChipMatches?.(settings);
    if (pre?.aspectOk && pre?.qtyOk && pre?.modelOk) {
      console.log("Farm Flow: settings already on chip", pre.chipText);
      return;
    }

    console.log("Farm Flow: opening settings popover", UI.elementSummary(chip));
    await clickEl(chip);
    await breakableDelay(700);

    for (let i = 0; i < 20; i++) {
      overlay = UI.findSettingsOverlay?.();
      if (overlay) break;
      // Layout switched to Agent panel after click (responsive)
      if (allowHandOff && UI.findAgentSettingsPanel?.()) {
        console.log("Farm Flow: click opened Agent panel instead of popover — hand off");
        await configureAgentSettingsFree(settings, { allowHandOff: false });
        return;
      }
      await breakableDelay(150);
    }
  }

  if (!overlay) {
    safeSendMessage({
      action: "AUTOMATION_PROGRESS",
      lastError: "Settings popover did not open after clicking 🍌 chip."
    });
    return;
  }

  async function clickRadio(needle, kind, exact) {
    const btn = UI.findOverlayRadio?.(overlay, needle, { exact: !!exact });
    if (!btn) {
      console.warn(`Farm Flow: no ${kind} for`, needle);
      return false;
    }
    if (btn.getAttribute("aria-checked") === "true") {
      console.log(`Farm Flow: ${kind} already`, needle);
      return true;
    }
    console.log(`Farm Flow: click ${kind}`, needle, UI.elementSummary(btn));
    await clickEl(btn);
    await breakableDelay(350);
    return true;
  }

  // Stay on Image (not Video)
  await clickRadio("image", "mode");

  const aspectOk = await clickRadio(wantAspect, "aspect");
  const qtyOk = await clickRadio(wantQty, "quantity", true);

  // Model family dropdown
  let modelOk = false;
  try {
    const modelBtn = UI.findModelFamilyButton?.(overlay);
    if (modelBtn) {
      const cur = (modelBtn.textContent || "").replace(/\s+/g, " ");
      if (cur.includes(wantModel)) {
        modelOk = true;
        console.log("Farm Flow: model already", wantModel);
      } else {
        await clickEl(modelBtn);
        await breakableDelay(600);
        const opt = UI.findModelMenuOption?.(wantModel);
        if (opt) {
          console.log("Farm Flow: pick model", UI.elementSummary(opt));
          await clickEl(opt);
          await breakableDelay(400);
          modelOk = true;
        } else {
          console.warn("Farm Flow: model option not found", wantModel);
          document.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
          );
          await breakableDelay(200);
        }
      }
    }
  } catch (e) {
    console.warn("Farm Flow: model select failed", e.message);
  }

  // Close popover — must be gone before prompt inject
  await dismissFlowOverlays();
  if (UI?.isSettingsOverlayOpen?.()) {
    const chip2 =
      UI.findVisiblePlusSettingsChip?.() ||
      (UI.findComposerSettingsTrigger?.() &&
      isVisible(UI.findComposerSettingsTrigger())
        ? UI.findComposerSettingsTrigger()
        : null);
    if (chip2) {
      await clickEl(chip2);
      await breakableDelay(400);
    }
    await dismissFlowOverlays();
  }

  const post = UI.settingsChipMatches?.(settings);
  console.log("Farm Flow: settings after", post);

  const fails = [];
  if (!aspectOk || !post?.aspectOk) fails.push(`aspect ${wantAspect}`);
  if (!qtyOk || !post?.qtyOk) fails.push(`quantity ${wantQty}`);
  if (!modelOk || !post?.modelOk) fails.push(`model ${wantModel}`);

  if (fails.length) {
    safeSendMessage({
      action: "AUTOMATION_PROGRESS",
      lastError: `Settings not applied: ${fails.join(", ")}. Chip now: ${post?.chipText || "?"}`
    });
  } else {
    safeSendMessage({
      action: "AUTOMATION_PROGRESS",
      statusText: `Settings OK · ${post.chipText}`,
      lastError: ""
    });
  }
}

/**
 * FREE wide / Agent mode: Agent settings side panel (flow-agent-panel).
 * Never + Image aspect/qty/model + Save. Does not touch Video defaults.
 * If tune somehow opens a popover (responsive), hands off to popover path.
 */
async function configureAgentSettingsFree(settings, opts = {}) {
  const allowHandOff = opts.allowHandOff !== false;
  const wantAspect = settings.aspectRatio || "1:1";
  const wantQty =
    settings.batchSize === "1x" ? "x1" : settings.batchSize || "x1";
  const wantModel = settings.model || "Nano Banana 2";

  let panel = UI?.findAgentSettingsPanel?.();
  if (!panel) {
    const tune = UI?.findAgentTuneButton?.();
    if (!tune) {
      throw new Error("Agent Settings: tune button not found");
    }
    console.log("Farm Flow: opening Agent settings via tune", UI.elementSummary(tune));
    await clickEl(tune);
    await breakableDelay(900);
    for (let i = 0; i < 25; i++) {
      panel = UI.findAgentSettingsPanel?.();
      if (panel) break;
      // Narrow layout may open popover from the same gesture / alternate control
      if (allowHandOff && UI.findSettingsOverlay?.()) {
        console.log("Farm Flow: tune path opened popover — hand off");
        await applyComposerSettings(settings, { allowHandOff: false });
        return;
      }
      await breakableDelay(150);
    }
  }
  if (!panel) {
    throw new Error("Agent settings panel (flow-agent-panel) did not open");
  }

  // Confirmation → Never (Always is often default on free)
  const neverEl = UI.findAgentNeverRadio?.(panel);
  if (neverEl) {
    const already =
      neverEl.classList?.contains("mat-mdc-radio-checked") ||
      !!neverEl.querySelector?.(".mat-mdc-radio-checked") ||
      neverEl.getAttribute?.("aria-checked") === "true";
    if (!already) {
      console.log("Farm Flow: selecting Confirmation = Never");
      const clickTarget =
        neverEl.querySelector?.("label, input, .mdc-radio") || neverEl;
      await clickEl(clickTarget);
      await breakableDelay(350);
    } else {
      console.log("Farm Flow: Never already selected");
    }
  } else {
    console.warn("Farm Flow: Never radio not found in Agent settings");
  }

  async function clickImageRadio(kind, needle, exact) {
    const btn = UI.findAgentImageRadio?.(kind, needle, { exact: !!exact });
    if (!btn) {
      console.warn(`Farm Flow: agent image ${kind} missing`, needle);
      return false;
    }
    if (btn.getAttribute("aria-checked") === "true") {
      console.log(`Farm Flow: agent ${kind} already`, needle);
      return true;
    }
    console.log(`Farm Flow: agent click ${kind}`, needle, UI.elementSummary(btn));
    await clickEl(btn);
    await breakableDelay(300);
    return true;
  }

  const aspectOk = await clickImageRadio("aspect", wantAspect, false);
  const qtyOk = await clickImageRadio("quantity", wantQty, true);

  let modelOk = false;
  try {
    const modelBtn = UI.findAgentImageModelButton?.(panel);
    if (modelBtn) {
      const cur = (modelBtn.textContent || "").replace(/\s+/g, " ");
      if (cur.includes(wantModel)) {
        modelOk = true;
        console.log("Farm Flow: agent model already", wantModel);
      } else {
        await clickEl(modelBtn);
        await breakableDelay(600);
        const opt = UI.findModelMenuOption?.(wantModel);
        if (opt) {
          console.log("Farm Flow: agent pick model", UI.elementSummary(opt));
          await clickEl(opt);
          await breakableDelay(400);
          modelOk = true;
        } else {
          console.warn("Farm Flow: agent model option not found", wantModel);
          document.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
          );
          await breakableDelay(200);
        }
      }
    }
  } catch (e) {
    console.warn("Farm Flow: agent model select failed", e.message);
  }

  // Save often sits below the fold inside .settings-content on short AdsPower windows
  const scrolled = panel.querySelector?.(".settings-content") || panel;
  try {
    scrolled.scrollTop = scrolled.scrollHeight;
    panel.scrollTop = panel.scrollHeight;
  } catch (_) {}
  await breakableDelay(250);

  let saveBtn = UI.findAgentSaveButton?.(panel);
  if (saveBtn) {
    try {
      saveBtn.scrollIntoView({ block: "center", inline: "nearest" });
    } catch (_) {}
    await breakableDelay(200);
    console.log("Farm Flow: clicking Save on Agent settings");
    await clickEl(saveBtn);
    await breakableDelay(900);
  } else {
    console.warn("Farm Flow: Agent Save not found — applying without Save, closing panel");
    safeSendMessage({
      action: "AUTOMATION_PROGRESS",
      lastError:
        "Agent Save not visible (scroll/viewport). Never/aspect may still be applied — check once."
    });
  }

  // Panel should close after Save; never click Back — Flow Back can leave /project/
  if (UI.isAgentSettingsOpen?.()) {
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
    );
    await breakableDelay(400);
    if (UI.isAgentSettingsOpen?.()) {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
      );
      await breakableDelay(300);
    }
  }

  const fails = [];
  if (!aspectOk) fails.push(`aspect ${wantAspect}`);
  if (!qtyOk) fails.push(`quantity ${wantQty}`);
  if (!modelOk) fails.push(`model ${wantModel}`);
  if (!saveBtn) fails.push("Save");

  if (fails.length) {
    safeSendMessage({
      action: "AUTOMATION_PROGRESS",
      lastError: `Agent settings partial: ${fails.join(", ")}`
    });
  } else {
    safeSendMessage({
      action: "AUTOMATION_PROGRESS",
      statusText: `Agent settings OK · ${wantAspect} · ${wantQty} · ${wantModel}`,
      lastError: ""
    });
  }
}

/** @deprecated name kept — forwards to configureAgentSettingsFree */
async function configureSettings(settings) {
  return configureAgentSettingsFree(settings);
}

/**
 * Probe which settings UI actually opens (popover vs agent panel), then apply.
 * Adapts to: Plus, free+narrow (popover), free+wide (agent panel).
 */
async function probeSettingsSurface() {
  const snap = UI?.inspectSettingsSurface?.() || { preferred: "unknown" };
  flowLog(
    `probe · inspect ${JSON.stringify(snap)}`,
    "dbg"
  );

  if (UI?.isAgentSettingsOpen?.()) {
    flowLog("probe · agent-panel already open", "ok");
    return "agent-panel";
  }
  if (UI?.isSettingsOverlayOpen?.()) {
    flowLog("probe · popover already open", "ok");
    return "popover";
  }

  const tryOpenPopover = async () => {
    const chip =
      UI.findVisiblePlusSettingsChip?.() ||
      (UI.findComposerSettingsTrigger?.() &&
      isVisible(UI.findComposerSettingsTrigger())
        ? UI.findComposerSettingsTrigger()
        : null);
    if (!chip) {
      flowLog("probe · no visible 🍌 chip", "dbg");
      return null;
    }
    flowLog("probe · open popover via chip…", "dbg");
    await clickEl(chip);
    await breakableDelay(800);
    if (UI.findSettingsOverlay?.()) {
      flowLog("probe · opened popover", "ok");
      return "popover";
    }
    if (UI.findAgentSettingsPanel?.()) {
      flowLog("probe · chip opened agent-panel instead", "ok");
      return "agent-panel";
    }
    flowLog("probe · chip click opened nothing", "dbg");
    await dismissFlowOverlays();
    return null;
  };

  const tryOpenAgent = async () => {
    const tune = UI.findAgentTuneButton?.();
    if (!tune) {
      flowLog("probe · no tune button", "dbg");
      return null;
    }
    flowLog("probe · open agent panel via tune…", "dbg");
    await clickEl(tune);
    await breakableDelay(900);
    if (UI.findAgentSettingsPanel?.()) {
      flowLog("probe · opened agent-panel", "ok");
      return "agent-panel";
    }
    if (UI.findSettingsOverlay?.()) {
      flowLog("probe · tune opened popover instead", "ok");
      return "popover";
    }
    flowLog("probe · tune click opened nothing", "dbg");
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
    );
    await breakableDelay(300);
    return null;
  };

  const preferAgent = snap.preferred === "agent-panel";
  const primary = preferAgent ? tryOpenAgent : tryOpenPopover;
  const secondary = preferAgent ? tryOpenPopover : tryOpenAgent;

  let mode = await primary();
  if (!mode) mode = await secondary();
  flowLog(`probe · result=${mode || "unknown"}`, mode ? "ok" : "err");
  return mode || "unknown";
}

/** Route by live UI surface (not by subscription). */
async function applySettingsForCurrentTier(settings) {
  let surface = "unknown";
  try {
    surface = await probeSettingsSurface();
  } catch (e) {
    flowLog(`probe failed: ${e.message}`, "err");
  }
  flowLog(`settings route → ${surface}`);

  if (surface === "popover") {
    await applyComposerSettings(settings);
    return "popover";
  }
  if (surface === "agent-panel") {
    await configureAgentSettingsFree(settings);
    return "agent-panel";
  }

  const snap = UI?.inspectSettingsSurface?.() || {};
  if (snap.plusChipVisible) {
    flowLog("settings fallback → popover (chip visible)", "dbg");
    await applyComposerSettings(settings);
    return "popover";
  }
  if (snap.tuneVisible) {
    flowLog("settings fallback → agent-panel (tune visible)", "dbg");
    await configureAgentSettingsFree(settings);
    return "agent-panel";
  }

  throw new Error(
    "Could not detect settings UI (no popover chip and no Agent tune). Resize window or open Flow project."
  );
}

function listMediaFingerprints() {
  return UI ? UI.listMediaFingerprints() : [];
}

function pageSaysThinking() {
  return UI ? UI.pageSaysThinking() : false;
}

function snapshotMediaSet() {
  return new Set(listMediaFingerprints());
}

function findNewMediaImage(baselineSet) {
  if (UI?.findNewMediaImage) return UI.findNewMediaImage(baselineSet);
  for (const img of document.querySelectorAll("img")) {
    if (!isVisible(img)) continue;
    const r = img.getBoundingClientRect();
    if (r.width < 80 || r.height < 80) continue;
    const src = img.currentSrc || img.src || "";
    if (!src || baselineSet.has(src)) continue;
    const alt = (img.alt || "").toLowerCase();
    if (
      alt.includes("tile displaying") ||
      alt.includes("generated image") ||
      src.includes("flow-content.google")
    ) {
      return img;
    }
  }
  return null;
}

async function waitForSubmitAck(timeoutMs = 14000, submittedPrompt = "", opts = {}) {
  const start = Date.now();
  const expect = String(submittedPrompt || "")
    .replace(/\s+/g, " ")
    .trim();
  const baselineHadAgent = !!opts.baselineHadAgent;
  while (Date.now() - start < timeoutMs) {
    if (!isRunning) throw new Error("USER_STOPPED");
    if (pageSaysThinking()) {
      flowLog("submit ack · Thinking…", "ok");
      return true;
    }
    const agentNow = pageSaysAgentActivity() || pageSaysAgentFailed();
    if (agentNow && !baselineHadAgent) {
      flowLog("submit ack · Agent activity", "ok");
      return true;
    }
    const editor = findPromptEditor();
    const plain = editorPlainText(editor);
    if (editor && !plain) {
      flowLog("submit ack · editor cleared", "ok");
      return true;
    }
    // Prompt left the composer and appears as a session bubble
    if (
      expect &&
      sessionMentionsPrompt(expect) &&
      (!plain || !plain.toLowerCase().includes(expect.slice(0, 20).toLowerCase()))
    ) {
      flowLog("submit ack · prompt in session chat", "ok");
      return true;
    }
    await clickAgentConfirmIfPresent();
    await breakableDelay(300);
  }
  return false;
}

function pageSaysAgentActivity() {
  return UI?.pageSaysAgentActivity?.() || false;
}

function pageSaysAgentFailed() {
  return UI?.pageSaysAgentFailed?.() || false;
}

function sessionMentionsPrompt(snippet) {
  const want = String(snippet || "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase()
    .slice(0, 36);
  if (!want || want.length < 6) return false;
  for (const el of document.querySelectorAll("div, p, span, li")) {
    if (!isVisible(el)) continue;
    const t = (el.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
    if (t.length < 6 || t.length > 400) continue;
    if (el.closest?.(".ProseMirror")) continue;
    if (t.includes(want)) return true;
  }
  return false;
}

async function clickAgentConfirmIfPresent() {
  const allowed = new Set(["Generate", "Confirm", "Continue", "Yes", "Run", "Looks good"]);
  for (const label of allowed) {
    const btn = Array.from(document.querySelectorAll("button")).find((el) => {
      if (!isVisible(el) || el.disabled || isForbiddenClickTarget(el)) return false;
      return (el.textContent || "").trim() === label;
    });
    if (btn) {
      console.log("Farm Flow: agent confirm →", label);
      await clickEl(btn);
      await breakableDelay(400);
      return true;
    }
  }
  return false;
}

function listNewMediaImages(baselineSet) {
  const out = [];
  for (const img of document.querySelectorAll("img")) {
    if (UI?.isFlowMediaImg) {
      if (!UI.isFlowMediaImg(img)) continue;
    } else if (!isVisible(img)) continue;
    const src = img.currentSrc || img.src || "";
    if (!src || baselineSet.has(src)) continue;
    if (img.getAttribute("data-flow-downloaded") === "1") continue;
    out.push(img);
  }
  return out;
}

function isDangerousMenuLabel(text) {
  const t = String(text || "").toLowerCase();
  return (
    t.includes("trash") ||
    t.includes("delete") ||
    t.includes("remove") ||
    t.includes("move to") ||
    t.includes("discard")
  );
}

function downloadViaBackground(url, filename) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(
      { action: "DOWNLOAD_URL", url, filename },
      (response) => {
        void chrome.runtime.lastError;
        resolve(!!(response && response.success));
      }
    );
  });
}

/** Prefer direct URL download — never opens gallery context menu (avoids Trash). */
async function downloadImagesSafe(images, _jobIndex) {
  const list = images.filter(Boolean);
  if (!list.length) throw new Error("No images to download");

  const st = await new Promise((resolve) =>
    chrome.storage.local.get(
      [STORAGE_KEYS.genName, STORAGE_KEYS.workerId, STORAGE_KEYS.downloadSeq],
      resolve
    )
  );
  const gen = sanitizeGenName(st[STORAGE_KEYS.genName]);
  const wid = Math.max(1, parseInt(st[STORAGE_KEYS.workerId] || 1, 10) || 1);
  let seq = Math.max(0, parseInt(st[STORAGE_KEYS.downloadSeq] || 0, 10) || 0);

  let ok = 0;
  for (let i = 0; i < list.length; i++) {
    if (!isRunning) throw new Error("USER_STOPPED");
    const img = list[i];
    const src = img.currentSrc || img.src;
    if (!src) continue;
    seq += 1;
    // FarmFlow/fruits/fruits_w1_01.png — generation folder + window id
    const base = `${gen}_w${wid}_${pad2(seq)}.png`;
    const filename = `${gen}/${base}`;
    safeSendMessage({
      action: "AUTOMATION_PROGRESS",
      statusText: `Download ${base}`
    });
    flowLog(`Download ${base}`);

    let saved = false;
    if (src.startsWith("http") || src.startsWith("blob:") || src.startsWith("data:")) {
      saved = await downloadViaBackground(src, filename);
    }

    if (!saved) {
      // Strict context-menu fallback: Download / 1K only
      saved = await downloadViaContextMenuStrict(img);
    }

    if (saved) {
      ok += 1;
      img.setAttribute("data-flow-downloaded", "1");
      const card = img.closest("article, li, [role='listitem'], div");
      if (card) card.setAttribute("data-flow-downloaded", "true");
    }
    await breakableDelay(800);
  }

  await new Promise((resolve) =>
    chrome.storage.local.set({ [STORAGE_KEYS.downloadSeq]: seq }, resolve)
  );

  if (!ok) throw new Error("Download failed for all tiles");
  return { ok, gen, wid, seq };
}

async function downloadViaContextMenuStrict(img) {
  await clickEl(img, "right");
  await breakableDelay(700);

  const items = Array.from(
    document.querySelectorAll("[role='menuitem'], button[role='menuitem'], div[role='menuitem']")
  ).filter(isVisible);

  const downloadItem = items.find((el) => {
    const t = (el.textContent || "").replace(/\s+/g, " ").trim();
    if (isDangerousMenuLabel(t)) return false;
    return /^download$/i.test(t) || t.toLowerCase().startsWith("download");
  });

  if (!downloadItem) {
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
    );
    return false;
  }

  await clickEl(downloadItem);
  await breakableDelay(500);

  try {
    const oneK = Array.from(
      document.querySelectorAll("[role='menuitem'], button[role='menuitem']")
    )
      .filter(isVisible)
      .find((el) => {
        const t = (el.textContent || "").replace(/\s+/g, " ");
        if (isDangerousMenuLabel(t)) return false;
        return /\b1K\b/i.test(t);
      });
    if (oneK) {
      await clickEl(oneK);
      await breakableDelay(600);
    }
  } catch (_) {}

  document.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
  );
  await breakableDelay(400);
  return true;
}

async function waitForGenerationBatch(baselineSet, expectCount = 1) {
  const need = Math.max(1, expectCount);
  let sawThinking = false;
  let found = [];
  let retriesDone = 0;
  const maxRetries = 8;
  let lastRetryAt = 0;
  let agentRetries = 0;

  for (let i = 0; i < 240; i++) {
    if (!isRunning) throw new Error("USER_STOPPED");

    const warningToast = document.evaluate(
      "//*[contains(text(), 'unusual activity') or contains(text(), 'You have reached the limit')]",
      document,
      null,
      XPathResult.FIRST_ORDERED_NODE_TYPE,
      null
    ).singleNodeValue;
    if (warningToast && isVisible(warningToast)) {
      throw new Error("CRITICAL_ACCOUNT_BLOCK");
    }

    if (pageSaysThinking() || pageSaysAgentActivity()) sawThinking = true;
    if (i > 0 && i % 3 === 0) await clickAgentConfirmIfPresent();

    // Agent chat hard-fail → Try again / re-Send
    if (
      pageSaysAgentFailed() &&
      agentRetries < 3 &&
      Date.now() - lastRetryAt > 2500
    ) {
      agentRetries += 1;
      lastRetryAt = Date.now();
      const tryBtn = UI?.findAgentTryAgainButton?.();
      flowLog(
        tryBtn
          ? `Agent failed · Try again ${agentRetries}/3`
          : `Agent failed · re-Send ${agentRetries}/3`
      );
      safeSendMessage({
        action: "AUTOMATION_PROGRESS",
        statusText: `Agent failed → retry ${agentRetries}/3…`,
        lastError: ""
      });
      if (tryBtn) await clickEl(tryBtn);
      else {
        const ed = findPromptEditor();
        const send = findSubmitButton(ed);
        if (send && !send.disabled) await clickEl(send);
        else if (ed) {
          submitViaEnter(ed);
          if (debuggerReady) await cdpKey("Enter", { code: "Enter", keyCode: 13 });
        }
      }
      sawThinking = false;
      await breakableDelay(1200);
      continue;
    }

    // Failed tile → click retry (refresh) and keep waiting
    const failedTiles =
      UI?.findFailedGenerationTiles?.() || findFailedGenerationTilesLocal();
    if (
      failedTiles.length > 0 &&
      retriesDone < maxRetries &&
      Date.now() - lastRetryAt > 3500
    ) {
      const retryBtn =
        UI?.findFailedTileRetryButton?.(failedTiles[0]) ||
        findFailedTileRetryButtonLocal(failedTiles[0]);
      if (retryBtn) {
        retriesDone += 1;
        lastRetryAt = Date.now();
        console.log(
          `Farm Flow: Failed tile detected — retry ${retriesDone}/${maxRetries}`,
          UI?.elementSummary?.(retryBtn) || retryBtn
        );
        flowLog(`Failed tile · retry ${retriesDone}/${maxRetries}`);
        safeSendMessage({
          action: "AUTOMATION_PROGRESS",
          statusText: `Failed → retry ${retriesDone}/${maxRetries}…`,
          lastError: ""
        });
        await clickEl(retryBtn);
        await breakableDelay(1500);
        sawThinking = false;
        continue;
      }
    }
    if (failedTiles.length > 0 && retriesDone >= maxRetries) {
      throw new Error(
        `Generation Failed after ${maxRetries} retries (Failed to load image).`
      );
    }

    found = listNewMediaImages(baselineSet);
    if (found.length >= need) break;

    if (i % 10 === 0) {
      const failHint = failedTiles.length ? " · fail tile" : "";
      const modeHint = pageSaysAgentActivity() ? " · agent" : "";
      safeSendMessage({
        action: "AUTOMATION_PROGRESS",
        statusText: sawThinking
          ? `Waiting ${found.length}/${need}… (${Math.round(i * 0.5)}s)${failHint}${modeHint}`
          : `No gen yet 0/${need} (${Math.round(i * 0.5)}s)${failHint}`
      });
    }
    await breakableDelay(500);
  }

  if (found.length < need) {
    if (found.length === 0) {
      const stillFailed =
        (UI?.findFailedGenerationTiles?.() || findFailedGenerationTilesLocal()).length > 0;
      throw new Error(
        stillFailed
          ? `No new image — still Failed after ${retriesDone} retry(ies).`
          : pageSaysAgentFailed()
            ? `Agent failed and no new image after ${agentRetries} retry(ies).`
            : `No new image after submit (expected ${need}). Check prompt + Send.`
      );
    }
    console.warn(
      `Farm Flow: expected ${need} tiles, got ${found.length} — downloading what we have`
    );
  }

  // Wait for % indicators to clear — do NOT click gallery meanwhile
  for (let i = 0; i < 80; i++) {
    if (!isRunning) throw new Error("USER_STOPPED");
    const pct = document.evaluate(
      "//div[contains(text(), '%')]",
      document,
      null,
      XPathResult.FIRST_ORDERED_NODE_TYPE,
      null
    ).singleNodeValue;
    if (!pct || !isVisible(pct)) break;
    await breakableDelay(500);
  }
  await breakableDelay(1200);

  // Refresh list after settle
  found = listNewMediaImages(baselineSet).slice(0, need);
  return found;
}

function findFailedGenerationTilesLocal() {
  const hits = [];
  for (const el of document.querySelectorAll("div, section, article")) {
    if (!isVisible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 120 || r.height < 100 || r.width > innerWidth * 0.85) continue;
    const t = (el.innerText || "").replace(/\s+/g, " ").trim().toLowerCase();
    if (t.length > 180) continue;
    if (t.includes("failed to load image") || t.includes("failed to generate")) {
      hits.push(el);
      if (hits.length >= 6) break;
    }
  }
  return hits;
}

function findFailedTileRetryButtonLocal(tileRoot) {
  if (!tileRoot) return null;
  return (
    Array.from(tileRoot.querySelectorAll("button, [role='button']")).find((b) => {
      if (!isVisible(b)) return false;
      const blob = `${b.getAttribute("aria-label") || ""} ${b.getAttribute("title") || ""} ${b.textContent || ""}`.toLowerCase();
      return /retry|reload|refresh|regenerate|replay|autorenew|sync/.test(blob);
    }) || null
  );
}

async function submitPromptNow(editor) {
  if (!editor) throw new Error("No editor to submit");
  const submittedPrompt = editorPlainText(editor);
  const baselineHadAgent = pageSaysAgentActivity() || pageSaysAgentFailed();
  editor.focus();
  await clickEl(editor);
  await breakableDelay(200);

  // Wait until send is enabled if present
  let submitBtn = null;
  for (let i = 0; i < 20; i++) {
    submitBtn = findSubmitButton(editor);
    if (
      submitBtn &&
      !submitBtn.disabled &&
      submitBtn.getAttribute("aria-disabled") !== "true"
    ) {
      break;
    }
    submitBtn = null;
    await breakableDelay(200);
  }

  if (submitBtn) {
    flowLog(`submit · Send · ${describeEl(submitBtn)}`, "dbg");
    await clickEl(submitBtn);
  } else {
    flowLog("submit · Send missing — Enter", "dbg");
    submitViaEnter(editor);
    if (debuggerReady) {
      await cdpKey("Enter", { code: "Enter", keyCode: 13 });
    }
  }

  await breakableDelay(600);
  await clickAgentConfirmIfPresent();

  const ackOpts = { baselineHadAgent };
  const ack = await waitForSubmitAck(14000, submittedPrompt, ackOpts);
  if (!ack) {
    flowLog("submit ack missing — retry Enter / Send", "dbg");
    const again = findSubmitButton(findPromptEditor());
    if (again && !again.disabled) await clickEl(again);
    else {
      submitViaEnter(findPromptEditor() || editor);
      if (debuggerReady) {
        await cdpKey("Enter", { code: "Enter", keyCode: 13 });
      }
    }
    await breakableDelay(500);
    await clickAgentConfirmIfPresent();
    if (!(await waitForSubmitAck(8000, submittedPrompt, ackOpts))) {
      // Soft continue: composer empty OR Stop/Thinking visible after retries
      const ed = findPromptEditor();
      const plain = editorPlainText(ed);
      if (!plain || pageSaysThinking() || pageSaysAgentActivity() || pageSaysAgentFailed()) {
        flowLog("submit · late ack (editor empty / Thinking / Agent) — continue", "ok");
        return;
      }
      if (
        sessionMentionsPrompt(submittedPrompt) &&
        (!plain || !plain.toLowerCase().includes(submittedPrompt.slice(0, 16).toLowerCase()))
      ) {
        flowLog("submit · no Thinking but prompt is in session — continue", "ok");
        return;
      }
      throw new Error(
        "Submit did not start (no Thinking… / Agent ack). Check Send enabled and Agent Confirmation=Never."
      );
    }
  }
}

async function runAutomationCycle() {
  if (runAutomationCycle._busy) {
    flowLog("cycle already running — skip duplicate start", "dbg");
    return;
  }
  runAutomationCycle._busy = true;
  try {
  while (isRunning) {
    try {
      const storageData = await new Promise((resolve) =>
        chrome.storage.local.get(Object.values(STORAGE_KEYS), resolve)
      );

      if (storageData[STORAGE_KEYS.isAutomating] !== true || !isRunning) break;

      const rawPrompts = storageData[STORAGE_KEYS.promptsText] || "";
      const prompts = parseQueueText(rawPrompts);

      if (prompts.length === 0) {
        isRunning = false;
        await detachDebugger();
        chrome.storage.local.set({ [STORAGE_KEYS.isAutomating]: false }, () => {
          safeSendMessage({ action: "AUTOMATION_PROGRESS", isDone: true });
        });
        break;
      }

      const currentPrompt = prompts[0];
      let indexQueue = [];
      try {
        indexQueue = JSON.parse(storageData[STORAGE_KEYS.jobIndexQueue] || "[]");
      } catch (_) {
        indexQueue = [];
      }
      const explicitIndex = Number(indexQueue[0]);
      const jobIndex = Number.isFinite(explicitIndex) && explicitIndex > 0
        ? explicitIndex
        : parseInt(storageData[STORAGE_KEYS.jobIndex] || 0, 10) + 1;
      const refImage = storageData[STORAGE_KEYS.refImage] || null;
      const settings = {
        aspectRatio: storageData[STORAGE_KEYS.aspectRatio] || "1:1",
        batchSize: storageData[STORAGE_KEYS.batchSize] || "1x",
        model: storageData[STORAGE_KEYS.model] || "Nano Banana 2"
      };

      console.log("Farm Flow: running:", currentPrompt.slice(0, 80));
      flowLog(`Job #${pad2(jobIndex)} · ${prompts.length} left · ${currentPrompt.slice(0, 60)}…`);
      safeSendMessage({
        action: "AUTOMATION_PROGRESS",
        statusText: `Job #${pad2(jobIndex)} (${prompts.length} left)`,
        jobIndex
      });

      // Close leftover overlays once
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
      );
      await breakableDelay(250);

      // Apply aspect / quantity / model once (Plus popover OR Free Agent panel)
      if (!settingsConfiguredOnce) {
        const tierHint = UI?.inspectSettingsSurface?.()?.preferred || UI?.detectUiTier?.() || "?";
        flowLog(`Applying settings (${tierHint})…`);
        try {
          const surface = await applySettingsForCurrentTier(settings);
          flowLog(
            `Settings · ${surface} · ${settings.aspectRatio} · ${settings.batchSize} · ${settings.model}`,
            "ok"
          );
        } catch (e) {
          console.warn("Farm Flow: settings error:", e.message);
          flowLog(`Settings failed: ${e.message}`, "err");
          safeSendMessage({
            action: "AUTOMATION_PROGRESS",
            lastError: `Settings failed: ${e.message}`
          });
        }
        settingsConfiguredOnce = true;
        // Close leftover Plus overlays only; Agent panel closes on Save
        if (UI?.isSettingsOverlayOpen?.()) {
          document.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
          );
          await breakableDelay(300);
        }
      }

      await prepareComposer();
      await dismissFlowOverlays();
      flowLog("Injecting prompt…");
      await injectTextRobust(currentPrompt);
      flowLog("Prompt injected", "ok");

      // Reference AFTER text: injectTextRobust clears the editor and would wipe a prior paste
      if (refImage) {
        try {
          flowLog("Attaching reference (after prompt)…");
          await attachReference(refImage);
          flowLog("Reference attached in prompt", "ok");
        } catch (e) {
          // Soft-fail: still submit the prompt (text-only) so the queue does not die
          flowLog(`Reference failed — continuing to Submit anyway: ${e.message}`, "err");
          console.warn("Farm Flow: reference attach failed, submitting without ref:", e.message);
          safeSendMessage({
            action: "AUTOMATION_PROGRESS",
            lastError: `Reference soft-fail: ${e.message}`
          });
          // Close leftover asset overlay if any
          document.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
          );
          await breakableDelay(300);
        }
      }

      const editor = findPromptEditor();
      if (!editor) {
        throw new Error("Prompt field disappeared after inject");
      }

      // Hard verify — exact prompt, no leftovers like "black coffeetea"
      const plain = editorPlainText(editor).replace(/\s+/g, " ").trim();
      const expect = currentPrompt.replace(/\s+/g, " ").trim();
      if (!plain || plain !== expect) {
        flowLog(
          `inject verify fail · got "${plain.slice(0, 60)}" · want "${expect.slice(0, 40)}" — re-inject`,
          "dbg"
        );
        await injectTextRobust(currentPrompt);
        const plain2 = editorPlainText(findPromptEditor() || editor)
          .replace(/\s+/g, " ")
          .trim();
        if (plain2 !== expect) {
          throw new Error(
            `Prompt was NOT inserted cleanly (editor has: "${plain2.slice(0, 60) || "(empty)"}"). Click the composer, then Start again.`
          );
        }
      }
      if (refImage && !composerHasReferenceAttachment(editor, 0)) {
        flowLog("ref · no chip detected before submit — sending text-only", "err");
      } else if (refImage) {
        flowLog(`ref · chip OK before submit · count=${countComposerReferenceImgs(editor)}`, "ok");
      }
      console.log("Farm Flow: prompt verified in editor:", plain.slice(0, 80));

      // Snapshot gallery BEFORE submit — never click tiles until batch is ready
      const baseline = snapshotMediaSet();
      const expectCount = quantityFromBatch(settings.batchSize);
      console.log("Farm Flow: baseline media", baseline.size, "expect", expectCount);
      flowLog(`Submit · expect ${expectCount} tile(s)`);

      await submitPromptNow(editor);

      const newImages = await waitForGenerationBatch(baseline, expectCount);
      flowLog(`Generated ${newImages.length}/${expectCount}`, "ok");
      const dl = await downloadImagesSafe(newImages, jobIndex);
      flowLog(
        `Done job #${pad2(jobIndex)} · ${newImages.length} file(s) → FarmFlow/${dl.gen}/${dl.gen}_w${dl.wid}_*.png`,
        "ok"
      );

      const remaining = serializeQueue(prompts.slice(1));
      const remainingIndexes = indexQueue.slice(1);
      const completed =
        parseInt(storageData[STORAGE_KEYS.statsCompleted] || 0, 10) +
        newImages.length;
      const failed = parseInt(storageData[STORAGE_KEYS.statsFailed] || 0, 10);

      await new Promise((resolve) =>
        chrome.storage.local.set(
          {
            [STORAGE_KEYS.promptsText]: remaining,
            [STORAGE_KEYS.jobIndexQueue]: JSON.stringify(remainingIndexes),
            [STORAGE_KEYS.statsCompleted]: completed,
            [STORAGE_KEYS.jobIndex]: Math.max(
              parseInt(storageData[STORAGE_KEYS.jobIndex] || 0, 10),
              jobIndex
            ),
            [STORAGE_KEYS.lastError]: ""
          },
          resolve
        )
      );

      safeSendMessage({
        action: "AUTOMATION_PROGRESS",
        stats: { completed, failed },
        remainingPromptsText: remaining,
        lastError: "",
        jobIndex,
        isDone: prompts.length <= 1
      });

      if (prompts.length <= 1) {
        isRunning = false;
        await detachDebugger();
        chrome.storage.local.set({ [STORAGE_KEYS.isAutomating]: false });
        break;
      }

      const baseRest =
        parseInt(storageData[STORAGE_KEYS.restDelay] || 5, 10) * 1000;
      const restTime = baseRest + Math.floor(Math.random() * 5000);
      safeSendMessage({
        action: "AUTOMATION_PROGRESS",
        statusText: `Resting ${(restTime / 1000).toFixed(1)}s…`
      });
      await breakableDelay(restTime);
    } catch (e) {
      if (e.message === "CRITICAL_ACCOUNT_BLOCK") {
        reportError("BLOCKED BY GOOGLE");
        isRunning = false;
        chrome.storage.local.set({ [STORAGE_KEYS.isAutomating]: false });
        safeSendMessage({ action: "UPDATE_STATUS", status: "BLOCKED BY GOOGLE" });
        await detachDebugger();
        return;
      }
      if (e.message === "USER_STOPPED") {
        isRunning = false;
        await detachDebugger();
        break;
      }

      const errMsg = e.message || String(e);
      reportError(errMsg);

      const storageData = await new Promise((resolve) =>
        chrome.storage.local.get(Object.values(STORAGE_KEYS), resolve)
      );
      const rawPrompts = storageData[STORAGE_KEYS.promptsText] || "";
      const prompts = parseQueueText(rawPrompts);
      const currentPrompt = prompts[0] || "";
      const failedText = storageData[STORAGE_KEYS.failedPromptsText] || "";
      const entry = `${currentPrompt}\n# ERR: ${errMsg}`;
      const newFailed = failedText ? `${failedText}\n\n${entry}` : entry;
      const remaining = serializeQueue(prompts.slice(1));
      const completed = parseInt(storageData[STORAGE_KEYS.statsCompleted] || 0, 10);
      const failed = parseInt(storageData[STORAGE_KEYS.statsFailed] || 0, 10) + 1;

      isRunning = false;
      await detachDebugger();

      chrome.storage.local.set(
        {
          [STORAGE_KEYS.isAutomating]: false,
          [STORAGE_KEYS.promptsText]: remaining,
          [STORAGE_KEYS.failedPromptsText]: newFailed,
          [STORAGE_KEYS.statsFailed]: failed,
          [STORAGE_KEYS.lastError]: errMsg
        },
        () => {
          safeSendMessage({
            action: "AUTOMATION_PROGRESS",
            stats: { completed, failed },
            remainingPromptsText: remaining,
            failedPromptsText: newFailed,
            lastError: errMsg,
            isDone: true
          });
        }
      );
      break;
    }
  }
  } finally {
    runAutomationCycle._busy = false;
  }
}

async function ensureDebuggerOptional() {
  stripForeignExtensionFrames();
  try {
    await attachDebugger();
    debuggerReady = true;
    console.log("Farm Flow: debugger attached");
    return true;
  } catch (err) {
    debuggerReady = false;
    console.warn(
      "Farm Flow: debugger unavailable, using DOM mode:",
      err.message
    );
    return false;
  }
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "PING") {
    sendResponse({ success: true, status: "pong", href: location.href });
    return true;
  }

  if (request.action === "SCRAPE_FLOW_UI") {
    try {
      const report = UI?.scrapeFlowUI?.() || { error: "flow-ui.js not loaded" };
      sendResponse({ success: true, report });
    } catch (e) {
      sendResponse({ success: false, error: e.message || String(e) });
    }
    return true;
  }

  if (request.action === "START_FLOW_AUTOMATION") {
    if (!isFlowPage()) {
      sendResponse({
        success: false,
        message: "Open a Flow project tab first."
      });
      return true;
    }

    (async () => {
      try {
        let prompts = Array.isArray(request.prompts) ? request.prompts.slice() : [];
        let jobIndexes = Array.isArray(request.jobIndexes)
          ? request.jobIndexes.map((n) => Number(n)).filter((n) => Number.isFinite(n) && n > 0)
          : [];

        // Farm hub arms chrome.storage first — trust that over flaky message fields
        if (request.preArmed) {
          const st = await new Promise((resolve) =>
            chrome.storage.local.get(
              [
                STORAGE_KEYS.promptsText,
                STORAGE_KEYS.jobIndexQueue,
                STORAGE_KEYS.refImage,
                STORAGE_KEYS.genName,
                STORAGE_KEYS.workerId
              ],
              resolve
            )
          );
          const storedPrompts = parseQueueText(st[STORAGE_KEYS.promptsText] || "");
          let storedIndexes = [];
          try {
            storedIndexes = JSON.parse(st[STORAGE_KEYS.jobIndexQueue] || "[]")
              .map(Number)
              .filter((n) => Number.isFinite(n) && n > 0);
          } catch (_) {}
          if (storedPrompts.length) prompts = storedPrompts;
          if (storedIndexes.length === prompts.length) jobIndexes = storedIndexes;
          if (st[STORAGE_KEYS.genName]) request.genName = st[STORAGE_KEYS.genName];
          if (st[STORAGE_KEYS.workerId]) request.workerId = st[STORAGE_KEYS.workerId];
        }

        if (Array.isArray(request.jobs) && request.jobs.length && !request.preArmed) {
          const pairs = request.jobs
            .map((j) => ({
              prompt: String(j.prompt || j.text || "").trim(),
              jobIndex: Number(j.jobIndex || j.index || 0)
            }))
            .filter((j) => j.prompt);
          prompts = pairs.map((p) => p.prompt);
          const fromJobs = pairs
            .map((p) => p.jobIndex)
            .filter((n) => Number.isFinite(n) && n > 0);
          if (jobIndexes.length !== prompts.length && fromJobs.length === prompts.length) {
            jobIndexes = fromJobs;
          }
        }
        if (!prompts.length) {
          sendResponse({ success: false, error: "No prompts provided." });
          return;
        }
        if (jobIndexes.length !== prompts.length) {
          const startAt = Math.max(1, parseInt(request.startJobIndex || 1, 10));
          jobIndexes = prompts.map((_, i) => startAt + i);
        }

        const updates = {
          [STORAGE_KEYS.isAutomating]: true,
          [STORAGE_KEYS.promptsText]: serializeQueue(prompts),
          [STORAGE_KEYS.jobIndexQueue]: JSON.stringify(jobIndexes),
          [STORAGE_KEYS.aspectRatio]: request.aspectRatio,
          [STORAGE_KEYS.batchSize]: request.batchSize,
          [STORAGE_KEYS.model]: request.model,
          [STORAGE_KEYS.restDelay]: request.restDelay,
          [STORAGE_KEYS.lastError]: "",
          [STORAGE_KEYS.statsCompleted]: 0,
          [STORAGE_KEYS.statsFailed]: 0,
          [STORAGE_KEYS.isPaused]: false,
          [STORAGE_KEYS.genName]: sanitizeGenName(request.genName || request.generationName),
          [STORAGE_KEYS.workerId]: Math.max(
            1,
            parseInt(request.workerId || request.windowId || 1, 10) || 1
          ),
          [STORAGE_KEYS.downloadSeq]: 0
        };
        if (request.refImage !== undefined) {
          updates[STORAGE_KEYS.refImage] = request.refImage || null;
        }

        await new Promise((resolve) => chrome.storage.local.set(updates, resolve));
        flowLog(
          `Queue armed · ${prompts.length} job(s) · gen=${updates[STORAGE_KEYS.genName]} · W${updates[STORAGE_KEYS.workerId]} · indexes=[${jobIndexes.join(",")}] · ref=${updates[STORAGE_KEYS.refImage] ? "yes" : "no"}`,
          "ok"
        );

        const editor = (await waitForPromptEditor(10000)) || (await prepareComposer());
        if (!editor) {
          chrome.storage.local.set({ [STORAGE_KEYS.isAutomating]: false });
          sendResponse({
            success: false,
            error:
              "Prompt field not found. Click «What do you want to create?» at the bottom, then Start again."
          });
          return;
        }

        if (request.scrapeFirst && UI?.scrapeFlowUI) {
          UI.scrapeFlowUI();
        }

        await ensureDebuggerOptional();
        refAttachedOnce = false;
        settingsConfiguredOnce = false;
        isPaused = false;
        isRunning = true;
        sendResponse({
          success: true,
          debugger: debuggerReady,
          mode: debuggerReady ? "cdp" : "dom",
          jobs: prompts.length,
          jobIndexes
        });
        runAutomationCycle();
      } catch (err) {
        chrome.storage.local.set({ [STORAGE_KEYS.isAutomating]: false });
        sendResponse({ success: false, error: err.message || String(err) });
      }
    })();
    return true;
  }

  if (request.action === "STOP_FLOW_AUTOMATION") {
    isRunning = false;
    isPaused = false;
    detachDebugger();
    chrome.storage.local.set(
      {
        [STORAGE_KEYS.isAutomating]: false,
        [STORAGE_KEYS.isPaused]: false
      },
      () => {
        sendResponse({ success: true });
      }
    );
    return true;
  }

  if (request.action === "PAUSE_FLOW_AUTOMATION") {
    isPaused = true;
    chrome.storage.local.set({ [STORAGE_KEYS.isPaused]: true }, () => {
      flowLog("Paused");
      safeSendMessage({
        action: "AUTOMATION_PROGRESS",
        statusText: "Paused",
        paused: true
      });
      sendResponse({ success: true });
    });
    return true;
  }

  if (request.action === "RESUME_FLOW_AUTOMATION") {
    isPaused = false;
    chrome.storage.local.set({ [STORAGE_KEYS.isPaused]: false }, () => {
      flowLog("Resumed", "ok");
      if (!isRunning) {
        isRunning = true;
        chrome.storage.local.set({ [STORAGE_KEYS.isAutomating]: true });
        ensureDebuggerOptional().then(() => runAutomationCycle());
      }
      safeSendMessage({
        action: "AUTOMATION_PROGRESS",
        statusText: "Resumed",
        paused: false
      });
      sendResponse({ success: true });
    });
    return true;
  }

  if (request.action === "APPLY_SETTINGS_ONLY") {
    (async () => {
      try {
        await ensureDebuggerOptional();
        const settings = {
          aspectRatio: request.aspectRatio || "1:1",
          batchSize: request.batchSize || "1x",
          model: request.model || "Nano Banana 2"
        };
        chrome.storage.local.set({
          [STORAGE_KEYS.aspectRatio]: settings.aspectRatio,
          [STORAGE_KEYS.batchSize]: settings.batchSize,
          [STORAGE_KEYS.model]: settings.model
        });
        settingsConfiguredOnce = false;
        const surface = await applySettingsForCurrentTier(settings);
        settingsConfiguredOnce = true;
        if (UI?.isSettingsOverlayOpen?.()) await dismissFlowOverlays();
        const chip = UI?.readSettingsChipText?.() || "";
        flowLog(`Apply settings only · ${surface} · chip: ${chip || "(agent panel)"}`, "ok");
        sendResponse({ success: true, surface, tier: surface, chipText: chip });
      } catch (e) {
        sendResponse({ success: false, error: e.message || String(e) });
      }
    })();
    return true;
  }
});

if (isFlowPage()) {
  chrome.storage.local.get(Object.values(STORAGE_KEYS), async (result) => {
    if (result[STORAGE_KEYS.isAutomating] === true) {
      await ensureDebuggerOptional();
      isRunning = true;
      runAutomationCycle();
    }
  });
}
