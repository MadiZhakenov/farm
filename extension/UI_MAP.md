# Flow UI map

## Plus (🍌 Settings trigger popover) — Brave scrape 2026-09-16

**Status in code:** used whenever live UI exposes the popover (Plus or free+narrow).

### Composer
| Control | Selector |
|---------|----------|
| Prompt | `div.ProseMirror[contenteditable=true]` |
| Add | `button[aria-label="Add ingredients to the prompt box"]` |
| Settings | `button[aria-label="Settings trigger"].settings-trigger-button` |
| Generate | `button[aria-label="Start generation"].generate-icon-button` |

### Settings popover
Root: `.cdk-overlay-pane` containing Image/Video + aspects + x1–x4

| Control | How to click |
|---------|----------------|
| Image mode | `button[role=radio]` text contains `Image` |
| Aspect 3:4 | `button[role=radio]` text `crop_portrait 3:4` |
| Aspect 16:9 | text `crop_16_9 16:9` |
| Aspect 4:3 | text `crop_landscape 4:3` |
| Aspect 1:1 | text `crop_square 1:1` |
| Aspect 9:16 | text `crop_9_16 9:16` |
| Quantity | exact `x1` / `x2` / `x3` / `x4` on `button[role=radio]` |
| Model | `button[aria-label="Select model family"]` → menu item with model name |

**No Save button** — values apply on click. Close with Escape.

---

## Adaptive routing (not subscription-based)

Flow switches layout by **viewport**, not only by Plus/free:

| Situation | Typical UI | Path |
|-----------|------------|------|
| Plus account | 🍌 Settings trigger → cdk popover | `popover` |
| Free + **narrow** window | Same 🍌 popover | `popover` |
| Free + **wide** window | `tune` → `flow-agent-panel` | `agent-panel` |

Runtime: `inspectSettingsSurface()` → `probeSettingsSurface()` clicks the preferred control and checks what actually opened (overlay vs panel), with fallback to the other path.

### Composer (free)
| Control | Selector |
|---------|----------|
| Prompt | `div.ProseMirror[contenteditable=true]` |
| Add | `button[aria-label="Add ingredients to the prompt box"].add-menu-trigger` |
| Mode | `button.agent-mode-chip` (pressed when Agent) |
| Settings open | `button[aria-label="Settings"].agent-action-button` icon `tune` |
| Agent instructions | `button[aria-label="Agent instructions"]` icon `article_spark` |
| Generate | `button[aria-label="Start generation"].generate-icon-button` icon `arrow_forward` |

### Agent settings panel
Root: `flow-agent-panel`  
Title: `h2.header-title` = `Agent settings`  
Content: `.settings-content`

| Control | How to click |
|---------|----------------|
| Back | `button[aria-label="Back"]` |
| Confirm Always | `mat-radio-button.radio-item` text starts with `Always` |
| Confirm Never | `mat-radio-button.radio-item` text starts with `Never` (**required**) |
| Image aspect | `flow-toggles[aria-label="Image generation default aspect ratio"]` → `button[role=radio]` with `16:9` / `4:3` / `1:1` / `3:4` / `9:16` |
| Image quantity | `flow-toggles[aria-label="Image generation default output count"]` → exact `x1`–`x4` |
| Image model | `button[aria-label="Image generation default model"].image-model-picker-button` → menu |
| Video defaults | **Do not touch** (separate section below Image) |
| Save | `button.settings-save-button` text `Save` |

**Note:** Free UI still exposes x1–x4 in Agent settings (not “locked to 1”). Use panel Quantity; `expectCount` follows that value. If a run only ever yields 1 tile, treat as account/runtime limit and fall back.
