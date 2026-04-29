"""Re-launch the persistent Chromium profile, confirm NotebookLM loads authed,
save storage_state.json, and print the active account + a notebook list."""
from pathlib import Path
from playwright.sync_api import sync_playwright
import time, json, re, sys

NB_HOME = Path.home() / ".notebooklm"
STATE   = NB_HOME / "storage_state.json"
PROFILE = NB_HOME / "browser_profile"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE),
        headless=True,
        viewport={"width": 1280, "height": 900},
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://notebooklm.google.com/", wait_until="domcontentloaded")
    time.sleep(4)                         # let React render

    url = page.url
    print(f"Landed URL: {url}")
    if "accounts.google.com" in url or "signin" in url:
        print("NOT AUTHED — need to re-run login")
        ctx.close()
        sys.exit(2)

    # Save state (also writes cookies to STATE file)
    ctx.storage_state(path=str(STATE))
    print(f"Saved storage_state -> {STATE}")

    # Try to find the account email in the DOM
    acct = page.evaluate("""() => {
        const qs = [
            'a[aria-label*="@"]',
            '[aria-label*="Account"]',
            'a[href*="SignOutOptions"]'
        ];
        for (const q of qs) {
            const e = document.querySelector(q);
            if (e) {
                const al = e.getAttribute('aria-label') || '';
                const m = al.match(/[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}/);
                if (m) return m[0];
            }
        }
        // Scan all aria-label attributes
        const all = document.querySelectorAll('[aria-label]');
        for (const e of all) {
            const al = e.getAttribute('aria-label') || '';
            const m = al.match(/[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}/);
            if (m) return m[0];
        }
        return null;
    }""")
    print(f"Detected account: {acct or '(not found in DOM — check storage_state)'}")

    # Capture notebook titles from the home grid
    titles = page.evaluate("""() => {
        const nodes = document.querySelectorAll('[data-notebook-id], [role="listitem"], article');
        const out = new Set();
        nodes.forEach(n => {
            const t = (n.innerText || '').split('\\n')[0].trim();
            if (t && t.length < 120) out.add(t);
        });
        return Array.from(out).slice(0, 50);
    }""")
    print(f"Notebook-ish items on page: {len(titles)}")
    for t in titles[:20]:
        print(f"  - {t}")
    ctx.close()
