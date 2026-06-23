#!/usr/bin/env python3
"""CDP WebSocket scraper — connect to Chrome CDP and extract tweets via scroll.

Usage:
  1. Launch Chrome with --remote-debugging-port=<port> and a FRESH temp --user-data-dir:
     chrome.exe --remote-debugging-address=127.0.0.1 --remote-debugging-port=9229 ^
       --user-data-dir="C:\Temp\chrome_scrape" --no-first-run --no-default-browser-check ^
       --new-window https://x.com/<target>

     IMPORTANT: Use a fresh empty temp profile, NOT a clone of an existing profile.
     Cloned profiles break CDP relaunch (Chrome refuses to bind the debug port).
     The user must log into X manually in the Chrome window that appears.
     Do NOT kill Chrome — run this scraper against the live session.

  2. Run: python cdp-ws-scraper.py [--port 9229] [--target https://x.com/user]

Requires: websockets (pip install websockets)
Environment variables:
  CDP_PORT          CDP port (default: 9229)
  CDP_TARGET        Target URL to navigate to (default: https://x.com/marclou)
  CDP_MAX_SCROLLS   Max scroll iterations (default: 2000)
  CDP_PAUSE_MS      Base pause between scrolls in ms (default: 8000 — SLOW to avoid rate limits)
  CDP_EMPTY_LIMIT   Stop after this many empty scrolls (default: 20)
  CDP_OUTPUT        Output file path (default: TEMP/cdp_scrape_results.json)
  CDP_SAVE_INTERVAL Save progress every N seconds (default: 60)
  CDP_REQUEST_LOG   Log file for request counting (default: TEMP/cdp_request_log.csv)
  CDP_RECV_TIMEOUT  Timeout in seconds for each WebSocket recv (default: 30 — prevents hangs)
"""

import asyncio, json, urllib.request, os, sys, time

# Defaults — slow by design to respect X rate limits
CDP_PORT = int(os.environ.get("CDP_PORT", "9229"))
TARGET = os.environ.get("CDP_TARGET", "https://x.com/marclou")
MAX_SCROLLS = int(os.environ.get("CDP_MAX_SCROLLS", "2000"))
PAUSE_MS = int(os.environ.get("CDP_PAUSE_MS", "8000"))  # 8s base delay
EMPTY_LIMIT = int(os.environ.get("CDP_EMPTY_LIMIT", "20"))
SAVE_INTERVAL = int(os.environ.get("CDP_SAVE_INTERVAL", "60"))
RECV_TIMEOUT = int(os.environ.get("CDP_RECV_TIMEOUT", "30"))  # per-recv timeout
OUTPUT = os.environ.get("CDP_OUTPUT", os.environ.get("TEMP", ".") + "/cdp_scrape_results.json")
CHECKPOINT_DIR = os.path.join(os.path.dirname(OUTPUT), "checkpoints")


async def send_cmd(ws, cmd_id, method, params=None):
    """Send a CDP command and wait for response with timeout.

    CRITICAL: Without a timeout on ws.recv(), this can hang forever if Chrome
    stops responding (rate-limited, page crashed, WebSocket disconnected).
    Use asyncio.wait_for to enforce a deadline per-call.
    """
    msg = json.dumps({"id": cmd_id, "method": method, "params": params or {}})
    await ws.send(msg)
    resp = await asyncio.wait_for(ws.recv(), timeout=RECV_TIMEOUT)
    return json.loads(resp)


async def check_rate_limited(ws):
    """Detect X rate limit pages by checking page body text."""
    resp = await send_cmd(ws, 9990, "Runtime.evaluate", {
        "expression": "document.body?.innerText?.substring(0,200) || ''",
        "returnByValue": True,
        "awaitPromise": True
    })
    body = (resp.get("result", {}).get("result", {}).get("value", "") or "").lower()
    indicators = ["rate limit", "rate_limit", "too many requests",
                  "try again later", "something went wrong",
                  "retry", "please wait", "blocked", "temporarily"]
    return any(i in body for i in indicators)


async def check_logged_in(ws):
    """Check if X session is active using multiple DOM indicators.

    IMPORTANT: Do NOT rely on a single selector. In practice,
    [data-testid="AppTabBar_Profile"] can return False even when the user
    IS logged in — it may not render on certain page types (e.g. when viewing
    another user's profile). The account switcher and new-tweet button are
    more reliable signals.
    """
    resp = await send_cmd(ws, 9991, "Runtime.evaluate", {
        "expression": """(() => {
    const selectors = [
        '[data-testid="SideNav_AccountSwitcher_Button"]',
        '[data-testid="SideNav_NewTweet_Button"]',
        '[data-testid="AppTabBar_Profile_Tab"]',
        'header[role="banner"] nav a[href*="/settings"]',
    ];
    return selectors.some(s => !!document.querySelector(s));
})()""",
        "returnByValue": True
    })
    return resp.get("result", {}).get("result", {}).get("value", False)


def save_snapshot(tweets, suffix=""):
    """Save tweets to output file, optionally with a checkpoint suffix."""
    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    path = OUTPUT.replace(".json", f"{suffix}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tweets, f, ensure_ascii=False, indent=2)
    return path


async def main():
    import websockets

    # Discover page targets via HTTP (GET /json still works in Chrome 148)
    cdp_http = f"http://127.0.0.1:{CDP_PORT}"
    with urllib.request.urlopen(f"{cdp_http}/json") as f:
        targets = json.loads(f.read())

    pages = [t for t in targets if t["type"] == "page"]
    if not pages:
        print("ERROR: No page target found")
        sys.exit(1)

    # Prefer a page already on the target domain
    page = next((t for t in pages if TARGET.split("/")[2] in t.get("url", "")), pages[0])
    ws_url = page["webSocketDebuggerUrl"]
    print(f"Page: {page.get('url', '?')[:60]}")
    print(f"WS: {ws_url}")
    sys.stdout.flush()

    # Wrap the ENTIRE session in a hard outer timeout so a single hung command
    # doesn't block the script forever. 600s = 10 minutes.
    async with asyncio.timeout(600):
        async with websockets.connect(ws_url) as ws:
            # Enable domains
            await send_cmd(ws, 1, "Runtime.enable")

            # Navigate to target
            print("Navigating...")
            sys.stdout.flush()
            await send_cmd(ws, 2, "Page.navigate", {"url": TARGET})
            await asyncio.sleep(max(PAUSE_MS / 1000, 6))

            # Check login
            logged_in = await check_logged_in(ws)
            print(f"Logged in: {logged_in}")
            sys.stdout.flush()

            if not logged_in:
                print("WARNING: Not logged in. Waiting up to 5 min for user to log in...")
                sys.stdout.flush()
                for i in range(60):
                    await asyncio.sleep(5)
                    logged_in = await check_logged_in(ws)
                    if logged_in:
                        print(f"  Logged in after {i*5+5}s!")
                        sys.stdout.flush()
                        break
                else:
                    print("Never logged in. Aborting.")
                    sys.stdout.flush()
                    return

            # Initial tweet count
            resp = await send_cmd(ws, 3, "Runtime.evaluate", {
                "expression": "document.querySelectorAll('[data-testid=\"tweet\"]').length"
            })
            print(f"Initial articles: {resp.get('result', {}).get('result', {}).get('value', 0)}")
            sys.stdout.flush()

            # Scroll and collect
            seen = {}
            empty_runs = 0
            rate_limit_hits = 0
            current_delay = PAUSE_MS / 1000
            last_save = time.time()
            start_time = time.time()

            for i in range(MAX_SCROLLS):
                # Check rate limiting before scrolling
                if await check_rate_limited(ws):
                    rate_limit_hits += 1
                    wait = min(30 * rate_limit_hits, 120)
                    print(f"\n⚠️  Rate limited! Waiting {wait}s (hit #{rate_limit_hits})")
                    sys.stdout.flush()
                    await asyncio.sleep(wait)
                    current_delay = min(30, current_delay + 5)
                    if rate_limit_hits >= 5:
                        print("Too many rate limits. Saving and stopping.")
                        sys.stdout.flush()
                        break
                    continue

                rate_limit_hits = 0

                # Scroll
                await send_cmd(ws, 1000 + i, "Runtime.evaluate", {
                    "expression": "window.scrollBy(0, window.innerHeight * 1.5)"
                })
                await asyncio.sleep(current_delay)

                # Extract tweets
                resp = await send_cmd(ws, 2000 + i, "Runtime.evaluate", {
                    "expression": """
(() => {
    const results = [];
    const articles = document.querySelectorAll('article[data-testid="tweet"]');
    for (const a of articles) {
        const allLinks = a.querySelectorAll('a[href*="/status/"]');
        let tweetUrl = '';
        for (const l of allLinks) {
            const href = l.getAttribute('href') || '';
            if (href.includes('/status/') && !href.includes('/analytics')) {
                tweetUrl = 'https://x.com' + href.split('?')[0];
                break;
            }
        }
        if (!tweetUrl) continue;
        const id = tweetUrl.match(/\/status\/(\d+)/)?.[1] || '';
        const textEl = a.querySelector('[data-testid="tweetText"]');
        const text = textEl ? textEl.textContent.trim() : '';
        const timeEl = a.querySelector('time');
        const time = timeEl ? timeEl.getAttribute('datetime') : '';
        const likeEl = a.querySelector('[data-testid="like"]');
        const likes = likeEl ? (likeEl.textContent || '0') : '0';
        const rtEl = a.querySelector('[data-testid="retweet"]');
        const rts = rtEl ? (rtEl.textContent || '0') : '0';
        const replyEl = a.querySelector('[data-testid="reply"]');
        const replies = replyEl ? (replyEl.textContent || '0') : '0';
        results.push({id, url: tweetUrl, text, datetime: time, likes, retweets: rts, replies});
    }
    return JSON.stringify(results);
})()
"""
                })

                raw = resp.get("result", {}).get("result", {}).get("value", "[]")
                try:
                    tweets = json.loads(raw)
                except json.JSONDecodeError:
                    tweets = []

                before = len(seen)
                for t in tweets:
                    tid = t.get("id", "")
                    if tid and tid not in seen:
                        seen[tid] = t

                new_count = len(seen) - before

                # Adaptive delay
                if new_count > 0:
                    empty_runs = 0
                    current_delay = max(current_delay - 0.5, 6)
                else:
                    empty_runs += 1
                    current_delay = min(current_delay + 1, 30)

                elapsed = int(time.time() - start_time)
                print(f"\r  Scroll {i+1}: +{new_count} new (total: {len(seen)}) [{elapsed}s, delay={current_delay:.0f}s]  ", end="")
                sys.stdout.flush()

                # Auto-stop
                if empty_runs >= EMPTY_LIMIT:
                    print(f"\n{EMPTY_LIMIT} empty scrolls — reached end")
                    sys.stdout.flush()
                    break

                # Periodic save
                now = time.time()
                if now - last_save > SAVE_INTERVAL:
                    last_save = now
                    save_snapshot(list(seen.values()))
                    print(f"\n  💾 Saved ({len(seen)} tweets)")
                    sys.stdout.flush()

            # Final save
            results = list(seen.values())
            results.sort(key=lambda t: t.get("datetime", ""))
            final_path = save_snapshot(results)
            elapsed = int(time.time() - start_time)

            print(f"\n{'='*50}")
            print(f"Collection complete!")
            print(f"  Total tweets: {len(results)}")
            print(f"  Scrolls: {i+1}")
            print(f"  Time: {elapsed}s ({elapsed//60}m {elapsed%60}s)")
            print(f"  Avg delay: {elapsed/max(i+1,1):.1f}s/scroll")
            print(f"  Saved to: {final_path}")

            dates = [t.get("datetime","")[:10] for t in results if t.get("datetime")]
            if dates:
                print(f"  Date range: {min(dates)} to {max(dates)}")

            sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(main())
