/**
 * Farm Flow — FREE / no-Plus UI scrape (AdsPower free Google accounts)
 *
 * Goal: dump everything we need to adapt automation WITHOUT breaking Plus path.
 * Paste into DevTools Console on a Flow project tab logged into a FREE account.
 *
 * Output:
 *   - downloads farm-flow-FREE-ui.json
 *   - console table of Plus-vs-Free diffs
 *   - tries clipboard copy of JSON
 *
 * Do NOT run Start in the extension while scraping.
 */
(async () => {
  const TAG = "FARM_FLOW_FREE";
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const vis = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return (
      r.width > 0 &&
      r.height > 0 &&
      s.visibility !== "hidden" &&
      s.display !== "none" &&
      Number(s.opacity) !== 0
    );
  };

  const txt = (el, n = 200) =>
    (el?.innerText || el?.textContent || "")
      .replace(/[\u200b\ufeff]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, n);

  const sum = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const icons = [...el.querySelectorAll(".google-symbols, .material-symbols-outlined, [class*='symbol']")]
      .map((n) => txt(n, 40))
      .filter(Boolean)
      .slice(0, 8);
    return {
      tag: el.tagName,
      id: el.id || "",
      role: el.getAttribute("role") || "",
      type: el.getAttribute("type") || "",
      aria: el.getAttribute("aria-label") || "",
      ariaPressed: el.getAttribute("aria-pressed") || "",
      ariaChecked: el.getAttribute("aria-checked") || "",
      ariaSelected: el.getAttribute("aria-selected") || "",
      ariaExpanded: el.getAttribute("aria-expanded") || "",
      ariaDisabled: el.getAttribute("aria-disabled") || "",
      disabled: !!(el.disabled || el.getAttribute("aria-disabled") === "true"),
      title: el.getAttribute("title") || "",
      name: el.getAttribute("name") || "",
      href: el.getAttribute("href") || "",
      text: txt(el, 180),
      class: String(el.className || "").slice(0, 200),
      icons,
      dataAttrs: [...el.attributes]
        .filter((a) => a.name.startsWith("data-"))
        .reduce((o, a) => {
          o[a.name] = String(a.value).slice(0, 80);
          return o;
        }, {}),
      rect: {
        t: Math.round(r.top),
        l: Math.round(r.left),
        w: Math.round(r.width),
        h: Math.round(r.height)
      }
    };
  };

  const clickSafe = async (el) => {
    if (!el || !vis(el)) return false;
    try {
      el.scrollIntoView({ block: "center", inline: "nearest" });
      el.click();
      await sleep(900);
      return true;
    } catch (_) {
      return false;
    }
  };

  const escapeClose = async () => {
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", code: "Escape", keyCode: 27, bubbles: true })
    );
    await sleep(400);
  };

  const collectOverlays = () =>
    [...document.querySelectorAll(
      ".cdk-overlay-pane, mat-dialog-container, [role='dialog'], .mat-mdc-menu-panel, [role='menu'], [role='listbox']"
    )]
      .filter(vis)
      .map((pane) => ({
        root: sum(pane),
        headings: [...pane.querySelectorAll("h1,h2,h3,h4,.mat-mdc-dialog-title,[role='heading']")]
          .filter(vis)
          .map((h) => txt(h, 120)),
        fullText: txt(pane, 6000),
        interactive: [
          ...pane.querySelectorAll(
            "button,[role='button'],[role='tab'],[role='radio'],[role='option'],[role='menuitem'],[role='switch'],input,label,a,mat-button-toggle,mat-radio-button,mat-option,.mat-mdc-menu-item"
          )
        ]
          .filter(vis)
          .map(sum)
      }));

  // ── Known Plus-era selectors (do not remove later — compare against Free) ──
  const PLUS_EXPECT = {
    editor: "div.ProseMirror[contenteditable='true']",
    settings: 'button[aria-label="Settings trigger"], button.settings-trigger-button',
    generate: 'button[aria-label="Start generation"], button.generate-icon-button',
    add: 'button[aria-label="Add ingredients to the prompt box"], button.add-menu-trigger',
    quantityRadios: ["x1", "x2", "x3", "x4"],
    aspectHints: ["16:9", "4:3", "1:1", "3:4", "9:16"],
    modelAria: "Select model family"
  };

  const qOne = (sel) => {
    try {
      return document.querySelector(sel);
    } catch (_) {
      return null;
    }
  };

  // ── 1) Page chrome / credits / upgrade signals ──
  const bodyText = txt(document.body, 12000);
  const creditHints = [];
  const creditRe =
    /(\d[\d,\.]*)\s*(credits?|credit|кредитов|кредит)|credits?\s*[:=]?\s*(\d[\d,\.]*)|upgrade|google\s*one|flow\s*plus|get\s*plus|subscribe|free\s*plan|monthly\s*limit|out\s*of\s*credits/gi;
  let m;
  while ((m = creditRe.exec(bodyText))) {
    creditHints.push(m[0]);
    if (creditHints.length > 40) break;
  }

  const topChromeButtons = [...document.querySelectorAll("button, a, [role='button']")]
    .filter((el) => {
      if (!vis(el)) return false;
      const r = el.getBoundingClientRect();
      return r.top < 120 && r.width > 0;
    })
    .map(sum)
    .slice(0, 60);

  // Material / Google Symbols anywhere on page (icons as text content)
  const pageIcons = [
    ...new Set(
      [...document.querySelectorAll(".google-symbols, .material-symbols-outlined, .material-icons")]
        .filter(vis)
        .map((n) => txt(n, 40))
        .filter(Boolean)
    )
  ].slice(0, 120);

  // ── 2) Composer baseline (closed overlays) ──
  await escapeClose();
  await escapeClose();

  const composerClosed = {
    editor: sum(qOne(PLUS_EXPECT.editor)),
    settings: sum(
      qOne('button[aria-label="Settings trigger"]') || qOne("button.settings-trigger-button")
    ),
    generate: sum(
      qOne('button[aria-label="Start generation"]') || qOne("button.generate-icon-button")
    ),
    add: sum(
      qOne('button[aria-label="Add ingredients to the prompt box"]') ||
        qOne("button.add-menu-trigger")
    ),
    // Free UI may rename these — catch any nearby composer buttons
    allNearBottom: [...document.querySelectorAll("button, [role='button']")]
      .filter((el) => {
        if (!vis(el)) return false;
        const r = el.getBoundingClientRect();
        return r.bottom > innerHeight * 0.45;
      })
      .map(sum)
      .slice(0, 80)
  };

  // ── 3) Open Settings popover ──
  const settingsBtn =
    qOne('button[aria-label="Settings trigger"]') ||
    qOne("button.settings-trigger-button") ||
    [...document.querySelectorAll("button")].find((b) => {
      if (!vis(b)) return false;
      const t = txt(b, 80).toLowerCase();
      const a = (b.getAttribute("aria-label") || "").toLowerCase();
      return a.includes("settings") || t.includes("settings") || /\d+:\d+/.test(t);
    });

  let settingsOpened = false;
  if (settingsBtn) {
    settingsOpened = await clickSafe(settingsBtn);
    await sleep(1000);
  }

  const overlaysAfterSettings = collectOverlays();

  // Quantity / aspect / model probes inside overlays
  const overlayBlob = overlaysAfterSettings.map((o) => o.fullText).join("\n");
  const quantityProbe = {
    hasX1: /\bx1\b/i.test(overlayBlob),
    hasX2: /\bx2\b/i.test(overlayBlob),
    hasX3: /\bx3\b/i.test(overlayBlob),
    hasX4: /\bx4\b/i.test(overlayBlob),
    has1x: /\b1x\b/i.test(overlayBlob),
    hasQuantityWord: /quantity|outputs?|images?\s*per|batch/i.test(overlayBlob),
    matchedTokens: (overlayBlob.match(/\b(?:x[1-4]|[1-4]x)\b/gi) || []).slice(0, 20)
  };

  const aspectProbe = {
    ratios: PLUS_EXPECT.aspectHints.filter((r) => overlayBlob.includes(r)),
    cropIcons: (
      overlayBlob.match(/crop_(?:16_9|landscape|square|portrait|9_16)/gi) || []
    ).slice(0, 20)
  };

  const modelProbe = {
    hasSelectModelFamily: overlayBlob.toLowerCase().includes("select model"),
    modelMentions: (
      overlayBlob.match(/nano banana(?:\s*(?:pro|2))?|imagen\s*4|veo|gemini/gi) || []
    ).slice(0, 30)
  };

  // All radios in settings overlays
  const settingsRadios = overlaysAfterSettings.flatMap((o) =>
    (o.interactive || []).filter((it) => it.role === "radio" || /radio/i.test(it.class || ""))
  );

  // ── 4) Try open model family menu (if present) ──
  let modelMenuItems = [];
  const modelBtn =
    document.querySelector('button[aria-label="Select model family"]') ||
    [...document.querySelectorAll("button")].find((b) => {
      if (!vis(b)) return false;
      const a = (b.getAttribute("aria-label") || "").toLowerCase();
      const t = txt(b, 80).toLowerCase();
      return (
        a.includes("select model") ||
        (t.includes("nano banana") && t.includes("arrow_drop_down")) ||
        (t.includes("imagen") && t.includes("arrow_drop_down"))
      );
    });

  if (modelBtn) {
    await clickSafe(modelBtn);
    await sleep(800);
    modelMenuItems = collectOverlays().flatMap((o) =>
      (o.interactive || []).filter(
        (it) =>
          it.role === "menuitem" ||
          /menu-item/i.test(it.class || "") ||
          /nano|imagen|veo|gemini/i.test(it.text || "")
      )
    );
    await escapeClose();
  }

  // ── 5) Try Add ingredients menu (free may differ) ──
  await escapeClose();
  const addBtn =
    qOne('button[aria-label="Add ingredients to the prompt box"]') ||
    qOne("button.add-menu-trigger");
  let addMenu = null;
  if (addBtn) {
    await clickSafe(addBtn);
    await sleep(700);
    addMenu = collectOverlays();
    await escapeClose();
  }

  // ── 6) Plus-vs-Free checklist ──
  const plusVsFree = {
    editorFound: !!composerClosed.editor,
    settingsTriggerFound: !!composerClosed.settings,
    generateFound: !!composerClosed.generate,
    addFound: !!composerClosed.add,
    settingsPopoverOpened: settingsOpened && overlaysAfterSettings.length > 0,
    quantityControlsPresent: quantityProbe.hasX1 || quantityProbe.hasX2 || quantityProbe.has1x,
    quantityLooksLockedToOne:
      !quantityProbe.hasX2 &&
      !quantityProbe.hasX3 &&
      !quantityProbe.hasX4 &&
      (quantityProbe.hasX1 || quantityProbe.has1x || !quantityProbe.hasQuantityWord),
    aspectControlsPresent: aspectProbe.ratios.length > 0,
    modelSelectorPresent: !!modelBtn || modelProbe.hasSelectModelFamily,
    upgradeSignals: creditHints.filter((h) => /upgrade|plus|subscribe/i.test(h)).slice(0, 20),
    creditSignals: creditHints.filter((h) => /credit/i.test(h)).slice(0, 20)
  };

  const report = {
    scrapedAt: new Date().toISOString(),
    tierHint: "FREE_NO_PLUS_EXPECTED",
    url: location.href,
    title: document.title,
    viewport: { w: innerWidth, h: innerHeight },
    userAgent: navigator.userAgent,
    plusExpectReference: PLUS_EXPECT,
    plusVsFree,
    creditHints: [...new Set(creditHints)].slice(0, 40),
    pageIcons,
    topChromeButtons,
    composerClosed,
    settings: {
      opened: settingsOpened,
      triggerUsed: sum(settingsBtn),
      overlays: overlaysAfterSettings,
      radios: settingsRadios,
      quantityProbe,
      aspectProbe,
      modelProbe
    },
    modelMenuItems,
    addMenu,
    notesForAdapter: [
      "If quantityControlsPresent=false → free path must expectCount=1 always.",
      "Keep Plus quantity/settings code paths; gate with tierDetect or settings flag.",
      "Compare settings.overlays[].interactive text/aria vs UI_MAP.md Plus scrape.",
      "Drop farm-flow-FREE-ui.json into chat after this run."
    ]
  };

  // Console summary
  console.log(`%c${TAG}`, "color:#0a0;font-weight:bold", report);
  console.table(plusVsFree);
  console.log(`${TAG} quantityProbe`, quantityProbe);
  console.log(`${TAG} aspectProbe`, aspectProbe);
  console.log(`${TAG} modelProbe`, modelProbe);
  console.log(
    `${TAG} settings radios (${settingsRadios.length})`,
    settingsRadios.map((r) => ({
      text: r.text,
      aria: r.aria,
      checked: r.ariaChecked,
      icons: r.icons
    }))
  );

  const json = JSON.stringify(report, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "farm-flow-FREE-ui.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);

  try {
    await navigator.clipboard.writeText(json);
    console.log(`${TAG}: downloaded farm-flow-FREE-ui.json + copied to clipboard`);
  } catch (_) {
    console.log(`${TAG}: downloaded farm-flow-FREE-ui.json (clipboard blocked)`);
  }

  // Close leftovers
  await escapeClose();

  return {
    ok: true,
    file: "farm-flow-FREE-ui.json",
    plusVsFree,
    quantityProbe
  };
})();
