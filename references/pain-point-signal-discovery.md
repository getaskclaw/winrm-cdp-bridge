# Pain-Point Signal Discovery (Multi-Platform)

Workflow for discovering commercial pain points across X/Twitter, HackerNews, and Reddit. Designed for AskClaw lead-gen: find real problems → validate → approach with help.

## When to use

The user asks to:
- "find pain points" or "find signals" on social media
- "dig into" agent ops, accounting automation, or any commercial niche
- search X/Reddit/HN for "pain point", "I'll pay", "frustrating", "broken", "wish"
- set up persistent collection (cron-based, hours-long)

## Architecture

```
Linux (Hermes) ←WinRM/NTLM→ Windows 26429 (OpenCLI + logged-in Chrome)
     ↕                                 ↕
  Local storage                   Browser cookies
  (signals.md + signals.db)       (X logged in)
```

## Data sources and methods

### HackerNews — best signal density

- **Method:** `hn.algolia.com` API (public, no auth)
- **Command:** `curl -s "https://hn.algolia.com/api/v1/search?query=<keyword>&hitsPerPage=5"`
- **Returns:** Clean JSON with title, url, points, comments, author, created_at
- **Filter:** Points >= 2 for relevance
- **Keywords:** Use topic-specific terms — avoid generic HN queries that return SEO fluff

### Reddit hot — trend awareness, not targeted search

- **Method:** OpenCLI `reddit hot` (public API, `[public]` strategy)
- **Command:** `opencli reddit hot --limit 15 --format json`
- **WinRM from Python:** `session.run_ps("opencli reddit hot --limit 15 --format json")` — JSON is in stdout, no need for `2>&1` or `Out-String` gymnastics
- **Note:** Only hot posts, not targeted search (Reddit search needs CDP `[intercept]`)

### X/Twitter — highest noise but best real-time pain signals

Three working approaches (no CDP needed):

**1. Account tweets `[cookie]` (cleanest data)**
- `opencli twitter tweets <username> --limit 5 -f json`
- Returns: id, author, name, text, likes, retweets, replies, views, created_at, url, media
- Works on normally-launched Chrome — OpenCLI reads cookies directly
- Key accounts to monitor: LangChain, Anthropic, hwchase17, Xero, QuickBooks, BILL, Expensify

**2. Web read `[cookie]` (search, noisy but works)**
- `opencli web read --url "https://x.com/search?q=<encoded-query>&src=typed_query&f=live" --format markdown`
- Captures server-rendered HTML (first few tweets of a search)
- Noisy — needs text cleaning to strip garbled SSR characters, sidebar content, image refs
- Better than nothing when CDP is unavailable

**3. Trending `[cookie]`**
- `opencli twitter trending --limit 10 -f json`
- Returns current trending topics with categories

### What doesn't work (without CDP)
- `opencli twitter search` — uses `[intercept]` strategy, hangs/timeout
- `opencli reddit search` — uses `[intercept]` strategy
- `opencli twitter post/like/reply` — uses `[ui]` strategy

Check strategy type: `<adapter> <command> --help` → look for `Strategy:` line.

## Suggested keyword sets

### Agent Ops / SRE
```
agent monitoring, agent reliability, AI agent production, agent infrastructure,
LLM observability, agent debugging, agent ops, AI agent broke, agent production pain
```

### Accounting Automation
```
receipt OCR, invoice automation, bookkeeping, expense tracking,
accounting automation, small business accounting, accountant hours manual
```

### Generic pain signals
```
"pain point", "I'll pay", "I will pay", frustrating, broken, "I wish there was",
"this is so frustrating", "spent 3 hours", "manual work", "why can't I just"
```

## Cron-based persistent collection

Target: 12 runs × 30 min = 6 hours of collection

```python
# Cron job prompt template:
# Run /root/2604/collect_signals.py every 30m x 12 via python3.
# Script uses pywinrm to WinRM into Windows host for OpenCLI commands.
# Saves to /root/2604/signals/signals_YYYY-MM-DD.md + /root/2604/signals/signals.db
# Deliver findings summary back (major signals, pay signals, product launches)
```

### Storage model

**Markdown** (`signals_YYYY-MM-DD.md`):
- Human-readable, appended each run
- Sections: HN, Reddit, X Account Tweets, X Search, X Trending
- URLs, scores, comments, author names included

**SQLite** (`signals.db`):
```sql
CREATE TABLE signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_ts TEXT,
    source TEXT,        -- hn, reddit, x_tweets, x_webread
    topic TEXT,         -- agent_ops, accounting, general
    keyword TEXT,
    title TEXT,
    url TEXT,
    score INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    author TEXT,
    text_snippet TEXT,
    raw_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

## Scoring leads

| Signal | Hot | Warm | Cold |
|--------|-----|------|------|
| Tried something and it failed | ✅ | | |
| Spending manual hours on it | ✅ | | |
| Asking for recommendations | | ✅ | |
| Just venting, no action | | | ✅ |
| Posted in last 48h | ✅ | | |
| Has role that can pay | ✅ | | |

## Pitfalls

1. X `web read` captures SSR HTML only — JS-rendered content is missed. Expect 1-3 tweets per query, not full results.
2. Reddit hot returns general trending content, not niche posts. For targeted search, use HN or X.
3. Account tweets from brand accounts are mostly marketing, not pain signals. Focus on real users complaining.
4. WinRM NTLM auth can be slow (~5s per connection). Batch commands in single PowerShell sessions.
5. OpenCLI v1.7.x outputs "Extension update available" and "Update available" to stderr — filter these in `run_ps`.
6. X SSR text is garbled (mojibake, control chars). Clean with regex before displaying.
