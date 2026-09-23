/**
 * Farm Flow settings scrape — no DevTools copy() needed.
 * Paste in Console on Flow project tab. Downloads farm-flow-settings.json
 */
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const vis = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none" && s.opacity !== "0";
  };
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
      text: (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 160),
      class: (el.className || "").toString().slice(0, 160),
      rect: { t: Math.round(r.top), l: Math.round(r.left), w: Math.round(r.width), h: Math.round(r.height) }
    };
  };

  const chip =
    document.querySelector('button[aria-label="Settings trigger"]') ||
    document.querySelector("button.settings-trigger-button");
  if (chip) {
    chip.click();
    await sleep(1800);
  }

  const panes = [...document.querySelectorAll(
    ".cdk-overlay-pane, mat-dialog-container, [role='dialog'], .mat-mdc-menu-panel, [role='menu']"
  )].filter(vis);

  const overlays = panes.map((pane) => ({
    root: sum(pane),
    headings: [...pane.querySelectorAll("h1,h2,h3,h4,.mat-mdc-dialog-title,[role='heading']")]
      .filter(vis)
      .map((h) => (h.innerText || "").replace(/\s+/g, " ").trim()),
    text: (pane.innerText || "").replace(/\s+/g, " ").trim().slice(0, 4000),
    items: [...pane.querySelectorAll(
      "button,[role='button'],[role='tab'],[role='radio'],[role='option'],[role='menuitem'],input,label,mat-button-toggle,mat-radio-button,mat-option"
    )]
      .filter(vis)
      .map(sum)
  }));

  const report = {
    scrapedAt: new Date().toISOString(),
    url: location.href,
    viewport: { w: innerWidth, h: innerHeight },
    composer: {
      editor: sum(document.querySelector("div.ProseMirror[contenteditable='true']")),
      settings: sum(chip),
      generate: sum(document.querySelector('button[aria-label="Start generation"], button.generate-icon-button')),
      add: sum(document.querySelector('button[aria-label="Add ingredients to the prompt box"], button.add-menu-trigger'))
    },
    overlayCount: overlays.length,
    overlays
  };

  const json = JSON.stringify(report, null, 2);
  console.log("FARM_FLOW_SETTINGS", report);

  // Download file (works without DevTools copy)
  const blob = new Blob([json], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "farm-flow-settings.json";
  a.click();
  URL.revokeObjectURL(a.href);

  // Also try clipboard API
  try {
    await navigator.clipboard.writeText(json);
    console.log("Also copied via navigator.clipboard");
  } catch (_) {
    console.log("Clipboard blocked — use the downloaded farm-flow-settings.json");
  }

  return "Downloaded farm-flow-settings.json — drop that file into the chat or open and paste.";
})();
