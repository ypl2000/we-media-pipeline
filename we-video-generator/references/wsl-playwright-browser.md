# WSL Playwright Browser Automation — Pitfalls & Patterns

## The Core Problem

Running `playwright` from a WSL terminal, the browser window closes immediately after the Python script finishes — even when the user hasn't finished interacting. This is because `with sync_playwright() as p:` uses a context manager that calls `stop()` when the `with` block exits.

## Anti-pattern (kills browser immediately)

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:           # ← browser closes here when block exits
    browser = p.chromium.launch(...)
    page.goto(...)
    # user has no time to scan QR code!
```

## Correct pattern — long-running background process

```python
from playwright.sync_api import sync_playwright
import os, time

os.environ['DISPLAY'] = ':0'

p = sync_playwright().start()          # ← no `with`, process stays alive
browser = p.chromium.launch(
    headless=False,
    args=['--remote-debugging-port=9222']  # optional: enable CDP reconnect
)
page = browser.new_page(viewport={"width": 1280, "height": 900})
page.goto('https://target-site.com')

print("READY")  # signal to user that browser is up

# Poll for login state
while True:
    time.sleep(5)
    url = page.url
    if '/login' not in url:
        print(f"LOGIN_OK: {url}")
        break
    else:
        print("waiting...")
```

Launch as `background=true` in the terminal tool so it survives across polling cycles.

## CDP Reconnect (experimental — sometimes works)

If the browser process is still alive, try to reconnect from a new script:

```python
browser = p.chromium.connect_over_cdp('http://localhost:9222')
```

Requirements: `--remote-debugging-port=9222` was passed at launch, and the firewall allows localhost connections.

## Known limitations in WSL

- `input()` calls in the terminal tool return `EOFError` — never use interactive input in WSL Playwright scripts
- Edge/Chrome Cookie files (`%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Network\Cookies`) are locked by the running browser and cannot be read from WSL
- Windows Defender or corporate AV can kill Playwright browser processes shortly after launch — if the window flashes and disappears, this is the cause
- `browser_navigate` etc. native tools fail with `WinError 193` in this WSL setup, but raw Playwright scripts work fine
