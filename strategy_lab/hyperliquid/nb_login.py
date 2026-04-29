"""
Interactive NotebookLM login — drives Playwright directly, no stdin needed.

Opens a Chromium window, waits until you've signed in (URL reaches
notebooklm.google.com homepage, not the accounts.google.com redirect),
then saves cookies to the same place the notebooklm CLI reads from.

The browser stays open until login completes (up to 10 minutes).
"""
from pathlib import Path
from playwright.sync_api import sync_playwright
import time, sys

NB_HOME = Path.home() / ".notebooklm"
NB_HOME.mkdir(exist_ok=True)
STATE = NB_HOME / "storage_state.json"

HOMEPAGE_RE = "notebooklm.google.com/"

def main(max_wait_s: int = 600, poll_s: float = 2.0):
    with sync_playwright() as p:
        # Use a persistent profile so we don't lose it across runs.
        profile_dir = NB_HOME / "browser_profile"
        profile_dir.mkdir(exist_ok=True)
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            args=["--start-maximized"],
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        print("Opening NotebookLM... Please sign in with your Google account.")
        page.goto("https://notebooklm.google.com/", wait_until="domcontentloaded")

        start = time.time()
        authed = False
        while time.time() - start < max_wait_s:
            url = page.url
            # The home page renders once Google accepts the account.
            # We check URL no longer contains accounts.google.com AND is
            # on notebooklm.google.com root.
            if ("accounts.google.com" not in url and
                "signin" not in url and
                "notebooklm.google.com" in url and
                url.endswith("/")):
                # Extra confirmation: page has the side-nav "Create" button
                try:
                    if page.locator('text="Create"').first.is_visible(timeout=1000):
                        authed = True
                        break
                except Exception:
                    pass
            time.sleep(poll_s)

        if not authed:
            print("Timed out before login completed.")
            ctx.close()
            sys.exit(2)

        # Discover the active Google account from the page
        try:
            # Click avatar / account menu to reveal email
            # (best-effort — not all UIs expose it in the DOM)
            meta = page.evaluate("""() => {
                const el = document.querySelector('a[aria-label*="@"]')
                          || document.querySelector('div[aria-label*="@"]');
                return el ? el.getAttribute('aria-label') : null;
            }""")
            if meta:
                print(f"Authenticated account hint: {meta}")
        except Exception:
            pass

        ctx.storage_state(path=str(STATE))
        print(f"\nSAVED cookies to: {STATE}")
        print("You can close the browser now.")
        ctx.close()

if __name__ == "__main__":
    main()
