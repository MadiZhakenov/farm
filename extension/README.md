# Farm Flow

Chrome extension for bulk **image** generation on [Google Flow](https://labs.google/fx/tools/flow).

Combines:
- **Flow Auto Prompter** — CDP clicks, settings, queue, auto-download, safety stop
- **flow-queue** — reference image paste + reuse from Flow asset menu

## Install

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → select this folder (`farm/extension`)
4. Open a Flow project tab (`labs.google/.../flow/...` or `flow.google.com`)
5. Click the extension icon → side panel opens

## Use

1. Paste prompts (one per line)
2. Optional: drop a **reference image**
3. Set aspect / batch / model / rest delay
4. Click **Start**

Yellow Chrome banner *"started debugging this browser"* is normal (CDP). Do not cancel it while running.

## Notes

- Unofficial automation — may break when Flow UI changes; can hit rate limits.
- Prefer a secondary Google account for heavy runs.
