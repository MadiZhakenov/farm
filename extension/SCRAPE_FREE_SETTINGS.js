/**
 * Farm Flow — FREE tier SETTINGS deep scrape (pass 2)
 *
 * Pass 1 showed: Plus "Settings trigger" chip is in DOM but 0×0 (hidden).
 * Real free controls live under Agent bar:
 *   - chip "Agent" (pressed)
 *   - button[aria-label="Settings"] with icon "tune"
 *   - button[aria-label="Start generation"] / arrow_forward
 *
 * Paste in Console on the SAME free Flow project tab.
 * Downloads farm-flow-FREE-settings.json
 */
(async () => {
  const TAG = "FARM_FLOW_FREE_SETTINGS";
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const vis = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return (
      r.width > 2 &&
      r.height > 2 &&
      s.visibility !== "hidden" &&
      s.display !== "none" &&
      Number(s.opacity) !== 0
    );
  };

  const txt = (el, n = 240) =>
    (el?.innerText || el?.textContent || "")
      .replace(/[\u200b\ufeff]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, n);

  const sum = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const icons = [...el.querySelectorAll(".google-symbols, .material-symbols-outlined, .material-icons")]
      .map((n) => txt(n, 40))
      .filter(Boolean)
      .slice(0, 12);
    return {
      tag: el.tagName,
      role: el.getAttribute("role") || "",
      type: el.getAttribute("type") || "",
      aria: el.getAttribute("aria-label") || "",
      ariaPressed: el.getAttribute("aria-pressed") || "",
      ariaChecked: el.getAttribute("aria-checked") || "",
      ariaSelected: el.getAttribute("aria-selected") || "",
      ariaExpanded: el.getAttribute("aria-expanded") || "",
      disabled: !!(el.disabled || el.getAttribute("aria-disabled") === "true"),
      text: txt(el, 200),
      class: String(el.className || "").slice(0, 220),
      icons,
      rect: {
        t: Math.round(r.top),
        l: Math.round(r.left),
        w: Math.round(r.width),
        h: Math.round(r.height),
        visible: vis(el)
      }
    };
  };

  const clickSafe = async (el, wait = 1200) => {
    if (!el) return false;
    try {
      el.scrollIntoView({ block: "center", inline: "nearest" });
      el.focus?.();
      el.click();
      await sleep(wait);
      return true;
    } catch (_) {
      return false;
    }
  };

  const escapeClose = async () => {
    for (let i = 0; i < 3; i++) {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", code: "Escape", keyCode: 27, bubbles: true })
      );
      await sleep(250);
    }
  };

  const collectOverlays = () =>
    [...document.querySelectorAll(
      ".cdk-overlay-pane, mat-dialog-container, [role='dialog'], .mat-mdc-menu-panel, [role='menu'], [role='listbox'], .mat-mdc-dialog-surface"
    )]
      .filter(vis)
      .map((pane) => {
        const interactive = [
          ...pane.querySelectorAll(
            "button,[role='button'],[role='tab'],[role='radio'],[role='option'],[role='menuitem'],[role='switch'],[role='checkbox'],input,label,a,mat-button-toggle,mat-radio-button,mat-option,.mat-mdc-menu-item,mat-slide-toggle,mat-checkbox"
          )
        ]
          .filter(vis)
          .map(sum);
        return {
          root: sum(pane),
          headings: [...pane.querySelectorAll("h1,h2,h3,h4,.mat-mdc-dialog-title,[role='heading']")]
            .filter(vis)
            .map((h) => txt(h, 160)),
          fullText: txt(pane, 8000),
          interactive,
          // Explicit probes for adapter
          probes: {
            hasQuantity: /\b(?:x[1-4]|[1-4]x)\b/i.test(txt(pane, 8000)),
            quantityTokens: (txt(pane, 8000).match(/\b(?:x[1-4]|[1-4]x)\b/gi) || []).slice(0, 20),
            aspects: ["16:9", "4:3", "1:1", "3:4", "9:16"].filter((r) =>
              txt(pane, 8000).includes(r)
            ),
            cropIcons: (txt(pane, 8000).match(/crop_(?:16_9|landscape|square|portrait|9_16)/gi) || []).slice(
              0,
              20
            ),
            models: (txt(pane, 8000).match(/nano banana(?:\s*(?:pro|2))?|imagen\s*4|veo|gemini/gi) || []).slice(
              0,
              30
            ),
            hasSave: /\bsave\b/i.test(txt(pane, 8000)),
            hasNever: /\bnever\b/i.test(txt(pane, 8000)),
            hasImageVideo: /image/i.test(txt(pane, 8000)) && /video/i.test(txt(pane, 8000)),
            hasCredits: /credit/i.test(txt(pane, 8000)),
            hasUpgrade: /upgrade|plus|subscribe/i.test(txt(pane, 8000))
          }
        };
      });

  const findByAria = (label) =>
    [...document.querySelectorAll("button, [role='button'], a")].find(
      (el) => vis(el) && (el.getAttribute("aria-label") || "") === label
    );

  const findTuneSettings = () =>
    findByAria("Settings") ||
    [...document.querySelectorAll("button")].find((b) => {
      if (!vis(b)) return false;
      const t = txt(b, 40).toLowerCase();
      const a = (b.getAttribute("aria-label") || "").toLowerCase();
      return (a === "settings" || t === "tune") && b.className.includes("agent-action");
    });

  const findAgentChip = () =>
    [...document.querySelectorAll("button")].find((b) => {
      if (!vis(b)) return false;
      return /^agent$/i.test(txt(b, 40)) || b.classList.contains("agent-mode-chip");
    });

  // Mode chips near composer (Create / Agent / etc.)
  const modeChips = [...document.querySelectorAll("button, [role='tab'], [role='radio']")]
    .filter((el) => {
      if (!vis(el)) return false;
      const r = el.getBoundingClientRect();
      if (r.bottom < innerHeight * 0.4) return false;
      const t = txt(el, 60);
      return /agent|create|image|video|frames|ingredients/i.test(t) || /chip|mode/i.test(el.className);
    })
    .map(sum);

  await escapeClose();

  // Snapshot Plus chip vs Free tune
  const plusChip =
    document.querySelector('button[aria-label="Settings trigger"]') ||
    document.querySelector("button.settings-trigger-button");
  const tuneBtn = findTuneSettings();
  const agentChip = findAgentChip();
  const agentInstructions = findByAria("Agent instructions");
  const generate =
    document.querySelector('button[aria-label="Start generation"]') ||
    document.querySelector("button.generate-icon-button");
  const expand = findByAria("Expand");

  const baseline = {
    plusSettingsTrigger: sum(plusChip),
    freeTuneSettings: sum(tuneBtn),
    agentChip: sum(agentChip),
    agentInstructions: sum(agentInstructions),
    generate: sum(generate),
    expand: sum(expand),
    modeChips
  };

  // ── A) Open FREE Settings via tune ──
  let tuneOpened = false;
  let overlaysAfterTune = [];
  if (tuneBtn) {
    tuneOpened = await clickSafe(tuneBtn, 1500);
    overlaysAfterTune = collectOverlays();
  }

  // If a nested control looks like model / aspect — click first promising radio / dropdown
  let nestedClicks = [];
  if (overlaysAfterTune.length) {
    const pane = overlaysAfterTune[0];
    const candidates = (pane.interactive || []).filter((it) => {
      const blob = `${it.aria} ${it.text}`.toLowerCase();
      return (
        /model|aspect|ratio|output|quantity|image|video|nano|imagen|confirmation|never|always|ask/i.test(
          blob
        ) || it.role === "radio"
      );
    });

    // Click model-like button if present (open submenu), then re-collect
    const modelLike = [...document.querySelectorAll("button, [role='menuitem'], [role='combobox']")].find(
      (b) => {
        if (!vis(b)) return false;
        const blob = `${b.getAttribute("aria-label") || ""} ${txt(b, 80)}`.toLowerCase();
        return /select model|model family|nano banana|imagen|arrow_drop_down/.test(blob);
      }
    );
    if (modelLike) {
      await clickSafe(modelLike, 1000);
      nestedClicks.push({ kind: "modelLike", el: sum(modelLike), overlays: collectOverlays() });
      await escapeClose();
      // reopen tune for clean state
      if (tuneBtn) {
        await clickSafe(tuneBtn, 1200);
        overlaysAfterTune = collectOverlays();
      }
    }

    nestedClicks.push({ kind: "candidates", list: candidates.slice(0, 40) });
  }

  await escapeClose();

  // ── B) Click Agent chip (maybe opens mode menu) ──
  let agentChipOverlays = [];
  if (agentChip) {
    await clickSafe(agentChip, 1000);
    agentChipOverlays = collectOverlays();
    await escapeClose();
  }

  // ── C) Tile grid settings (top bar settings_2) — NOT composer, but document ──
  let tileGridOverlays = [];
  const tileGrid = findByAria("Tile grid settings");
  if (tileGrid) {
    await clickSafe(tileGrid, 900);
    tileGridOverlays = collectOverlays();
    await escapeClose();
  }

  // ── D) Agent instructions button ──
  let agentInstrOverlays = [];
  if (agentInstructions) {
    await clickSafe(agentInstructions, 900);
    agentInstrOverlays = collectOverlays();
    await escapeClose();
  }

  // Flatten probes
  const allProbeText = [
    ...overlaysAfterTune,
    ...agentChipOverlays,
    ...tileGridOverlays,
    ...agentInstrOverlays
  ]
    .map((o) => o.fullText)
    .join("\n");

  const summary = {
    freeSettingsOpened: tuneOpened && overlaysAfterTune.length > 0,
    plusChipVisible: !!(plusChip && vis(plusChip)),
    plusChipInDomZeroSize: !!(plusChip && !vis(plusChip)),
    quantityPresentAnywhere: /\b(?:x[1-4]|[1-4]x)\b/i.test(allProbeText),
    aspectsFound: ["16:9", "4:3", "1:1", "3:4", "9:16"].filter((r) => allProbeText.includes(r)),
    modelsFound: (allProbeText.match(/nano banana(?:\s*(?:pro|2))?|imagen\s*4|veo/gi) || []).slice(0, 20),
    hasSave: /\bsave\b/i.test(allProbeText),
    hasNeverConfirmation: /\bnever\b/i.test(allProbeText),
    expectCountShouldBe: 1
  };

  const report = {
    scrapedAt: new Date().toISOString(),
    pass: 2,
    url: location.href,
    viewport: { w: innerWidth, h: innerHeight },
    summary,
    baseline,
    tuneSettings: {
      opened: tuneOpened,
      trigger: sum(tuneBtn),
      overlays: overlaysAfterTune,
      nestedClicks
    },
    agentChipMenu: agentChipOverlays,
    tileGridSettings: tileGridOverlays,
    agentInstructions: agentInstrOverlays,
    adapterHints: [
      "Use button[aria-label='Settings'] (tune) for free settings — NOT Settings trigger.",
      "Keep Plus applyComposerSettings() but disable when freeTune path detected.",
      "Force expectCount=1 on free; skip quantity radios.",
      "Agent mode chip is pressed — confirm settings dialog contents in tuneSettings.overlays."
    ]
  };

  console.log(`%c${TAG}`, "color:#06c;font-weight:bold", report);
  console.table(summary);
  console.log(
    `${TAG} tune overlay texts:`,
    overlaysAfterTune.map((o) => ({
      headings: o.headings,
      probes: o.probes,
      interactive: o.interactive.map((i) => ({
        aria: i.aria,
        text: i.text,
        role: i.role,
        checked: i.ariaChecked || i.ariaPressed,
        icons: i.icons
      }))
    }))
  );

  const json = JSON.stringify(report, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "farm-flow-FREE-settings.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);

  try {
    await navigator.clipboard.writeText(json);
    console.log(`${TAG}: downloaded + clipboard OK`);
  } catch (_) {
    console.log(`${TAG}: downloaded farm-flow-FREE-settings.json`);
  }

  await escapeClose();
  return summary;
})();
