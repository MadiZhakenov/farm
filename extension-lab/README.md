# Farm Flow Lab

Local Chrome with the extension loaded. You log in once; the agent drives jobs and reads logs.

## One-time setup

```powershell
cd e:\Users\Desktop\farm\extension-lab
npm install
npm run launch
```

In the opened Chrome window:

1. Sign into your Google / Flow account
2. Open a Flow project (composer visible)
3. Leave this window open (CDP on `127.0.0.1:9222`)

## Agent commands (I use these)

```powershell
npm run status
npm run logs
node agent.mjs start "make the suit pink" --ref ..\_refs\some.png
node agent.mjs watch 120
node agent.mjs shot
node agent.mjs scrape
node agent.mjs stop
```

Profile lives in `extension-lab/profile` (cookies stay). Screenshots/scrapes go to `extension-lab/out/`.

## Reload extension after code changes

Close the lab Chrome window, then `npm run launch` again (same profile = still logged in).
Or in Chrome: `chrome://extensions` → Farm Flow → Reload, then refresh the Flow tab.
