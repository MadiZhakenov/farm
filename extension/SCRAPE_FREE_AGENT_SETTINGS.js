/**
 * Farm Flow — FREE Agent Settings scrape (pass 3)
 *
 * Pass 2: tune click "worked" but cdk-overlay was empty.
 * Free UI is Agent mode → settings are likely the legacy "Agent Settings"
 * modal/panel (inline or mat-dialog), NOT the Plus 🍌 popover.
 *
 * This script:
 *  1) diffs the page BEFORE/AFTER clicking tune
 *  2) finds "Agent Settings" / Save / Never / aspects / models anywhere
 *  3) dumps NEW interactive controls after open
 *
 * Paste in Console. Downloads farm-flow-FREE-agent-settings.json
 * Also: after it runs, if modal is open, leave it open and re-run with
 *   window.__FARM_SCRAPE_OPEN_ONLY = true
 * to dump whatever is currently visible without clicking again.
 */
(async () => {
  const TAG = "FARM_FLOW_FREE_AGENT";
  const OPEN_ONLY = !!window.__FARM_SCRAPE_OPEN_ONLY;
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

  const txt = (el, n = 300) =>
    (el?.innerText || el?.textContent || "")
      .replace(/[\u200b\ufeff]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, n);

  const sum = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {
      tag: el.tagName,
      role: el.getAttribute("role") || "",
      aria: el.getAttribute("aria-label") || "",
      ariaPressed: el.getAttribute("aria-pressed") || "",
      ariaChecked: el.getAttribute("aria-checked") || "",
      ariaSelected: el.getAttribute("aria-selected") || "",
      disabled: !!(el.disabled || el.getAttribute("aria-disabled") === "true"),
      text: txt(el, 220),
      class: String(el.className || "").slice(0, 220),
      icons: [...el.querySelectorAll(".google-symbols, .material-symbols-outlined, .material-icons")]
        .map((n) => txt(n, 40))
        .filter(Boolean)
        .slice(0, 10),
      rect: {
        t: Math.round(r.top),
        l: Math.round(r.left),
        w: Math.round(r.width),
        h: Math.round(r.height)
      }
    };
  };

  const pointerClick = async (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const x = r.left + r.width / 2;
    const y = r.top + r.height / 2;
    el.scrollIntoView({ block: "center", inline: "nearest" });
    await sleep(200);
    for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
      el.dispatchEvent(
        new MouseEvent(type, {
          bubbles: true,
          cancelable: true,
          view: window,
          clientX: x,
          clientY: y,
          button: 0
        })
      );
    }
    await sleep(1800);
    return true;
  };

  const escapeClose = async () => {
    for (let i = 0; i < 2; i++) {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", code: "Escape", keyCode: 27, bubbles: true })
      );
      await sleep(200);
    }
  };

  const interactiveSelector =
    "button,[role='button'],[role='tab'],[role='radio'],[role='option'],[role='menuitem'],[role='switch'],[role='checkbox'],input,label,a,mat-button-toggle,mat-radio-button,mat-option,.mat-mdc-menu-item,mat-slide-toggle";

  const snapshotInteractives = () =>
    [...document.querySelectorAll(interactiveSelector)].filter(vis).map(sum);

  const findTextNodes = (needles) => {
    const out = [];
    const all = [...document.querySelectorAll("h1,h2,h3,h4,div,span,p,label,button,[role='heading']")];
    for (const el of all) {
      if (!vis(el)) continue;
      const t = txt(el, 120);
      const low = t.toLowerCase();
      if (!needles.some((n) => low.includes(n))) continue;
      // skip huge containers
      const r = el.getBoundingClientRect();
      if (r.height > 400 || r.width > 900) continue;
      out.push(sum(el));
      if (out.length > 80) break;
    }
    return out;
  };

  const collectAnyPanels = () => {
    const sels = [
      ".cdk-overlay-pane",
      "mat-dialog-container",
      ".mat-mdc-dialog-container",
      ".mat-mdc-dialog-surface",
      "[role='dialog']",
      ".mat-mdc-menu-panel",
      "[role='menu']",
      "aside",
      "[class*='settings']",
      "[class*='agent-settings']",
      "[class*='drawer']",
      "[class*='sheet']",
      "[class*='panel']"
    ];
    const nodes = new Set();
    for (const sel of sels) {
      try {
        for (const el of document.querySelectorAll(sel)) {
          if (vis(el)) nodes.add(el);
        }
      } catch (_) {}
    }
    // Also: any visible root that contains exact heading Agent Settings
    for (const el of document.querySelectorAll("h1,h2,h3,h4,[role='heading'],div")) {
      if (!vis(el)) continue;
      if (txt(el, 40).toLowerCase() === "agent settings") {
        let root = el.parentElement;
        for (let i = 0; i < 8 && root; i++) {
          const r = root.getBoundingClientRect();
          if (r.width > 280 && r.height > 200) {
            nodes.add(root);
            break;
          }
          root = root.parentElement;
        }
      }
    }
    return [...nodes].map((pane) => ({
      root: sum(pane),
      headings: [...pane.querySelectorAll("h1,h2,h3,h4,[role='heading']")]
        .filter(vis)
        .map((h) => txt(h, 120))
        .slice(0, 20),
      fullText: txt(pane, 10000),
      interactive: [...pane.querySelectorAll(interactiveSelector)].filter(vis).map(sum).slice(0, 120)
    }));
  };

  const pageFingerprint = () => ({
    title: document.title,
    bodyLen: (document.body?.innerText || "").length,
    bodySample: txt(document.body, 2500),
    headings: [...document.querySelectorAll("h1,h2,h3,h4,[role='heading']")]
      .filter(vis)
      .map((h) => txt(h, 100))
      .slice(0, 40),
    keywordHits: findTextNodes([
      "agent settings",
      "confirmation",
      "never",
      "always",
      "ask",
      "aspect",
      "outputs",
      "quantity",
      "nano banana",
      "imagen",
      "save",
      "model",
      "credits",
      "16:9",
      "3:4",
      "1:1",
      "x1",
      "x2"
    ])
  });

  const findTune = () =>
    [...document.querySelectorAll("button")].find((b) => {
      if (!vis(b)) return false;
      const aria = (b.getAttribute("aria-label") || "").toLowerCase();
      const t = txt(b, 40).toLowerCase();
      return aria === "settings" && (t === "tune" || b.className.includes("agent-action"));
    });

  // ── BEFORE ──
  if (!OPEN_ONLY) await escapeClose();
  await sleep(300);

  const before = {
    fp: pageFingerprint(),
    interactives: snapshotInteractives(),
    panels: collectAnyPanels()
  };

  let clickInfo = null;
  if (!OPEN_ONLY) {
    const tune = findTune();
    clickInfo = { found: !!tune, beforeClick: sum(tune) };
    if (!tune) {
      console.error(`${TAG}: tune Settings button not found`);
    } else {
      // Prefer real .click() then pointer sequence
      try {
        tune.click();
        await sleep(2000);
      } catch (_) {
        await pointerClick(tune);
      }
      clickInfo.afterClick = sum(tune);
      clickInfo.stillInDom = document.contains(tune);
    }
  }

  const after = {
    fp: pageFingerprint(),
    interactives: snapshotInteractives(),
    panels: collectAnyPanels()
  };

  // Diff interactives by aria+text+rect key
  const keyOf = (it) => `${it.tag}|${it.aria}|${it.text}|${it.rect?.t},${it.rect?.l}`;
  const beforeKeys = new Set(before.interactives.map(keyOf));
  const newInteractives = after.interactives.filter((it) => !beforeKeys.has(keyOf(it)));

  const bodyBefore = before.fp.bodySample.toLowerCase();
  const bodyAfter = after.fp.bodySample.toLowerCase();
  const appearedPhrases = [
    "agent settings",
    "confirmation",
    "never",
    "save",
    "nano banana",
    "imagen",
    "aspect ratio",
    "outputs",
    "quantity",
    "credits",
    "16:9",
    "3:4",
    "1:1",
    "x1",
    "x2",
    "x3",
    "x4"
  ].filter((p) => !bodyBefore.includes(p) && bodyAfter.includes(p));

  // Deep search for Agent Settings heading even if in huge container
  const agentSettingsHeading = [...document.querySelectorAll("*")].find((el) => {
    if (!vis(el)) return false;
    return txt(el, 40).toLowerCase() === "agent settings";
  });

  let agentSettingsRoot = null;
  if (agentSettingsHeading) {
    let root = agentSettingsHeading;
    for (let i = 0; i < 12 && root?.parentElement; i++) {
      root = root.parentElement;
      const r = root.getBoundingClientRect();
      if (r.width >= 320 && r.height >= 240 && r.width < innerWidth * 0.98) {
        agentSettingsRoot = root;
        break;
      }
    }
  }

  const agentSettingsDump = agentSettingsRoot
    ? {
        root: sum(agentSettingsRoot),
        fullText: txt(agentSettingsRoot, 12000),
        interactive: [...agentSettingsRoot.querySelectorAll(interactiveSelector)]
          .filter(vis)
          .map(sum)
      }
    : null;

  const summary = {
    openOnlyMode: OPEN_ONLY,
    tuneClicked: !OPEN_ONLY && !!clickInfo?.found,
    agentSettingsHeadingFound: !!agentSettingsHeading,
    agentSettingsPanelDumped: !!agentSettingsDump,
    newInteractiveCount: newInteractives.length,
    appearedPhrases,
    quantityAnywhere: /\b(?:x[1-4]|[1-4]x)\b/i.test(after.fp.bodySample),
    hasSave: /\bsave\b/i.test(after.fp.bodySample),
    hasNever: /\bnever\b/i.test(after.fp.bodySample),
    panelCountAfter: after.panels.length,
    expectCount: 1
  };

  const report = {
    scrapedAt: new Date().toISOString(),
    pass: 3,
    url: location.href,
    viewport: { w: innerWidth, h: innerHeight },
    summary,
    clickInfo,
    appearedPhrases,
    newInteractives: newInteractives.slice(0, 100),
    agentSettingsHeading: sum(agentSettingsHeading),
    agentSettingsDump,
    panelsAfter: after.panels.slice(0, 15),
    keywordHitsAfter: after.fp.keywordHits,
    headingsAfter: after.fp.headings,
    howToManual: [
      "If agentSettingsPanelDumped=false: manually click the tune icon once,",
      "then in console run: window.__FARM_SCRAPE_OPEN_ONLY=true",
      "and paste this script again — it will dump the open modal without clicking."
    ]
  };

  console.log(`%c${TAG}`, "color:#c60;font-weight:bold", report);
  console.table(summary);
  console.log(`${TAG} appearedPhrases`, appearedPhrases);
  console.log(
    `${TAG} newInteractives`,
    newInteractives.map((i) => ({ aria: i.aria, text: i.text, role: i.role, icons: i.icons }))
  );
  if (agentSettingsDump) {
    console.log(`${TAG} AGENT SETTINGS TEXT`, agentSettingsDump.fullText.slice(0, 2000));
    console.log(
      `${TAG} AGENT SETTINGS CONTROLS`,
      agentSettingsDump.interactive.map((i) => ({
        aria: i.aria,
        text: i.text,
        role: i.role,
        checked: i.ariaChecked || i.ariaPressed,
        icons: i.icons
      }))
    );
  }

  const json = JSON.stringify(report, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "farm-flow-FREE-agent-settings.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);

  try {
    await navigator.clipboard.writeText(json);
    console.log(`${TAG}: downloaded + clipboard`);
  } catch (_) {
    console.log(`${TAG}: downloaded farm-flow-FREE-agent-settings.json`);
  }

  // Do NOT auto-escape if we found the panel — leave it for visual check
  if (!agentSettingsDump && !OPEN_ONLY) await escapeClose();

  return summary;
})();
