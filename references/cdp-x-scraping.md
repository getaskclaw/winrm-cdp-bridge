# X.com CDP Browser Scraping

## When to use this

- You need tweets BEYOND OpenCLI's ~200 cap
- The X API v2 is not available (no bearer token)
- OpenCLI rate limits (429 after ~5-10 calls) are blocking historical collection
- You want to scroll the profile page like a human and extract visible tweets

## The approach

Navigate Chrome to `https://x.com/<user>`, scroll repeatedly to trigger X's lazy loading, and extract tweet data from the DOM via CDP Runtime.evaluate. Requires a Chrome instance with X logged in and CDP WebSocket access.

## Prerequisites

- Chrome on Windows with `--remote-debugging-port=<port>` and a fresh `--user-data-dir`
- Python 3.12+ with `websockets` library on the Windows host
- User logged into X in that Chrome window (login persists while Chrome stays running)

## X.com DOM selectors (verified May 2026)

| Data | Selector | Notes |
|------|----------|-------|
| Tweet container | `article[data-testid="tweet"]` | Each tweet is an article element |
| Tweet text | `[data-testid="tweetText"]` | Returns textContent (may contain emoji that JSON.stringify mishandles) |
| Tweet URL | `a[href*="/status/"]` (NOT containing `/analytics`) | X includes an analytics link per tweet — filter it out |
| Tweet ID | extracted from URL: `/status/(\d+)` | Stable identifier for dedup |
| Timestamp | `time[datetime]` | ISO 8601 string, e.g. `2025-02-20T15:15:01.000Z` |
| Like count | `[data-testid="like"]` | Text content like "11K", "1.6K", or "0" |
| Retweet count | `[data-testid="retweet"]` | Same format as likes |
| Reply count | `[data-testid="reply"]` | Same format as likes |
| Login check | `[data-testid="SideNav_AccountSwitcher_Button"]` | Exists when logged in, null when logged out |

## URL extraction — critical detail

X puts TWO links in each tweet article: one to the tweet and one to `/analytics`. The analytics link must be filtered out:

```javascript
const allLinks = article.querySelectorAll('a[href*="/status/"]');
let tweetUrl = '';
for (const a of allLinks) {
    const href = a.getAttribute('href') || '';
    if (href.includes('/status/') && !href.includes('/analytics')) {
        tweetUrl = 'https://x.com' + href.split('?')[0];
        break;
    }
}
```

## Scroll and extract pattern

```python
for i in range(max_scrolls):
    # Scroll down one viewport height
    ws.send(json.dumps({"id": i+1, "method": "Runtime.evaluate",
        "params": {"expression": "window.scrollBy(0, window.innerHeight * 1.5)",
                   "returnByValue": True}}))
    time.sleep(scroll_delay)
    
    # Extract tweets
    ws.send(json.dumps({"id": i+2, "method": "Runtime.evaluate",
        "params": {"expression": JS_EXTRACTOR, "returnByValue": True}}))
    resp = json.loads(ws.recv())
    raw = resp.get("result", {}).get("result", {}).get("value", "[]")
    tweets = json.loads(raw)
```

## Observed scroll performance (May 2026, @marclou)

Scroll performance depends heavily on your delay setting — slower = more data, less rate limiting.

### With 8-10s scroll delay (polite, rate-limit-safe)

| Metric | Value |
|--------|-------|
| Scroll delay | 10s |
| Scrolls until stall | ~55-60 before 600s outer timeout fires |
| Tweets collected per run | ~100-185 (varies with total timeout) |
| Tweets per scroll (typical) | 1-5 new in early scrolls, tapering to 0-2 |
| Scroll pixel depth per cycle | ~1,104px (one viewport) |
| Total pixels scrolled (60 scrolls) | ~60,000-70,000px |
| Total time for 60 scrolls | ~10 min |
| Outer timeout effect | Saves at last checkpoint (~scroll 30 with 60 tweets), losing ~40 tweets if timeout fires at scroll 60 |

### With 1.5s scroll delay (aggressive, rate-limit-prone)

| Metric | Value |
|--------|-------|
| Scroll delay | 1.5s |
| Scrolls before saturation | ~55 |
| Unique tweets extracted | ~99 |
| Flat scrolls before abort | 10-12 |
| Time per scroll cycle | ~2s (1.5s delay + 0.5s JS eval) |
| Total time for full collection | ~2 min |
| Top tweet likes (example) | 11K, 2.4K, 2.1K, 2K, 1.9K |

**Key insight:** Slower scrolling (8-10s) gives you ~2x more tweets before hitting X's hard stop vs aggressive 1.5s scrolling, but takes 5x longer. X's web profile view loads approximately 2 years of tweets via lazy scroll before hitting a hard stop. The fundamental limit is the same ~200 cap you hit with OpenCLI, just reached from the DOM instead of the API.

**For more tweets:** Use X API v2 with cursor pagination.

### Checkpoint loss — critical design pattern

The CDP scraper keeps tweets in a **volatile in-memory dict** (`all_tweets[tweet_id] = tweet`). Periodic saves happen every N scrolls or every N seconds. If the scraper is killed between checkpoints (outer timeout, Chrome crash, hard process kill), the tweets collected since the last save are **permanently lost**.

In one observed run with a 600s outer timeout:
- Save interval: every 30 scrolls
- Outer timeout fired at scroll 59 (101 tweets total)
- Last save was at scroll 30 (59 tweets)
- **42 tweets lost** (scrolls 31-59)

**Fix — multiple layers:**
1. **Save more frequently:** every 10 scrolls, not 30. This caps the gap at ~10 scrolls (~100s of work)
2. **Save on every exception path:** the `except`/`finally` blocks should call `save_output(all_tweets)` before the process exits
3. **Use a longer outer timeout:** 1800s (30 min) instead of 600s for large accounts, or remove outer timeout entirely and rely on per-command timeouts
4. **Alternative:** write each new tweet to a persistent queue (file or SQLite) immediately on discovery, not just at checkpoint intervals

### Dedup — in-memory dict keyed by tweet ID

Each tweet has a stable `/status/{id}` from the status link. The scraper keys an `all_tweets` dict by this ID:

```python
all_tweets = {}
for t in tweets_from_scroll:
    tid = t.get("id", "")
    if tid and tid not in all_tweets:
        all_tweets[tid] = t
        new_count += 1
```

**Limitations:**
- **No cross-run dedup.** Each scraper run starts with an empty dict. If you run the scraper twice, the second run will re-collect tweets already saved in the first run's JSON.
- **No dedup against existing data.** The scraper doesn't query the x-timeline-sqlite DB or signals.db to skip already-known tweets.
- **No gap detection.** If X skips serving certain tweets (algorithmic ranking, rate-limit shadowing), the scraper has no way to know it missed them.

**Cross-referencing against reference data:** After a CDP scraper run, compare results against any existing OpenCLI-collected data (e.g., from x-timeline-sqlite) to measure coverage. The OpenCLI `tweets` command returns ~200 recent tweets; the CDP scraper should match or exceed that count. If the CDP count is lower, check if the scraper ran long enough (enough scrolls) or if X served older tweets.

Example cross-reference check:

```python
# Get tweet IDs from CDP scraper output
cdp_ids = {t["id"] for t in cdp_results}

# Get tweet IDs from x-timeline-sqlite items table (via SSH)
ssh_items = [...]  # IDs from DB query

# Find what CDP missed
missing = ssh_items - cdp_ids
print(f"CDP has {len(cdp_ids)}, reference has {len(ssh_items)}, missing: {len(missing)}")
```

This tells you whether the CDP scraper is covering the same ground or if there are structural gaps.

## Handling page state

```python
def evaluate(ws, js):
    """Execute JS via CDP and return the result value."""
    resp = send_cmd(ws, "Runtime.evaluate", {
        "expression": js,
        "returnByValue": True,
        "awaitPromise": True  # needed for async DOM operations
    })
    return resp.get("result", {}).get("result", {}).get("value")

# Check if page is still on the right URL
url = evaluate(ws, "window.location.href")
if "marclou" not in url:
    send_cmd(ws, "Page.navigate", {"url": "https://x.com/marclou"})
    time.sleep(4)

# Check login state
logged_in = evaluate(ws, 
    "!!document.querySelector('[data-testid=\"SideNav_AccountSwitcher_Button\"]')")
if not logged_in:
    # Navigate to login page and ask user
    send_cmd(ws, "Page.navigate", {"url": "https://x.com/i/flow/login"})
    # Tell user to log in
```

## Logging the user in

When using a fresh temp profile (no existing login):

1. Navigate Chrome to `https://x.com/i/flow/login` via CDP
2. A Chrome window appears on the Windows desktop showing the X login form
3. Tell the user to log in
4. Wait ~30 seconds
5. Verify login state via CDP (`SideNav_AccountSwitcher_Button` presence)
6. Navigate to target profile and start scraping

## Session lifetime

On a temp profile (`$env:TEMP`), the X login session persists as long as Chrome keeps running. If Chrome is left idle for ~30+ minutes, X may show the login screen again on refresh. Save cookies via CDP if you need to recover the session later:
- `document.cookie` returns only non-HttpOnly cookies
- For full cookie recovery, use Chrome's CDP `Network.getAllCookies` method

## Common pitfalls

1. **JSON.stringify corruption.** Emoji and special characters in tweet text can produce invalid JSON when passed through CDP's Runtime.evaluate. The text `"Show up daily 💪" a lot can change"` becomes `"Show up daily 💪\" a lot can change"` — an unescaped quote. **Fix:** Use `JSON.stringify()` in JavaScript (which handles escaping) rather than building JSON manually. If corruption still occurs, try cleaning with `cleaned = val.replace('\\\\"', "'").replace('\\"', "'")` as a fallback.

2. **Login expires silently.** The temp profile's X session expires after ~30 minutes idle. Always verify login state before starting a long scroll run.

3. **Scroll rate limiting.** X may rate-limit rapid scrolling. If you hit 0 new tweets for several consecutive scrolls, try increasing the scroll delay from 1.5s to 3s. Change Scroll behavior from `scrollBy(0, window.innerHeight * 1.5)` to `window.scrollTo(0, document.body.scrollHeight)` to trigger different lazy-load paths.

4. **Page awareness of automation.** X's web client may detect non-human scroll patterns and show a "You've been away" interstitial. If this happens, the page needs a reload (`Page.reload` via CDP) and a re-navigate to the profile.

5. **CDP session cleanup.** Always call `ws.close()` after scraping to avoid leaking WebSocket connections. Chrome accumulates zombie devtools sessions if you don't close cleanly.

## Complete scraper pattern

The reusable CDP WebSocket scraper lives in `remote-windows-browser-automation`'s `scripts/cdp-ws-scraper.py`. Adapt for X.com by:
1. Setting `PAGE_WS_URL` to the target page's WebSocket URL
2. Adjusting `MAX_SCROLLS` and `SCROLL_DELAY` based on account activity
3. Using the X.com DOM selectors above
4. Filtering out `/analytics` URLs
- Saving output as JSON + markdown

## X Search — bypassing the profile timeline limit

When profile timeline scrolling stops serving new tweets after ~14 months, use **X search** with date filters:

```
https://x.com/search?q=from%3A<user>%20since%3A2022-01-01%20until%3A2024-12-31&f=live
```

This hits X's SearchTimeline endpoint instead of UserTweets. Different endpoint, different retention. Observed coverage:

- Profile scroll: ~14 months (Mar 2025 → Apr 2026), 656 tweets
- X search: ~3 months (Oct 27 → Dec 29, 2024), 968 tweets
- Merged (zero overlap): Oct 2024 → Apr 2026, **1,624 tweets**

Key finding: zero overlap across the two approaches. Profile won't serve older than ~Mar 2025; search won't serve newer than ~Dec 2024. They are complementary, not alternatives.

Usage: Navigate Chrome to the search URL via CDP `Page.navigate`, then run a scroll scraper against that tab. The existing `scripts/cdp-ws-search-scraper.py` in `remote-windows-browser-automation` does this. Strategy: run search first (oldest tweets), then profile scroll (recent tweets), merge by tweet ID.
