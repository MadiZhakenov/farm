chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((e) => console.error("Farm Flow: side panel setup failed", e));
});

chrome.runtime.onStartup.addListener(() => {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((e) => console.error("Farm Flow: side panel setup failed", e));
});

const LOGS_KEY = "flow_logs_text";
const MAX_LOG_CHARS = 180_000;

/** Armed path for the next Page.fileChooserOpened */
let armedFileUpload = null; // { tabId, path, done, error, at }

function pad2(n) {
  return String(n).padStart(2, "0");
}

function stamp() {
  const d = new Date();
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
}

async function appendPersistedLog(text, level = "info") {
  const line = `[${stamp()}]${
    level === "err" ? " ERR" : level === "ok" ? " OK" : level === "dbg" ? " ·" : ""
  } ${String(text || "")}`;
  const cur = await chrome.storage.local.get(LOGS_KEY);
  let next = String(cur[LOGS_KEY] || "");
  next = next ? `${next}\n${line}` : line;
  if (next.length > MAX_LOG_CHARS) next = next.slice(-MAX_LOG_CHARS);
  await chrome.storage.local.set({ [LOGS_KEY]: next });
  return line;
}

async function findFlowTab() {
  const tabs = await chrome.tabs.query({
    url: ["*://labs.google/*", "*://flow.google.com/*"]
  });
  if (!tabs.length) return null;
  const project = tabs.find((t) => /\/project\//i.test(t.url || ""));
  if (project) return project;
  const active = tabs.find((t) => t.active);
  return active || tabs[0];
}

async function materializeDataUrlToDisk(dataUrl) {
  const filename = `FarmFlow/_temp_farm_reference.png`;
  const old = await chrome.downloads.search({
    filenameRegex: "_temp_farm_reference\\.png$",
    limit: 5
  });
  for (const d of old) {
    try {
      await chrome.downloads.removeFile(d.id);
    } catch (_) {}
    try {
      await chrome.downloads.erase({ id: d.id });
    } catch (_) {}
  }
  const id = await chrome.downloads.download({
    url: dataUrl,
    filename,
    conflictAction: "overwrite",
    saveAs: false
  });
  for (let i = 0; i < 50; i++) {
    const [item] = await chrome.downloads.search({ id });
    if (item?.filename && item.state === "complete") return item.filename;
    if (item?.state === "interrupted") throw new Error("download interrupted");
    await new Promise((r) => setTimeout(r, 120));
  }
  throw new Error("temp file path not ready");
}

chrome.debugger.onEvent.addListener((source, method, params) => {
  if (method !== "Page.fileChooserOpened") return;
  const armed = armedFileUpload;
  if (!armed || armed.tabId !== source.tabId || !armed.path || armed.done) return;
  const backendNodeId = params?.backendNodeId;
  if (!backendNodeId) {
    armed.error = "fileChooserOpened without backendNodeId";
    armed.done = true;
    return;
  }
  chrome.debugger
    .sendCommand({ tabId: source.tabId }, "DOM.setFileInputFiles", {
      backendNodeId,
      files: [armed.path]
    })
    .then(() => {
      armed.done = true;
      armed.ok = true;
      appendPersistedLog("ref · CDP fileChooser set OK", "ok");
    })
    .catch((e) => {
      armed.done = true;
      armed.error = e.message || String(e);
      appendPersistedLog(`ref · CDP fileChooser set FAIL: ${armed.error}`, "err");
    });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const tabId = sender.tab ? sender.tab.id : null;

  if (message.action === "FLOW_LOG") {
    appendPersistedLog(message.text, message.level || "info")
      .then(() => sendResponse({ success: true }))
      .catch((e) => sendResponse({ success: false, error: String(e) }));
    return true;
  }

  if (message.action === "AGENT_GET_STATE") {
    (async () => {
      const storage = await chrome.storage.local.get(null);
      const tab = await findFlowTab();
      sendResponse({
        success: true,
        extensionId: chrome.runtime.id,
        tab: tab
          ? { id: tab.id, url: tab.url, title: tab.title, active: tab.active }
          : null,
        storage: {
          isAutomating: storage.flow_is_automating || false,
          isPaused: storage.flow_is_paused || false,
          lastError: storage.flow_last_error || "",
          statsCompleted: storage.flow_stats_completed || 0,
          statsFailed: storage.flow_stats_failed || 0,
          jobIndex: storage.flow_job_index || 0,
          aspectRatio: storage.flow_aspect_ratio || "",
          batchSize: storage.flow_batch_size || "",
          model: storage.flow_model || "",
          hasRef: !!storage.flow_ref_image,
          promptsPreview: String(storage.flow_prompts_text || "").slice(0, 200),
          logsTail: String(storage.flow_logs_text || "")
            .split("\n")
            .slice(-80)
            .join("\n")
        }
      });
    })();
    return true;
  }

  if (message.action === "AGENT_GET_LOGS") {
    (async () => {
      const cur = await chrome.storage.local.get(LOGS_KEY);
      const full = String(cur[LOGS_KEY] || "");
      const lines = message.tail ? full.split("\n").slice(-(message.tail | 0)) : full.split("\n");
      sendResponse({ success: true, text: lines.join("\n"), chars: full.length });
    })();
    return true;
  }

  if (message.action === "AGENT_CLEAR_LOGS") {
    chrome.storage.local.set({ [LOGS_KEY]: "" }, () =>
      sendResponse({ success: true })
    );
    return true;
  }

  if (message.action === "AGENT_START") {
    (async () => {
      try {
        const tab = await findFlowTab();
        if (!tab?.id) {
          sendResponse({
            success: false,
            error: "No Flow tab open. Open labs.google / flow.google.com first."
          });
          return;
        }
        const jobs = Array.isArray(message.jobs) ? message.jobs : null;
        let prompts = Array.isArray(message.prompts)
          ? message.prompts.map((s) => String(s || "").trim()).filter(Boolean)
          : String(message.prompt || message.promptsText || "")
              .split(/\n@@@FARM_NEXT@@@\n|\n\s*\n/)
              .map((s) => s.trim())
              .filter(Boolean);
        let jobIndexes = Array.isArray(message.jobIndexes)
          ? message.jobIndexes.map((n) => Number(n)).filter((n) => Number.isFinite(n) && n > 0)
          : [];
        if (jobs?.length) {
          const pairs = jobs
            .map((j) => ({
              prompt: String(j.prompt || j.text || "").trim(),
              jobIndex: Number(j.jobIndex || j.index || 0)
            }))
            .filter((j) => j.prompt);
          if (pairs.length) {
            prompts = pairs.map((p) => p.prompt);
            const fromJobs = pairs
              .map((p) => p.jobIndex)
              .filter((n) => Number.isFinite(n) && n > 0);
            if (jobIndexes.length !== prompts.length && fromJobs.length === prompts.length) {
              jobIndexes = fromJobs;
            }
          }
        }
        if (!prompts.length) {
          sendResponse({ success: false, error: "No prompts provided." });
          return;
        }
        if (jobIndexes.length !== prompts.length) {
          const startAt = Math.max(1, parseInt(message.startJobIndex || 1, 10));
          jobIndexes = prompts.map((_, i) => startAt + i);
        }
        if (!/\/project\//i.test(tab.url || "")) {
          sendResponse({
            success: false,
            error:
              "Open a Flow PROJECT tab (…/project/…), not the About page. Use Hub → Open project."
          });
          return;
        }
        const payload = {
          action: "START_FLOW_AUTOMATION",
          prompts,
          jobIndexes,
          jobs: jobs || undefined,
          startJobIndex: jobIndexes[0] || Number(message.startJobIndex) || 1,
          preArmed: message.preArmed === true,
          genName: message.genName || message.generationName || "farm",
          workerId: Number(message.workerId || message.windowId || 1) || 1,
          aspectRatio: message.aspectRatio || "16:9",
          batchSize: message.batchSize || "x1",
          model: message.model || "Nano Banana 2",
          restDelay: message.restDelay || "3",
          iterations: message.iterations || 1
        };
        // Farm Hub always sends clearRef or refImage — never inherit stale cloned ref
        if (message.clearRef === true || message.refImage === null) {
          payload.refImage = null;
        } else if (typeof message.refImage === "string" && message.refImage) {
          payload.refImage = message.refImage;
        } else if (message.keepStoredRef === true) {
          const st = await chrome.storage.local.get("flow_ref_image");
          if (st.flow_ref_image) payload.refImage = st.flow_ref_image;
        } else {
          // Default for agent/farm: no ref unless explicitly provided
          payload.refImage = null;
        }
        await appendPersistedLog(
          `AGENT_START · ${prompts.length} job(s) · gen=${payload.genName} · W${payload.workerId} · indexes=[${jobIndexes.join(",")}] · ref=${payload.refImage ? "yes" : "no"} · ${payload.aspectRatio} · ${payload.model}`,
          "ok"
        );
        const response = await chrome.tabs.sendMessage(tab.id, payload);
        sendResponse(response || { success: false, error: "No response from content" });
      } catch (e) {
        sendResponse({ success: false, error: e.message || String(e) });
      }
    })();
    return true;
  }

  if (message.action === "AGENT_STOP") {
    (async () => {
      const tab = await findFlowTab();
      if (tab?.id) {
        try {
          await chrome.tabs.sendMessage(tab.id, { action: "STOP_FLOW_AUTOMATION" });
        } catch (_) {}
      }
      await chrome.storage.local.set({
        flow_is_automating: false,
        flow_is_paused: false
      });
      await appendPersistedLog("AGENT_STOP", "ok");
      sendResponse({ success: true });
    })();
    return true;
  }

  if (message.action === "AGENT_APPLY_SETTINGS") {
    (async () => {
      try {
        const tab = await findFlowTab();
        if (!tab?.id) {
          sendResponse({ success: false, error: "No Flow tab" });
          return;
        }
        const response = await chrome.tabs.sendMessage(tab.id, {
          action: "APPLY_SETTINGS_ONLY",
          aspectRatio: message.aspectRatio || "16:9",
          batchSize: message.batchSize || "x1",
          model: message.model || "Nano Banana 2"
        });
        sendResponse(response || { success: false });
      } catch (e) {
        sendResponse({ success: false, error: e.message || String(e) });
      }
    })();
    return true;
  }

  if (message.action === "AGENT_SCRAPE") {
    (async () => {
      try {
        const tab = await findFlowTab();
        if (!tab?.id) {
          sendResponse({ success: false, error: "No Flow tab" });
          return;
        }
        const response = await chrome.tabs.sendMessage(tab.id, {
          action: "SCRAPE_FLOW_UI"
        });
        sendResponse(response || { success: false });
      } catch (e) {
        sendResponse({ success: false, error: e.message || String(e) });
      }
    })();
    return true;
  }

  if (message.action === "AGENT_SET_REF") {
    (async () => {
      await chrome.storage.local.set({
        flow_ref_image: message.refImage || null
      });
      await appendPersistedLog(
        message.refImage ? "AGENT_SET_REF · set" : "AGENT_SET_REF · cleared",
        "ok"
      );
      sendResponse({ success: true });
    })();
    return true;
  }

  if (message.action === "CDP_ARM_FILE_UPLOAD") {
    (async () => {
      try {
        if (!tabId) {
          sendResponse({ success: false, error: "No target tab ID." });
          return;
        }
        const dataUrl = message.dataUrl || "";
        if (!/^data:image\//i.test(dataUrl)) {
          sendResponse({ success: false, error: "bad dataUrl" });
          return;
        }
        const path = await materializeDataUrlToDisk(dataUrl);
        await chrome.debugger.sendCommand({ tabId }, "Page.setInterceptFileChooserDialog", {
          enabled: true
        });
        armedFileUpload = {
          tabId,
          path,
          done: false,
          ok: false,
          error: "",
          at: Date.now()
        };
        await appendPersistedLog(`ref · armed file chooser · ${path}`, "dbg");
        sendResponse({ success: true, path });
      } catch (err) {
        sendResponse({ success: false, error: err.message || String(err) });
      }
    })();
    return true;
  }

  if (message.action === "CDP_AWAIT_FILE_UPLOAD") {
    (async () => {
      const timeoutMs = Math.min(20000, Number(message.timeoutMs) || 12000);
      const start = Date.now();
      while (Date.now() - start < timeoutMs) {
        if (armedFileUpload?.done) {
          const res = {
            success: !!armedFileUpload.ok,
            error: armedFileUpload.error || "",
            path: armedFileUpload.path || ""
          };
          armedFileUpload = null;
          try {
            if (tabId) {
              await chrome.debugger.sendCommand(
                { tabId },
                "Page.setInterceptFileChooserDialog",
                { enabled: false }
              );
            }
          } catch (_) {}
          sendResponse(res);
          return;
        }
        await new Promise((r) => setTimeout(r, 150));
      }
      const err = armedFileUpload?.error || "file chooser timeout";
      armedFileUpload = null;
      sendResponse({ success: false, error: err });
    })();
    return true;
  }

  if (message.action === "CDP_SET_FILE_INPUT") {
    (async () => {
      try {
        if (!tabId) {
          sendResponse({ success: false, error: "No target tab ID." });
          return;
        }
        const filePath = message.path;
        if (!filePath) {
          sendResponse({ success: false, error: "No path" });
          return;
        }
        await chrome.debugger.sendCommand({ tabId }, "Page.setInterceptFileChooserDialog", {
          enabled: true
        });
        const doc = await chrome.debugger.sendCommand({ tabId }, "DOM.getDocument", {
          depth: -1
        });
        const selector = message.selector || 'input[type="file"]';
        const { nodeId } = await chrome.debugger.sendCommand({ tabId }, "DOM.querySelector", {
          nodeId: doc.root.nodeId,
          selector
        });
        if (!nodeId) {
          sendResponse({ success: false, error: "file input not found: " + selector });
          return;
        }
        await chrome.debugger.sendCommand({ tabId }, "DOM.setFileInputFiles", {
          nodeId,
          files: [filePath]
        });
        sendResponse({ success: true, nodeId });
      } catch (err) {
        sendResponse({ success: false, error: err.message || String(err) });
      }
    })();
    return true;
  }

  if (message.action === "MATERIALIZE_REF_FILE") {
    (async () => {
      try {
        const dataUrl = message.dataUrl || "";
        if (!/^data:image\//i.test(dataUrl)) {
          sendResponse({ success: false, error: "bad dataUrl" });
          return;
        }
        const filename = `FarmFlow/_temp_farm_reference.png`;
        // Remove prior temp if any
        const old = await chrome.downloads.search({
          filenameRegex: "_temp_farm_reference\\.png$",
          limit: 5
        });
        for (const d of old) {
          try {
            await chrome.downloads.removeFile(d.id);
          } catch (_) {}
          try {
            await chrome.downloads.erase({ id: d.id });
          } catch (_) {}
        }
        const id = await chrome.downloads.download({
          url: dataUrl,
          filename,
          conflictAction: "overwrite",
          saveAs: false
        });
        let path = "";
        for (let i = 0; i < 40; i++) {
          const [item] = await chrome.downloads.search({ id });
          if (item?.filename && item.state === "complete") {
            path = item.filename;
            break;
          }
          if (item?.state === "interrupted") {
            sendResponse({ success: false, error: "download interrupted" });
            return;
          }
          await new Promise((r) => setTimeout(r, 150));
        }
        if (!path) {
          sendResponse({ success: false, error: "temp file path not ready" });
          return;
        }
        sendResponse({ success: true, path, id });
      } catch (err) {
        sendResponse({ success: false, error: err.message || String(err) });
      }
    })();
    return true;
  }

  if (message.action === "ATTACH_DEBUGGER") {
    (async () => {
      try {
        if (!tabId) {
          sendResponse({ success: false, error: "No target tab ID." });
          return;
        }
        try {
          await chrome.debugger.detach({ tabId });
        } catch (_) {}
        await chrome.debugger.attach({ tabId }, "1.3");
        sendResponse({ success: true });
      } catch (err) {
        const msg = err.message || String(err);
        let hint = msg;
        if (/chrome-extension:\/\//i.test(msg)) {
          hint =
            msg +
            " — disable other extensions that inject into this tab (password managers, Claude, etc.), or turn off Brave Shields on Flow.";
        } else if (/Cannot attach|already attached|Another debugger/i.test(msg)) {
          hint =
            msg +
            " — close DevTools on this tab and retry. Only one debugger can attach.";
        }
        sendResponse({ success: false, error: hint });
      }
    })();
    return true;
  }

  if (message.action === "DETACH_DEBUGGER") {
    (async () => {
      try {
        if (tabId) await chrome.debugger.detach({ tabId });
        sendResponse({ success: true });
      } catch (_) {
        sendResponse({ success: true });
      }
    })();
    return true;
  }

  if (message.action === "CDP_CLICK") {
    (async () => {
      try {
        if (!tabId) {
          sendResponse({ success: false, error: "No target tab ID." });
          return;
        }
        const { x, y } = message;
        const button = message.button || "left";
        await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
          type: "mousePressed",
          button,
          x,
          y,
          clickCount: 1
        });
        await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
          type: "mouseReleased",
          button,
          x,
          y,
          clickCount: 1
        });
        sendResponse({ success: true });
      } catch (err) {
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true;
  }

  if (message.action === "CDP_TYPE") {
    (async () => {
      try {
        if (!tabId) {
          sendResponse({ success: false, error: "No target tab ID." });
          return;
        }
        await chrome.debugger.sendCommand({ tabId }, "Input.insertText", {
          text: message.text || ""
        });
        sendResponse({ success: true });
      } catch (err) {
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true;
  }

  if (message.action === "CDP_KEY") {
    (async () => {
      try {
        if (!tabId) {
          sendResponse({ success: false, error: "No target tab ID." });
          return;
        }
        const key = message.key || "Enter";
        const code = message.code || (key === "Enter" ? "Enter" : key);
        const keyCode =
          message.keyCode ??
          (key === "Enter" ? 13 : key === "Backspace" ? 8 : key === "a" ? 65 : 0);
        const modifiers = message.modifiers || 0; // 2 = ctrl
        for (const type of ["keyDown", "keyUp"]) {
          await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
            type,
            key,
            code,
            windowsVirtualKeyCode: keyCode,
            nativeVirtualKeyCode: keyCode,
            modifiers
          });
        }
        sendResponse({ success: true });
      } catch (err) {
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true;
  }

  if (message.action === "WRITE_CLIPBOARD") {
    (async () => {
      try {
        const text = message.text || "";
        if (tabId) {
          await chrome.debugger.sendCommand({ tabId }, "Runtime.evaluate", {
            expression: `navigator.clipboard.writeText(${JSON.stringify(text)})`,
            awaitPromise: true
          });
          sendResponse({ success: true, method: "cdp-clipboard" });
          return;
        }
        sendResponse({ success: false, error: "No tab for clipboard" });
      } catch (err) {
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true;
  }

  if (message.action === "DOWNLOAD_URL") {
    (async () => {
      try {
        const url = message.url;
        // Allow "gen/gen_w1_01.png" (one safe subfolder) — strip path tricks
        let filename = String(message.filename || "farm-flow.png")
          .replace(/\\/g, "/")
          .replace(/\.\./g, "")
          .replace(/[<>:"|?*]/g, "_");
        const parts = filename.split("/").filter(Boolean);
        if (parts.length > 2) {
          filename = parts.slice(-2).join("/");
        } else {
          filename = parts.join("/") || "farm-flow.png";
        }
        if (!url) {
          sendResponse({ success: false, error: "No url" });
          return;
        }
        // Keep extension consistent with source (Flow often serves jpeg)
        if (/\.jpe?g(\?|$)/i.test(url) && filename.toLowerCase().endsWith(".png")) {
          filename = filename.replace(/\.png$/i, ".jpg");
        }
        const downloadId = await chrome.downloads.download({
          url,
          filename: `FarmFlow/${filename}`,
          conflictAction: "uniquify",
          saveAs: false
        });
        // Wait until complete so Hub can list the file
        let finalPath = "";
        for (let i = 0; i < 80; i++) {
          const [item] = await chrome.downloads.search({ id: downloadId });
          if (item?.state === "complete") {
            finalPath = item.filename || "";
            break;
          }
          if (item?.state === "interrupted") {
            sendResponse({ success: false, error: "download interrupted", downloadId });
            return;
          }
          await new Promise((r) => setTimeout(r, 100));
        }
        sendResponse({ success: true, downloadId, path: finalPath, filename });
      } catch (err) {
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true;
  }
});
