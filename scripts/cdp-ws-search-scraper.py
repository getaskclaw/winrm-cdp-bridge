#!/usr/bin/env python3
"""CDP WebSocket search scraper — scroll X search results for historical tweets.

Use when profile timeline scrolling stops serving old tweets. X search can
bypass the ~14mo profile limit and reach ~3mo deeper into the archive.

Usage:
  1. Have a Chrome with CDP running on the Windows host, logged into X.
  2. Navigate to a search URL first (via CDP Page.navigate or manually):
     https://x.com/search?q=from%3A<user>%20since%3A2022-01-01%20until%3A2024-12-31&f=live
  3. Run: python cdp-ws-search-scraper.py

Environment variables:
  CDP_PORT          CDP port (default: 9250)
  CDP_MAX_SCROLLS   Max scroll iterations (default: 500)
  CDP_PAUSE_MS      Base pause between scrolls in ms (default: 8000)
  CDP_EMPTY_LIMIT   Stop after this many empty scrolls (default: 20)
  CDP_OUTPUT_DIR    Output directory (default: marclou_archive on Desktop)
  CDP_WS_URL        Force a specific WebSocket URL (skip page discovery)
"""

import asyncio, json, urllib.request, os, sys, time, re
from datetime import datetime

# Config
PORT = int(os.environ.get("CDP_PORT", "9250"))
MAX_SCROLLS = int(os.environ.get("CDP_MAX_SCROLLS", "500"))
PAUSE_MS = int(os.environ.get("CDP_PAUSE_MS", "8000"))
EMPTY_LIMIT = int(os.environ.get("EMPTY_LIMIT", "20"))
OUT_DIR = os.environ.get("CDP_OUTPUT_DIR",
    os.path.expandvars("%USERPROFILE%\\Desktop\\marclou_archive"))
WS_URL_OVERRIDE = os.environ.get("CDP_WS_URL", "")

SAVE_EVERY = 10  # save progress every N scrolls
RECV_TIMEOUT = 30

LOG = os.path.join(OUT_DIR, "search_scraper.log")
os.makedirs(OUT_DIR, exist_ok=True)


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except:
        pass


async def ws_send_recv(ws, msg_id, method, params=None, timeout=RECV_TIMEOUT):
    """Send CDP command, wait for response with timeout. Never block forever."""
    msg = json.dumps({"id": msg_id, "method": method, "params": params or {}})
    await ws.send(msg)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = json.loads(await asyncio.wait_for(ws.recv(), max(1, deadline - time.time())))
            if resp.get("id") == msg_id:
                return resp
        except asyncio.TimeoutError:
            break
        except Exception:
            break
    return {"error": "timeout"}


async def main():
    import websockets

    # Resolve WS URL
    ws_url = WS_URL_OVERRIDE
    if not ws_url:
        url = f"http://127.0.0.1:{PORT}/json"
        with urllib.request.urlopen(url, timeout=5) as f:
            targets = json.loads(f.read())
        pages = [t for t in targets if t.get("type") == "page"]
        # Prefer a search page tab
        for t in pages:
            if "search" in t.get("url", ""):
                ws_url = t["webSocketDebuggerUrl"]
                log(f"Found search tab: {t.get('url', '')[:80]}")
                break
        if not ws_url:
            for t in pages:
                if "x.com" in t.get("url", ""):
                    ws_url = t["webSocketDebuggerUrl"]
                    log(f"Fallback to x.com tab")
                    break
        if not ws_url:
            log("ERROR: No suitable tab found")
            return

    log(f"WS={ws_url}")
    all_tweets = {}
    no_new_count = 0
    last_save_time = time.time()

    try:
        async with websockets.connect(ws_url, close_timeout=10) as ws:
            log("Connected!")
            await asyncio.sleep(4)

            # Check page loaded
            pagetitle = await ws_send_recv(ws, 1, "Runtime.evaluate", {
                "expression": "document.title", "returnByValue": True
            })
            title = pagetitle.get("result", {}).get("result", {}).get("value", "?")
            log(f"Title: {title[:60]}")

            # Check login (multi-selector)
            login_check = await ws_send_recv(ws, 2, "Runtime.evaluate", {
                "expression": """
(() => {
    const s = ['[data-testid="SideNav_AccountSwitcher_Button"]',
               '[data-testid="SideNav_NewTweet_Button"]',
               '[data-testid="AppTabBar_Profile_Tab"]'];
    return s.some(x => !!document.querySelector(x));
})()
""",
                "returnByValue": True
            })
            logged_in = login_check.get("result", {}).get("result", {}).get("value", False)
            log(f"Logged in: {logged_in}")

            # Initial tweet count
            tc = await ws_send_recv(ws, 3, "Runtime.evaluate", {
                "expression": "document.querySelectorAll('article[data-testid=\"tweet\"]').length",
                "returnByValue": True
            })
            initial = tc.get("result", {}).get("result", {}).get("value", 0)
            log(f"Initial tweets on page: {initial}")

            if initial == 0:
                body = await ws_send_recv(ws, 4, "Runtime.evaluate", {
                    "expression": "document.body?.innerText?.substring(0,300) || ''",
                    "returnByValue": True
                })
                snippet = body.get("result", {}).get("result", {}).get("value", "")[:200]
                log(f"Body: {snippet}")

            # Scroll & extract loop
            for scroll in range(1, MAX_SCROLLS + 1):
                # Scroll
                await ws_send_recv(ws, 100 + scroll, "Runtime.evaluate", {
                    "expression": "window.scrollBy(0, window.innerHeight * 2)",
                    "returnByValue": True
                }, timeout=15)

                await asyncio.sleep(PAUSE_MS / 1000)

                # Extract tweets (broad — any /status/ link)
                result = await ws_send_recv(ws, 200 + scroll, "Runtime.evaluate", {
                    "expression": r"""
(() => {
    const tweets = [];
    const articles = document.querySelectorAll('article[data-testid="tweet"]');
    articles.forEach(article => {
        const links = article.querySelectorAll('a[href*="/status/"]');
        let url = '';
        links.forEach(a => {
            const h = a.getAttribute('href') || '';
            if (h.includes('/status/')) {
                const m = h.match(/\/status\/(\d+)/);
                if (m) url = 'https://x.com' + h.split('?')[0];
            }
        });
        if (!url) return;
        const id = url.match(/\/status\/(\d+)/)?.[1] || '';
        if (!id) return;
        const textEl = article.querySelector('[data-testid="tweetText"]');
        const text = textEl ? textEl.textContent.trim() : '';
        const timeEl = article.querySelector('time');
        const datetime = timeEl ? timeEl.getAttribute('datetime') : '';
        const likeEl = article.querySelector('[data-testid="like"]');
        const likes = likeEl ? (likeEl.textContent || '0') : '0';
        const rtEl = article.querySelector('[data-testid="retweet"]');
        const rts = rtEl ? (rtEl.textContent || '0') : '0';
        const replyEl = article.querySelector('[data-testid="reply"]');
        const replies = replyEl ? (replyEl.textContent || '0') : '0';
        const authorEl = article.querySelector('[data-testid="User-Name"] a');
        const author = authorEl ? authorEl.textContent.trim() : '';
        tweets.push({id, url, text, datetime, likes, retweets: rts, replies, author});
    });
    return JSON.stringify(tweets);
})();
""",
                    "returnByValue": True
                }, timeout=20)

                new_count = 0
                try:
                    raw = result.get("result", {}).get("result", {}).get("value", "[]")
                    tweets = json.loads(raw) if isinstance(raw, str) else []
                    for t in tweets:
                        if t.get("id") and t["id"] not in all_tweets:
                            all_tweets[t["id"]] = t
                            new_count += 1
                except:
                    pass

                if new_count > 0:
                    no_new_count = 0
                else:
                    no_new_count += 1

                # Date range for logging
                dates = [t.get("datetime", "") for t in all_tweets.values() if t.get("datetime")]
                oldest = min(dates)[:10] if dates else "?"
                newest = max(dates)[:10] if dates else "?"

                log(f"Scroll {scroll}/{MAX_SCROLLS} | Tweets: {len(all_tweets)} (+{new_count}) | "
                    f"Oldest: {oldest} | Newest: {newest} | NoNew: {no_new_count}")

                # Periodic save
                if scroll % SAVE_EVERY == 0:
                    save_output(all_tweets)

                if no_new_count >= EMPTY_LIMIT:
                    log(f"No new tweets for {no_new_count} scrolls. Stopping.")
                    break

            # Final save
            save_output(all_tweets)
            log(f"DONE! Total: {len(all_tweets)} tweets")

    except asyncio.CancelledError:
        log("Cancelled — saving")
        save_output(all_tweets)
    except Exception as e:
        log(f"Error: {type(e).__name__}: {e}")
        save_output(all_tweets)


def save_output(tweets_dict):
    if not tweets_dict:
        return
    tweets = sorted(tweets_dict.values(), key=lambda t: t.get("datetime", ""))
    ts = datetime.now().strftime("%Y-%m-%d_%H%M")

    json_path = os.path.join(OUT_DIR, f"marclou_search_{ts}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(tweets, f, indent=2, ensure_ascii=False)

    md_path = os.path.join(OUT_DIR, f"marclou_search_{ts}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# @marclou Tweets — Search — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n\n")
        f.write(f"**Total: {len(tweets)} tweets**\n\n")
        for t in tweets:
            dt = t.get("datetime", "")[:19].replace("T", " ")
            author = t.get("author", "")[:20]
            like = t.get("likes", "0")
            rt = t.get("retweets", "0")
            reply = t.get("replies", "0")
            text = t.get("text", "")[:200].replace("\n", " ")
            url = t.get("url", "")
            f.write(f"- **{dt}** @{author} ❤️{like} 🔁{rt} 💬{reply}\n  {text}\n  {url}\n\n")

    log(f"Saved {len(tweets)} tweets to marclou_search_{ts}.*")


if __name__ == "__main__":
    asyncio.run(main())
