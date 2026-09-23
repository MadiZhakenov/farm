document.addEventListener("DOMContentLoaded", () => {
  const promptsInput = document.getElementById("prompts-input");
  const aspectRatio = document.getElementById("aspect-ratio");
  const batchSize = document.getElementById("batch-size");
  const model = document.getElementById("model");
  const iterations = document.getElementById("iterations");
  const restDelay = document.getElementById("rest-delay");
  const toggleBtn = document.getElementById("toggle-btn");
  const stopBtn = document.getElementById("stop-btn");
  const applySettingsBtn = document.getElementById("apply-settings-btn");
  const promptBadge = document.getElementById("prompt-badge");
  const statsQueued = document.getElementById("stats-queued");
  const statsCompleted = document.getElementById("stats-completed");
  const statsFailed = document.getElementById("stats-failed");
  const statusDot = document.getElementById("status-dot");
  const statusText = document.getElementById("status-text");
  const resetBtn = document.getElementById("reset-btn");
  const scanUiBtn = document.getElementById("scan-ui-btn");
  const clearLogsBtn = document.getElementById("clear-logs-btn");
  const logsEl = document.getElementById("logs");
  const refInput = document.getElementById("ref-input");
  const dropZone = document.getElementById("drop-zone");
  const previewWrap = document.getElementById("preview-wrap");
  const refPreview = document.getElementById("ref-preview");
  const clearRef = document.getElementById("clear-ref");
  const logMeta = document.getElementById("log-meta");

  let isAutomating = false;
  let isPaused = false;
  let refImageBase64 = null;
  let logLines = [];
  let lastErrSummary = "";

  const STORAGE_KEYS = {
    isAutomating: "flow_is_automating",
    isPaused: "flow_is_paused",
    promptsText: "flow_prompts_text",
    failedPromptsText: "flow_failed_prompts_text",
    aspectRatio: "flow_aspect_ratio",
    batchSize: "flow_batch_size",
    model: "flow_model",
    restDelay: "flow_rest_delay",
    iterations: "flow_iterations",
    refImage: "flow_ref_image",
    statsCompleted: "flow_stats_completed",
    statsFailed: "flow_stats_failed",
    lastError: "flow_last_error",
    jobIndex: "flow_job_index",
    logsText: "flow_logs_text"
  };

  function appendLog(text, level = "info") {
    const ts = new Date().toLocaleTimeString("en-GB", { hour12: false });
    const line = { ts, text: String(text || ""), level };
    logLines.push(line);
    if (logLines.length > 900) logLines = logLines.slice(-900);
    if (level === "err") lastErrSummary = String(text || "").slice(0, 120);
    renderLogs();
    chrome.storage.local.set({
      [STORAGE_KEYS.logsText]: logLines
        .map((l) => `[${l.ts}]${l.level === "err" ? " ERR" : l.level === "ok" ? " OK" : l.level === "dbg" ? " ·" : ""} ${l.text}`)
        .join("\n")
    });
  }

  function renderLogs() {
    if (!logsEl) return;
    logsEl.innerHTML = "";
    for (const l of logLines) {
      const div = document.createElement("div");
      div.className =
        l.level === "err"
          ? "log-err"
          : l.level === "ok"
            ? "log-ok"
            : l.level === "dbg"
              ? "log-dbg"
              : "log-info";
      div.textContent = `[${l.ts}] ${l.text}`;
      logsEl.appendChild(div);
    }
    logsEl.scrollTop = logsEl.scrollHeight;
    if (logMeta) {
      logMeta.textContent = lastErrSummary
        ? `Last issue: ${lastErrSummary}`
        : `${logLines.length} lines · clicks, probes, uploads, waits`;
      logMeta.style.color = lastErrSummary ? "var(--err)" : "";
    }
  }

  function clearLogs() {
    logLines = [];
    lastErrSummary = "";
    renderLogs();
    chrome.storage.local.set({ [STORAGE_KEYS.logsText]: "" });
  }

  function showLastError(msg, opts = {}) {
    const doLog = opts.log !== false;
    if (msg) {
      lastErrSummary = String(msg).slice(0, 120);
      if (doLog) appendLog(msg, "err");
      else if (logMeta) {
        logMeta.textContent = `Last issue: ${lastErrSummary}`;
        logMeta.style.color = "var(--err)";
      }
    } else {
      lastErrSummary = "";
      if (logMeta) {
        logMeta.textContent = `${logLines.length} lines · clicks, probes, uploads, waits`;
        logMeta.style.color = "";
      }
    }
  }

  function setStatus(kind, label) {
    statusDot.className = "dot";
    if (kind === "ok") statusDot.classList.add("ok");
    if (kind === "run") statusDot.classList.add("run");
    statusText.textContent = label;
  }

  function parsePromptBlocks(text) {
    return String(text || "")
      .split(/\n\s*\n/)
      .map((block) => block.replace(/\s+$/g, "").replace(/^\s+/g, "").trim())
      .filter(Boolean);
  }

  function quantityMultiplier() {
    const raw = String(batchSize?.value || "x1").toLowerCase().trim();
    const m = raw.match(/(\d+)/);
    const n = m ? parseInt(m[1], 10) : 1;
    return Math.max(1, Math.min(4, n || 1));
  }

  function updatePromptCount() {
    const blocks = parsePromptBlocks(promptsInput.value);
    const iters = Math.max(1, Math.min(999, parseInt(iterations?.value || "1", 10) || 1));
    const qty = quantityMultiplier();
    const images = blocks.length * iters * qty;
    if (blocks.length === 0) {
      promptBadge.textContent = "0";
    } else if (qty === 1 && iters === 1) {
      promptBadge.textContent = String(blocks.length);
    } else if (blocks.length === 1) {
      promptBadge.textContent = `${qty}×${iters}=${images}`;
    } else {
      promptBadge.textContent = `${blocks.length}×${qty}×${iters}=${images}`;
    }
    statsQueued.textContent = String(images);
  }

  function syncRunButtons() {
    if (!isAutomating) {
      toggleBtn.textContent = "Start";
      toggleBtn.classList.remove("stop");
      stopBtn.style.display = "none";
      return;
    }
    stopBtn.style.display = "block";
    if (isPaused) {
      toggleBtn.textContent = "Resume";
      toggleBtn.classList.remove("stop");
    } else {
      toggleBtn.textContent = "Pause";
      toggleBtn.classList.add("stop");
    }
  }

  function setRefPreview(dataUrl) {
    refImageBase64 = dataUrl || null;
    if (dataUrl) {
      refPreview.src = dataUrl;
      previewWrap.classList.add("show");
      dropZone.style.display = "none";
    } else {
      refPreview.src = "";
      previewWrap.classList.remove("show");
      dropZone.style.display = "block";
      refInput.value = "";
    }
  }

  function handleFile(file) {
    if (!file || !file.type.startsWith("image/")) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      setRefPreview(ev.target.result);
      saveToStorage();
    };
    reader.readAsDataURL(file);
  }

  function saveToStorage() {
    chrome.storage.local.set({
      [STORAGE_KEYS.promptsText]: promptsInput.value,
      [STORAGE_KEYS.aspectRatio]: aspectRatio.value,
      [STORAGE_KEYS.batchSize]: batchSize.value,
      [STORAGE_KEYS.model]: model.value,
      [STORAGE_KEYS.restDelay]: restDelay.value,
      [STORAGE_KEYS.iterations]: iterations.value,
      [STORAGE_KEYS.refImage]: refImageBase64
    });
  }

  async function getFlowTab() {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) return null;
    if (
      !tab.url ||
      !(tab.url.includes("labs.google") || tab.url.includes("flow.google.com"))
    ) {
      return null;
    }
    return tab;
  }

  function scanUiQuiet(tabId) {
    chrome.tabs.sendMessage(tabId, { action: "SCRAPE_FLOW_UI" }, (response) => {
      if (chrome.runtime.lastError || !response?.success || !response.report) {
        if (!isAutomating) setStatus("", "Refresh Flow tab");
        return;
      }
      const r = response.report;
      const c = r.composer?.editor;
      const plus = r.composer?.settingsPlus || r.composer?.settings;
      const tune = r.composer?.settingsFreeTune;
      const plusOk = !!(plus && (plus.rect?.w > 0 || plus.rect?.visible !== false) && (plus.rect?.w !== 0 || plus.aria));
      // Prefer live surface: visible plus chip OR free tune OR agent panel
      const surface = r.settingsSurface || {};
      const sOk =
        !!surface.plusChipVisible ||
        !!surface.tuneVisible ||
        !!surface.agentPanelOpen ||
        !!tune ||
        (plusOk && plus?.rect?.w > 0);
      const g = r.composer?.generate || r.sendButton;
      const parts = [
        c ? "composer✓" : "composer✗",
        sOk ? "settings✓" : "settings✗",
        g ? "send✓" : "send✗"
      ];
      if (!isAutomating) {
        const pref = surface.preferred || r.uiTier || "";
        setStatus(c && g ? "ok" : "", `${parts.join(" · ")}${pref ? ` · ${pref}` : ""}`);
      }
    });
  }

  function loadFromStorage() {
    chrome.storage.local.get(Object.values(STORAGE_KEYS), (result) => {
      if (result[STORAGE_KEYS.promptsText] != null) {
        promptsInput.value = result[STORAGE_KEYS.promptsText];
      }
      if (result[STORAGE_KEYS.logsText]) {
        const raw = String(result[STORAGE_KEYS.logsText]);
        logLines = raw
          .split("\n")
          .filter(Boolean)
          .map((line) => {
            const m = line.match(/^\[([^\]]+)\]\s*(.*)$/);
            const text = m ? m[2] : line;
            const level = /err|fail|error/i.test(text)
              ? "err"
              : /ok|done|download|settings ok/i.test(text)
                ? "ok"
                : "info";
            return { ts: m ? m[1] : "", text, level };
          });
        renderLogs();
      }
      if (result[STORAGE_KEYS.aspectRatio]) aspectRatio.value = result[STORAGE_KEYS.aspectRatio];
      if (result[STORAGE_KEYS.batchSize]) batchSize.value = result[STORAGE_KEYS.batchSize];
      if (result[STORAGE_KEYS.model]) model.value = result[STORAGE_KEYS.model];
      if (result[STORAGE_KEYS.restDelay]) restDelay.value = result[STORAGE_KEYS.restDelay];
      if (result[STORAGE_KEYS.iterations]) iterations.value = result[STORAGE_KEYS.iterations];
      if (result[STORAGE_KEYS.refImage]) setRefPreview(result[STORAGE_KEYS.refImage]);
      statsCompleted.textContent = String(result[STORAGE_KEYS.statsCompleted] || 0);
      statsFailed.textContent = String(result[STORAGE_KEYS.statsFailed] || 0);
      showLastError(result[STORAGE_KEYS.lastError] || "", { log: false });

      if (result[STORAGE_KEYS.isAutomating] === true) {
        isAutomating = true;
        isPaused = result[STORAGE_KEYS.isPaused] === true;
        syncRunButtons();
        setStatus("run", isPaused ? "Paused" : "Running");
      } else {
        cleanupStop();
      }
      updatePromptCount();
    });
  }

  async function checkTab() {
    try {
      const tab = await getFlowTab();
      if (!tab) {
        if (!isAutomating) setStatus("", "Open Flow");
        return;
      }
      chrome.tabs.sendMessage(tab.id, { action: "PING" }, (response) => {
        if (chrome.runtime.lastError) {
          if (!isAutomating) setStatus("", "Refresh Flow tab");
          return;
        }
        if (!isAutomating) scanUiQuiet(tab.id);
        else if (response?.status === "pong") {
          /* keep run status */
        }
      });
    } catch (_) {
      if (!isAutomating) setStatus("", "Disconnected");
    }
  }

  function cleanupStop() {
    isAutomating = false;
    isPaused = false;
    syncRunButtons();
    checkTab();
  }

  refInput.addEventListener("change", (e) => handleFile(e.target.files[0]));

  ["dragenter", "dragover", "dragleave", "drop"].forEach((name) => {
    dropZone.addEventListener(name, (e) => {
      e.preventDefault();
      e.stopPropagation();
    });
  });
  ["dragenter", "dragover"].forEach((name) => {
    dropZone.addEventListener(name, () => dropZone.classList.add("over"));
  });
  ["dragleave", "drop"].forEach((name) => {
    dropZone.addEventListener(name, () => dropZone.classList.remove("over"));
  });
  dropZone.addEventListener("drop", (e) => handleFile(e.dataTransfer.files[0]));

  clearRef.addEventListener("click", () => {
    setRefPreview(null);
    saveToStorage();
  });

  promptsInput.addEventListener("input", () => {
    updatePromptCount();
    saveToStorage();
  });
  aspectRatio.addEventListener("change", saveToStorage);
  batchSize.addEventListener("change", () => {
    updatePromptCount();
    saveToStorage();
  });
  model.addEventListener("change", saveToStorage);
  iterations.addEventListener("change", () => {
    const n = Math.max(1, Math.min(999, parseInt(iterations.value || "1", 10) || 1));
    iterations.value = String(n);
    updatePromptCount();
    saveToStorage();
  });
  iterations.addEventListener("input", updatePromptCount);
  restDelay.addEventListener("change", saveToStorage);

  toggleBtn.addEventListener("click", async () => {
    const tab = await getFlowTab();
    if (!tab?.id) {
      alert("Open a Google Flow project tab first.");
      return;
    }

    // Pause
    if (isAutomating && !isPaused) {
      chrome.tabs.sendMessage(tab.id, { action: "PAUSE_FLOW_AUTOMATION" }, () => {
        isPaused = true;
        syncRunButtons();
        setStatus("run", "Paused");
      });
      return;
    }

    // Resume
    if (isAutomating && isPaused) {
      chrome.tabs.sendMessage(tab.id, { action: "RESUME_FLOW_AUTOMATION" }, () => {
        isPaused = false;
        syncRunButtons();
        setStatus("run", "Running");
      });
      return;
    }

    // Start
    const prompts = parsePromptBlocks(promptsInput.value);
    if (!prompts.length) {
      alert("Add at least one prompt.\n\nSeparate multiple prompts with a blank line.");
      return;
    }

    const iters = Math.max(1, Math.min(999, parseInt(iterations.value || "1", 10) || 1));
    iterations.value = String(iters);
    const expanded = [];
    for (const p of prompts) {
      for (let i = 0; i < iters; i++) expanded.push(p);
    }

    chrome.tabs.sendMessage(
      tab.id,
      {
        action: "START_FLOW_AUTOMATION",
        prompts: expanded,
        aspectRatio: aspectRatio.value,
        batchSize: batchSize.value,
        model: model.value,
        restDelay: restDelay.value,
        iterations: iters,
        refImage: refImageBase64
      },
      (response) => {
        if (chrome.runtime.lastError) {
          alert("Can't reach Flow tab — refresh the page and try again.");
          return;
        }
        if (response?.success) {
          isAutomating = true;
          isPaused = false;
          syncRunButtons();
          showLastError("");
          appendLog(
            response.mode === "dom" ? "Started (DOM mode)" : "Started (CDP)",
            "ok"
          );
          setStatus(
            "run",
            response.mode === "dom" ? "Running (DOM)" : "Running"
          );
        } else {
          const err = response?.error || response?.message || "Start failed.";
          showLastError(err);
          alert(err);
        }
      }
    );
  });

  stopBtn.addEventListener("click", async () => {
    const tab = await getFlowTab();
    if (tab?.id) {
      chrome.tabs.sendMessage(tab.id, { action: "STOP_FLOW_AUTOMATION" }, () => {
        cleanupStop();
      });
    } else cleanupStop();
  });

  applySettingsBtn.addEventListener("click", async () => {
    const tab = await getFlowTab();
    if (!tab?.id) {
      alert("Open a Google Flow project tab first.");
      return;
    }
    setStatus("", "Applying settings…");
    chrome.tabs.sendMessage(
      tab.id,
      {
        action: "APPLY_SETTINGS_ONLY",
        aspectRatio: aspectRatio.value,
        batchSize: batchSize.value,
        model: model.value
      },
      (response) => {
        if (chrome.runtime.lastError) {
          alert("Can't reach Flow tab — refresh and try again.");
          return;
        }
        if (response?.success) {
          setStatus("ok", response.chipText ? `Chip: ${response.chipText}` : "Settings applied");
          appendLog(
            response.chipText
              ? `Settings applied · ${response.chipText}`
              : "Settings applied",
            "ok"
          );
          showLastError("");
        } else {
          const err = response?.error || "Apply settings failed";
          showLastError(err);
          setStatus("", "Settings failed");
        }
      }
    );
  });

  resetBtn.addEventListener("click", () => {
    if (!confirm("Reset prompts, reference, and stats?")) return;
    promptsInput.value = "";
    aspectRatio.value = "1:1";
    batchSize.value = "1x";
    model.value = "Nano Banana 2";
    iterations.value = "1";
    restDelay.value = "5";
    setRefPreview(null);
    statsCompleted.textContent = "0";
    statsFailed.textContent = "0";
    clearLogs();
    chrome.storage.local.set({
      [STORAGE_KEYS.promptsText]: "",
      [STORAGE_KEYS.failedPromptsText]: "",
      [STORAGE_KEYS.aspectRatio]: "1:1",
      [STORAGE_KEYS.batchSize]: "1x",
      [STORAGE_KEYS.model]: "Nano Banana 2",
      [STORAGE_KEYS.restDelay]: "5",
      [STORAGE_KEYS.iterations]: "1",
      [STORAGE_KEYS.refImage]: null,
      [STORAGE_KEYS.statsCompleted]: 0,
      [STORAGE_KEYS.statsFailed]: 0,
      [STORAGE_KEYS.jobIndex]: 0,
      [STORAGE_KEYS.isPaused]: false,
      [STORAGE_KEYS.logsText]: ""
    });
    updatePromptCount();
    checkTab();
  });

  clearLogsBtn.addEventListener("click", clearLogs);

  scanUiBtn.addEventListener("click", async () => {
    const tab = await getFlowTab();
    if (!tab?.id) {
      alert("Open a Google Flow project tab first.");
      return;
    }
    chrome.tabs.sendMessage(tab.id, { action: "SCRAPE_FLOW_UI" }, (response) => {
      if (chrome.runtime.lastError) {
        alert("Can't reach Flow tab — refresh the page and try again.");
        return;
      }
      if (response?.success && response.report) {
        const r = response.report;
        console.log("Farm Flow UI scan:", r);
        appendLog(
          `Scan UI · tier=${r.uiTier || "?"} · surface=${JSON.stringify(r.settingsSurface || {})}`,
          "dbg"
        );
        const c = r.composer?.editor;
        const surface = r.settingsSurface || {};
        const sOk =
          !!surface.plusChipVisible ||
          !!surface.tuneVisible ||
          !!r.composer?.settingsFreeTune ||
          !!(r.composer?.settingsPlus && r.composer.settingsPlus.rect?.w > 0);
        const g = r.composer?.generate;
        showLastError("");
        setStatus(
          c && g ? "ok" : "",
          [
            c ? "composer✓" : "composer✗",
            sOk ? "settings✓" : "settings✗",
            g ? "send✓" : "send✗",
            surface.preferred || r.uiTier || ""
          ]
            .filter(Boolean)
            .join(" · ")
        );
      } else {
        alert(response?.error || "Scan failed.");
      }
    });
  });

  chrome.tabs.onActivated.addListener(checkTab);
  chrome.tabs.onUpdated.addListener((_id, info) => {
    if (info.status === "complete") checkTab();
  });

  chrome.runtime.onMessage.addListener((message) => {
    if (message.action === "UPDATE_STATUS") {
      setStatus("", message.status);
      cleanupStop();
    }
    if (message.action === "UPDATE_TEXTAREA" && message.promptsText != null) {
      promptsInput.value = message.promptsText;
      updatePromptCount();
    }
    if (message.action === "AUTOMATION_PROGRESS") {
      if (message.paused === true) {
        isPaused = true;
        isAutomating = true;
        syncRunButtons();
      }
      if (message.paused === false && isAutomating) {
        isPaused = false;
        syncRunButtons();
      }
      if (message.statusText) {
        setStatus(isAutomating ? "run" : "", message.statusText);
        // Detailed lines come via FLOW_LOG — avoid duplicating every status tick
      }
      if (message.lastError != null && message.lastError !== "") {
        showLastError(message.lastError, { log: false });
      } else if (message.lastError === "") {
        showLastError("", { log: false });
      }
      if (message.stats) {
        if (message.stats.completed != null) {
          statsCompleted.textContent = String(message.stats.completed);
        }
        if (message.stats.failed != null) {
          statsFailed.textContent = String(message.stats.failed);
        }
      }
      if (message.remainingPromptsText != null) {
        if (message.remainingPromptsText.includes("@@@FARM_NEXT@@@")) {
          const left = message.remainingPromptsText
            .split("@@@FARM_NEXT@@@")
            .map((s) => s.trim())
            .filter(Boolean).length;
          const qty = quantityMultiplier();
          statsQueued.textContent = String(left * qty);
        } else {
          promptsInput.value = message.remainingPromptsText;
          updatePromptCount();
        }
      }
      if (message.isDone) {
        appendLog("Queue finished", "ok");
        cleanupStop();
      }
    }
    if (message.action === "FLOW_LOG") {
      appendLog(message.text || "", message.level || "info");
    }
  });

  loadFromStorage();
  checkTab();
});
