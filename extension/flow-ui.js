/**
 * Live Flow UI map
 *
 * PLUS (2026-09-16) — Settings trigger popover (.cdk-overlay-pane), no Save:
 *   - button[aria-label="Settings trigger"].settings-trigger-button
 *   - Image/Video, aspects, x1–x4, Select model family
 *
 * FREE / no-Plus (2026-09-17 AdsPower) — Agent settings side panel:
 *   - Plus chip often in DOM at 0×0; use tune button instead
 *   - button[aria-label="Settings"].agent-action-button (icon tune)
 *   - Root: flow-agent-panel  |  Save: button.settings-save-button
 *   - Never confirmation required; Image defaults via flow-toggles aria-labels
 */
(function (global) {
  const MAP = {
    version: "2026-09-17-plus-and-free-agent",
    aspectText: {
      "16:9": "16:9",
      "4:3": "4:3",
      "1:1": "1:1",
      "3:4": "3:4",
      "9:16": "9:16"
    },
    quantityMap: {
      "1x": "x1",
      x1: "x1",
      x2: "x2",
      x3: "x3",
      x4: "x4"
    }
  };

  function isVisible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return (
      r.width > 0 &&
      r.height > 0 &&
      style.visibility !== "hidden" &&
      style.display !== "none" &&
      style.opacity !== "0"
    );
  }

  function queryAllDeep(selector, root = document) {
    const out = [];
    const visit = (node) => {
      if (!node?.querySelectorAll) return;
      try {
        out.push(...node.querySelectorAll(selector));
      } catch (_) {}
      for (const el of node.querySelectorAll("*")) {
        if (el.shadowRoot) visit(el.shadowRoot);
      }
    };
    visit(root);
    return out;
  }

  function normText(s) {
    return String(s || "")
      .replace(/[\u200b\ufeff]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .toLowerCase();
  }

  function elementSummary(el) {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {
      tag: el.tagName,
      aria: el.getAttribute("aria-label") || "",
      text: (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 80),
      class: (el.className || "").toString().slice(0, 120),
      checked: el.getAttribute("aria-checked") || "",
      disabled: !!el.disabled || el.getAttribute("aria-disabled") === "true",
      rect: {
        top: Math.round(r.top),
        left: Math.round(r.left),
        w: Math.round(r.width),
        h: Math.round(r.height)
      }
    };
  }

  function isInTopChrome(el) {
    return !el || el.getBoundingClientRect().top < 90;
  }

  function isForbiddenClickTarget(el) {
    if (!el) return true;
    // Asset / settings overlays live near the top — do NOT treat as page chrome
    const inOverlay = !!el.closest?.(
      ".cdk-overlay-pane, mat-dialog-container, [role='dialog'], [role='menu'], flow-agent-panel, .mat-mdc-menu-panel"
    );
    if (!inOverlay && isInTopChrome(el)) return true;
    const aria = normText(el.getAttribute("aria-label"));
    const t = normText(el.textContent);
    // Exact short labels only — don't block "Search assets" input in overlays via includes("search")
    const forbiddenExact = [
      "account",
      "avatar",
      "profile",
      "google account",
      "sign out",
      "upgrade",
      "help",
      "home"
    ];
    if (forbiddenExact.some((f) => aria === f || t === f)) return true;
    if (aria.includes("google account") || aria.includes("account details")) return true;
    return false;
  }

  function findPromptEditor() {
    const pm = document.querySelector("div.ProseMirror[contenteditable='true']");
    if (pm && isVisible(pm)) return pm;
    for (const el of queryAllDeep('[contenteditable="true"]')) {
      if (!isVisible(el)) continue;
      if (el.classList?.contains("ProseMirror")) return el;
      const r = el.getBoundingClientRect();
      if (r.bottom > window.innerHeight * 0.5 && r.width > 80) return el;
    }
    return null;
  }

  function findComposerSettingsTrigger() {
    return (
      document.querySelector('button[aria-label="Settings trigger"]') ||
      document.querySelector("button.settings-trigger-button") ||
      null
    );
  }

  function findSubmitButton() {
    const btn =
      document.querySelector('button[aria-label="Start generation"]') ||
      document.querySelector("button.generate-icon-button");
    if (btn && isVisible(btn)) return btn;
    return null;
  }

  function findAddImageButton() {
    return (
      document.querySelector(
        'button[aria-label="Add ingredients to the prompt box"]'
      ) ||
      document.querySelector("button.add-menu-trigger") ||
      null
    );
  }

  function findEmptyStateActivator() {
    return Array.from(document.querySelectorAll("button, div, p, span")).find((n) => {
      if (!isVisible(n)) return false;
      const t = normText(n.textContent);
      return t.includes("start creating or drop media");
    });
  }

  /** Settings popover root (Material CDK). */
  function findSettingsOverlay() {
    const panes = Array.from(
      document.querySelectorAll(".cdk-overlay-pane")
    ).filter(isVisible);
    // Prefer pane that contains aspect / quantity toggles
    const scored = panes
      .map((pane) => {
        const t = normText(pane.innerText);
        let s = 0;
        if (t.includes("16:9") && t.includes("3:4")) s += 10;
        if (/\bx1\b/.test(t) && /\bx2\b/.test(t)) s += 8;
        if (t.includes("select model") || t.includes("nano banana")) s += 5;
        if (t.includes("image") && t.includes("video")) s += 4;
        return { pane, s };
      })
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s);
    return scored[0]?.pane || null;
  }

  function isSettingsOverlayOpen() {
    return !!findSettingsOverlay();
  }

  /** Clickable radio inside overlay whose visible text contains needle. */
  function findOverlayRadio(overlay, needle, opts = {}) {
    if (!overlay) return null;
    const want = normText(needle);
    const exact = opts.exact === true;
    const radios = Array.from(
      overlay.querySelectorAll(
        'button[role="radio"], button.mat-button-toggle-button, mat-button-toggle button'
      )
    ).filter(isVisible);

    const matches = radios.filter((btn) => {
      const t = normText(btn.textContent);
      if (exact) return t === want || t.endsWith(want) || t.split(" ").pop() === want;
      return t.includes(want);
    });

    if (!matches.length) return null;
    // Prefer the actual button[role=radio] over wrappers
    matches.sort((a, b) => {
      const sa = a.getAttribute("role") === "radio" ? 2 : 0;
      const sb = b.getAttribute("role") === "radio" ? 2 : 0;
      return sb - sa || a.getBoundingClientRect().width - b.getBoundingClientRect().width;
    });
    return matches[0];
  }

  function findModelFamilyButton(overlay) {
    if (!overlay) return null;
    return (
      overlay.querySelector('button[aria-label="Select model family"]') ||
      Array.from(overlay.querySelectorAll("button")).find((b) => {
        if (!isVisible(b)) return false;
        const aria = normText(b.getAttribute("aria-label"));
        const t = normText(b.textContent);
        return (
          aria.includes("select model") ||
          (t.includes("nano banana") && t.includes("arrow_drop_down")) ||
          (t.includes("imagen") && t.includes("arrow_drop_down"))
        );
      }) ||
      null
    );
  }

  function findModelMenuOption(wantModel) {
    const want = normText(wantModel);
    // Model menu is usually another cdk-overlay-pane
    const panes = Array.from(document.querySelectorAll(".cdk-overlay-pane, [role='menu']")).filter(
      isVisible
    );
    for (const pane of panes) {
      const items = Array.from(
        pane.querySelectorAll(
          "[role='menuitem'], button, mat-option, .mat-mdc-menu-item"
        )
      ).filter(isVisible);
      const hit = items.find((el) => normText(el.textContent).includes(want));
      if (hit) return hit;
    }
    // Fallback whole document
    return Array.from(
      document.querySelectorAll("[role='menuitem'], .mat-mdc-menu-item, button")
    ).find((el) => isVisible(el) && normText(el.textContent).includes(want));
  }

  function editorPlainText(el) {
    if (!el) return "";
    const clone = el.cloneNode(true);
    clone
      .querySelectorAll(
        '[aria-hidden="true"], .ProseMirror-placeholder, .ProseMirror-trailingBreak, [contenteditable="false"]'
      )
      .forEach((n) => n.remove());
    let t = (clone.innerText || clone.textContent || "")
      .replace(/[\u200b\ufeff]/g, "")
      .replace(/\s+/g, " ")
      .trim();
    if (t.toLowerCase().startsWith("what do you want to create")) return "";
    return t;
  }

  function pageSaysThinking() {
    const nodes = Array.from(document.querySelectorAll("div, span, p, button")).find((el) => {
      if (!isVisible(el)) return false;
      const t = normText(el.textContent)
        .replace(/\u2026/g, "...")
        .replace(/\.+$/, (m) => (m.length >= 3 ? "..." : m));
      if (t.length > 80) return false;
      return (
        t === "thinking..." ||
        t === "thinking" ||
        t === "generating..." ||
        t === "generating" ||
        t.startsWith("thinking")
      );
    });
    // Agent composer swaps Send for Stop while running
    const stopBtn = Array.from(document.querySelectorAll("button")).find((el) => {
      if (!isVisible(el)) return false;
      const aria = normText(el.getAttribute("aria-label"));
      const t = normText(el.textContent);
      return t === "stop" || aria.includes("stop generation") || aria === "stop";
    });
    return !!nodes || !!stopBtn || !!document.querySelector('[role="progressbar"]');
  }

  /** Agent-mode activity (no classic Thinking… toast). */
  function pageSaysAgentActivity() {
    const hits = [
      "i'm going to",
      "i am going to",
      "let me ",
      "working on",
      "i'll ",
      "i will ",
      "changing the",
      "generating",
      "looking at",
      "updating the"
    ];
    for (const el of document.querySelectorAll("div, span, p, li")) {
      if (!isVisible(el)) continue;
      const t = normText(el.textContent);
      if (t.length < 8 || t.length > 220) continue;
      if (hits.some((h) => t.includes(h))) return true;
    }
    return false;
  }

  function pageSaysAgentFailed() {
    for (const el of document.querySelectorAll("div, span, p, button")) {
      if (!isVisible(el)) continue;
      const t = normText(el.textContent);
      if (t.length > 180) continue;
      if (
        t.includes("the agent failed") ||
        t.includes("agent failed") ||
        (t.includes("failed") && t.includes("please try again"))
      ) {
        return true;
      }
    }
    return false;
  }

  function findAgentTryAgainButton() {
    for (const el of document.querySelectorAll("button, a, [role='button']")) {
      if (!isVisible(el)) continue;
      const t = normText(el.textContent || el.getAttribute("aria-label"));
      if (t === "try again" || t.includes("try again") || t === "retry") return el;
    }
    return null;
  }

  function isFlowMediaImg(img) {
    if (!img || !isVisible(img)) return false;
    const r = img.getBoundingClientRect();
    if (r.width < 80 || r.height < 80) return false;
    const alt = normText(img.alt);
    if (alt.includes("avatar") || alt.includes("icon")) return false;
    const src = img.currentSrc || img.src || "";
    if (alt.includes("tile displaying") || alt.includes("generated image")) return true;
    if (src.includes("flow-content.google")) return true;
    return false;
  }

  function listMediaFingerprints() {
    return Array.from(document.querySelectorAll("img"))
      .filter(isFlowMediaImg)
      .map((img) => img.currentSrc || img.src)
      .filter(Boolean);
  }

  function findNewMediaImage(baselineSet) {
    for (const img of document.querySelectorAll("img")) {
      if (!isFlowMediaImg(img)) continue;
      const src = img.currentSrc || img.src || "";
      if (src && !baselineSet.has(src)) return img;
    }
    return null;
  }

  /** Gallery tiles that show Failed / Failed to load image. */
  function findFailedGenerationTiles() {
    const hits = [];
    const seen = new Set();
    const nodes = Array.from(
      document.querySelectorAll("div, section, article, li, [role='listitem'], [role='button']")
    );
    for (const el of nodes) {
      if (!isVisible(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 120 || r.height < 100) continue;
      if (r.width > window.innerWidth * 0.85 || r.height > window.innerHeight * 0.85) {
        continue;
      }
      // Prefer leaf-ish tiles: text should be short and clearly a failure card
      const raw = (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
      if (raw.length < 6 || raw.length > 180) continue;
      const t = normText(raw);
      const isFail =
        t.includes("failed to load image") ||
        t.includes("failed to generate") ||
        (t.startsWith("failed") && (t.includes("load") || t.includes("image") || t.includes("generate")));
      if (!isFail) continue;

      // Walk up a bit to a stable tile root (has retry btn nearby)
      let root = el;
      for (let i = 0; i < 5 && root.parentElement; i++) {
        const p = root.parentElement;
        const pr = p.getBoundingClientRect();
        if (pr.width > window.innerWidth * 0.7 || pr.height > window.innerHeight * 0.7) break;
        if (pr.width >= r.width && pr.height >= r.height && pr.width < 900) {
          root = p;
        } else break;
      }
      if (seen.has(root)) continue;
      seen.add(root);
      hits.push(root);
      if (hits.length >= 8) break;
    }
    return hits;
  }

  function findFailedTileRetryButton(tileRoot) {
    const roots = tileRoot ? [tileRoot] : findFailedGenerationTiles();
    const searchIn = (root) => {
      if (!root) return null;
      const buttons = Array.from(
        root.querySelectorAll("button, [role='button'], a")
      ).filter(isVisible);
      const scored = buttons
        .map((b) => {
          const aria = normText(b.getAttribute("aria-label"));
          const title = normText(b.getAttribute("title"));
          const t = normText(b.textContent);
          const blob = `${aria} ${title} ${t}`;
          let s = 0;
          if (/retry|try again|reload|regenerate/.test(blob)) s += 10;
          if (/refresh|replay|autorenew|restart_alt|sync|cached/.test(blob)) s += 8;
          // Icon-only refresh in corner — small square button
          const r = b.getBoundingClientRect();
          if (s === 0 && r.width <= 48 && r.height <= 48 && /refresh|replay|sync|autorenew/.test(t)) {
            s += 6;
          }
          return { b, s };
        })
        .filter((x) => x.s > 0)
        .sort((a, b) => b.s - a.s);
      return scored[0]?.b || null;
    };

    for (const root of roots) {
      const btn = searchIn(root);
      if (btn) return btn;
    }
    // Global fallback near "Failed to load image"
    const failLabel = Array.from(document.querySelectorAll("div, span, p")).find((el) => {
      if (!isVisible(el)) return false;
      const t = normText(el.textContent);
      return t.includes("failed to load image") || t === "failed";
    });
    if (failLabel) {
      let root = failLabel;
      for (let i = 0; i < 6 && root.parentElement; i++) root = root.parentElement;
      return searchIn(root);
    }
    return null;
  }

  function readSettingsChipText() {
    const chip = findComposerSettingsTrigger();
    return chip ? (chip.textContent || "").replace(/\s+/g, " ").trim() : "";
  }

  function settingsChipMatches(settings) {
    const t = normText(readSettingsChipText());
    const aspect = settings.aspectRatio || "";
    const qty = MAP.quantityMap[settings.batchSize] || settings.batchSize || "x1";
    const model = settings.model || "";
    const aspectOk = !aspect || t.includes(aspect.toLowerCase()) || t.includes(
      aspect === "16:9"
        ? "crop_16_9"
        : aspect === "4:3"
          ? "crop_landscape"
          : aspect === "1:1"
            ? "crop_square"
            : aspect === "3:4"
              ? "crop_portrait"
              : aspect === "9:16"
                ? "crop_9_16"
                : aspect
    );
    const qtyOk = t.includes(normText(qty));
    const modelOk =
      !model ||
      t.includes(normText(model)) ||
      (normText(model).includes("pro") && t.includes("pro")) ||
      (normText(model).includes("banana 2") && t.includes("banana 2"));
    return { aspectOk, qtyOk, modelOk, chipText: readSettingsChipText() };
  }

  function scrapeFlowUI() {
    const editor = findPromptEditor();
    const overlay = findSettingsOverlay();
    const agentPanel = findAgentSettingsPanel();
    const report = {
      scrapedAt: new Date().toISOString(),
      mapVersion: MAP.version,
      url: location.href,
      uiTier: detectUiTier(),
      settingsSurface: inspectSettingsSurface(),
      composer: {
        editor: elementSummary(editor),
        settingsPlus: elementSummary(findComposerSettingsTrigger()),
        settingsFreeTune: elementSummary(findAgentTuneButton()),
        generate: elementSummary(findSubmitButton()),
        add: elementSummary(findAddImageButton()),
        agentChip: elementSummary(findAgentModeChip())
      },
      settingsOverlayOpen: !!overlay,
      settingsOverlay: overlay
        ? {
            text: (overlay.innerText || "").slice(0, 500),
            radios: Array.from(
              overlay.querySelectorAll('button[role="radio"]')
            )
              .filter(isVisible)
              .map(elementSummary)
          }
        : null,
      agentSettingsOpen: !!agentPanel,
      agentSettings: agentPanel
        ? {
            text: (agentPanel.innerText || "").slice(0, 800),
            neverChecked: (() => {
              const n = findAgentNeverRadio(agentPanel);
              return !!(
                n &&
                (n.classList.contains("mat-mdc-radio-checked") ||
                  n.querySelector?.(".mat-mdc-radio-checked"))
              );
            })()
          }
        : null
    };
    console.log("Farm Flow UI scrape:", report);
    return report;
  }

  // ── Free / Agent settings (2026-09-17) ──

  function findAgentModeChip() {
    return (
      Array.from(document.querySelectorAll("button.agent-mode-chip")).find(isVisible) ||
      Array.from(document.querySelectorAll("button")).find((b) => {
        if (!isVisible(b)) return false;
        return normText(b.textContent) === "agent";
      }) ||
      null
    );
  }

  function isAgentModeActive() {
    const chip = findAgentModeChip();
    if (!chip) return false;
    return (
      chip.getAttribute("aria-pressed") === "true" ||
      chip.classList.contains("agent-mode-chip-checked")
    );
  }

  /** Visible Plus 🍌 chip (not the 0×0 free-account stub). */
  function findVisiblePlusSettingsChip() {
    const chip = findComposerSettingsTrigger();
    return chip && isVisible(chip) ? chip : null;
  }

  function findAgentTuneButton() {
    const byAria = Array.from(document.querySelectorAll("button")).find((b) => {
      if (!isVisible(b)) return false;
      const aria = normText(b.getAttribute("aria-label"));
      if (aria !== "settings") return false;
      return (
        b.classList.contains("agent-action-button") ||
        normText(b.textContent) === "tune"
      );
    });
    if (byAria) return byAria;
    return (
      Array.from(document.querySelectorAll("button.agent-action-button")).find((b) => {
        if (!isVisible(b)) return false;
        return normText(b.textContent).includes("tune");
      }) || null
    );
  }

  function findAgentSettingsPanel() {
    const custom = document.querySelector("flow-agent-panel");
    if (custom && isVisible(custom)) return custom;
    const title = Array.from(document.querySelectorAll("h2.header-title, h1, h2, h3")).find(
      (el) => isVisible(el) && normText(el.textContent) === "agent settings"
    );
    if (!title) return null;
    return title.closest("flow-agent-panel") || title.closest(".settings-content")?.parentElement || title.parentElement;
  }

  function isAgentSettingsOpen() {
    return !!findAgentSettingsPanel();
  }

  function findAgentNeverRadio(panel) {
    const root = panel || findAgentSettingsPanel() || document;
    return (
      Array.from(root.querySelectorAll("mat-radio-button.radio-item, mat-radio-button")).find(
        (el) => {
          if (!isVisible(el)) return false;
          const t = normText(el.textContent);
          return t.startsWith("never") && t.includes("credit");
        }
      ) ||
      Array.from(root.querySelectorAll("label, mat-radio-button")).find((el) => {
        if (!isVisible(el)) return false;
        const t = normText(el.textContent);
        return t.startsWith("never") && (t.includes("generate") || t.includes("credit"));
      }) ||
      null
    );
  }

  function findAgentImageToggles(kind) {
    const panel = findAgentSettingsPanel();
    if (!panel) return null;
    const aria =
      kind === "aspect"
        ? "image generation default aspect ratio"
        : kind === "quantity"
          ? "image generation default output count"
          : "";
    if (!aria) return null;
    return (
      Array.from(panel.querySelectorAll("flow-toggles")).find(
        (el) => normText(el.getAttribute("aria-label")) === aria
      ) || null
    );
  }

  function findAgentImageRadio(kind, needle, opts = {}) {
    const group = findAgentImageToggles(kind);
    if (!group) return null;
    const want = normText(needle);
    const exact = opts.exact === true;
    const radios = Array.from(
      group.querySelectorAll('button[role="radio"], button.mat-button-toggle-button')
    ).filter(isVisible);
    const matches = radios.filter((btn) => {
      const t = normText(btn.textContent);
      if (exact) return t === want || t.split(" ").pop() === want;
      return t.includes(want);
    });
    if (!matches.length) return null;
    matches.sort((a, b) => {
      const sa = a.getAttribute("role") === "radio" ? 2 : 0;
      const sb = b.getAttribute("role") === "radio" ? 2 : 0;
      return sb - sa;
    });
    return matches[0];
  }

  function findAgentImageModelButton(panel) {
    const root = panel || findAgentSettingsPanel();
    if (!root) return null;
    return (
      root.querySelector(
        'button[aria-label="Image generation default model"], button.image-model-picker-button'
      ) || null
    );
  }

  function findAgentSaveButton(panel) {
    const root = panel || findAgentSettingsPanel() || document;
    const byClass =
      root.querySelector("button.settings-save-button") ||
      document.querySelector("flow-agent-panel button.settings-save-button");
    if (byClass) return byClass;
    return (
      Array.from(root.querySelectorAll("button")).find((b) => {
        return normText(b.textContent) === "save";
      }) ||
      Array.from(document.querySelectorAll("flow-agent-panel button, button")).find(
        (b) => {
          if (normText(b.textContent) !== "save") return false;
          return !!b.closest("flow-agent-panel, .settings-content, .save-container");
        }
      ) ||
      null
    );
  }

  /**
   * Inspect which settings UI the page is showing right now.
   * Not subscription-based: free narrow viewports often get the same
   * 🍌 popover as Plus; free wide viewports use Agent panel (tune).
   */
  function inspectSettingsSurface() {
    const plusChip = findVisiblePlusSettingsChip();
    const tune = findAgentTuneButton();
    const panelOpen = !!findAgentSettingsPanel();
    const overlayOpen = !!findSettingsOverlay();
    let preferred = "unknown";
    if (panelOpen) preferred = "agent-panel";
    else if (overlayOpen) preferred = "popover";
    else if (plusChip && !tune) preferred = "popover";
    else if (tune && !plusChip) preferred = "agent-panel";
    else if (plusChip) preferred = "popover"; // narrow free: chip visible → popover
    else if (tune) preferred = "agent-panel";
    else if (isAgentModeActive()) preferred = "agent-panel";

    return {
      viewport: { w: window.innerWidth, h: window.innerHeight },
      plusChipVisible: !!plusChip,
      tuneVisible: !!tune,
      agentPanelOpen: panelOpen,
      popoverOpen: overlayOpen,
      agentMode: isAgentModeActive(),
      preferred
    };
  }

  /**
   * Preferred settings surface for this layout (sync heuristic).
   * Values: "popover" | "agent-panel" | "unknown"
   * Legacy aliases: plus≈popover, free≈agent-panel
   */
  function detectUiTier() {
    const p = inspectSettingsSurface().preferred;
    return p;
  }

  /** @deprecated use detectUiTier / inspectSettingsSurface */
  function detectSubscriptionGuess() {
    const p = detectUiTier();
    if (p === "popover") return "plus";
    if (p === "agent-panel") return "free";
    return "unknown";
  }

  // Back-compat aliases used by older content.js
  function findNeverConfirmationCard() {
    return findAgentNeverRadio();
  }
  function findSaveButton() {
    return findAgentSaveButton() || null;
  }
  function findSettingsChip(label) {
    return findOverlayRadio(findSettingsOverlay(), label);
  }
  function findModelMenuTrigger() {
    return findModelFamilyButton(findSettingsOverlay());
  }
  function findModelOption(wantModel) {
    return findModelMenuOption(wantModel);
  }
  function getComposerRect(editor) {
    const ed = editor || findPromptEditor();
    if (ed) return ed.getBoundingClientRect();
    return {
      top: window.innerHeight * 0.55,
      bottom: window.innerHeight,
      left: 0,
      right: window.innerWidth,
      width: window.innerWidth,
      height: window.innerHeight * 0.45
    };
  }
  function isInComposerBand() {
    return true;
  }

  global.FarmFlowUI = {
    MAP,
    isVisible,
    queryAllDeep,
    isForbiddenClickTarget,
    isInTopChrome,
    isInComposerBand,
    findPromptEditor,
    findSubmitButton,
    findComposerSettingsTrigger,
    findVisiblePlusSettingsChip,
    findAddImageButton,
    findEmptyStateActivator,
    findSettingsOverlay,
    isSettingsOverlayOpen,
    isAgentSettingsOpen,
    findOverlayRadio,
    findModelFamilyButton,
    findModelMenuOption,
    findNeverConfirmationCard,
    findSaveButton,
    findSettingsChip,
    findModelMenuTrigger,
    findModelOption,
    findAgentModeChip,
    isAgentModeActive,
    findAgentTuneButton,
    findAgentSettingsPanel,
    findAgentNeverRadio,
    findAgentImageToggles,
    findAgentImageRadio,
    findAgentImageModelButton,
    findAgentSaveButton,
    inspectSettingsSurface,
    detectUiTier,
    detectSubscriptionGuess,
    editorPlainText,
    pageSaysThinking,
    pageSaysAgentActivity,
    pageSaysAgentFailed,
    findAgentTryAgainButton,
    listMediaFingerprints,
    findNewMediaImage,
    isFlowMediaImg,
    findFailedGenerationTiles,
    findFailedTileRetryButton,
    readSettingsChipText,
    settingsChipMatches,
    getComposerRect,
    scrapeFlowUI,
    elementSummary
  };
})(typeof globalThis !== "undefined" ? globalThis : window);
