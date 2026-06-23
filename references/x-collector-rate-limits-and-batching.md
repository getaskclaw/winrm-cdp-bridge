# OpenCLI X/Twitter Rate Limits and Batch Collection Strategies

## The `tweets` command's real limitations

`opencli twitter tweets <user> --limit N -f json` has three hard constraints that are not obvious:

1. **No date filtering** — the `--date-start`/`--date-end` in `xtimeline-db collect-tweets` filters *after* collection. OpenCLI's `tweets` command does not support date-range parameters. Every call fetches the same result set regardless of window.

2. **Hard cap at ~200 tweets** — X's internal UserTweets GraphQL endpoint returns at most ~200 tweets per user regardless of `--limit`. Setting `--limit 500` or `--limit 1000` does not expand the result. For accounts with fewer than 200 tweets total, you get them all. For active accounts, you get the most recent ~200.

3. **No cursor pagination** — `next_cursor` is always null in the page state. The `tweets` endpoint does not support pagination through OpenCLI's browser bridge.

### What this means in practice

Running `collect-tweets` with date windows does NOT extend historical reach:

```python
# Both calls below return the SAME ~200 most recent tweets.
# The date_start/date_end do NOT affect the OpenCLI call.

collect-tweets --target marclou --date-start 2026-01-01T00:00:00Z --date-end 2026-05-15T23:59:59Z
collect-tweets --target marclou --date-start 2022-01-01T00:00:00Z --date-end 2022-12-31T23:59:59Z
```

Only the first call produces new tweets (if within the retention window). The second produces 0 new because the same tweets are already in the DB (deduped) and none fall in the 2022 window.

### Monthly windows vs weekly windows

Since every call returns ~200 tweets regardless, **monthly windows are always better than weekly**:

| Strategy | Calls | Total tweets | OpenCLI calls to X | 429 risk |
|----------|-------|-------------|-------------------|----------|
| Weekly (229 runs) | 229 | ~200 | 229 identical calls | High |
| Monthly (52 runs) | 52 | ~200 | 52 identical calls | Moderate |
| Single call | 1 | ~200 | 1 | None |

Use monthly windows only when the goal is labeling/export — never to extend historical reach.

## HTTP 429 / "queryId expired" rate limiting

### Pattern

After ~5-10 sequential `tweets` calls against the same user, X's internal GraphQL returns:

```json
{
  "code": "COMMAND_EXEC",
  "message": "HTTP 429: UserTweets fetch failed — queryId may have expired"
}
```

The 429 persists for minutes to hours, then self-recovers. This is X's rate limit on the UserTweets internal API, not OpenCLI's limit. It is triggered by call count against the same browser session, not by call frequency.

### Gaps don't help

Testing showed 90-second gaps still triggered 429 after ~5-10 calls. The browser bridge session shares a single X API session — the rate limit accumulates across all calls until the session is refreshed.

### Workarounds

1. **Session refresh** — run `opencli profile use <profile>` between batches to rotate the browser session. Each profile switch creates a fresh X session with a fresh rate-limit counter.

2. **Spread over time** — 5 calls per batch, then wait hours (not seconds). The rate limit decays over time but slowly. Overnight batching helps.

3. **Use `search "from:user"` instead** — `opencli twitter search "from:marclou" --product live -f json` hits a different X endpoint (`/i/api/graphql/SearchTimeline`) with different rate limits. May sustain more calls before 429.

4. **CDP browser scrolling** — bypass OpenCLI entirely. Navigate to `x.com/user` in a Chrome tab, use CDP to scroll repeatedly (triggers X to load older tweets), extract from DOM. No OpenCLI rate limits, no 429. The tradeoff is CDP setup complexity.

## CDP scrolling for full historical collection

### How it works

Instead of calling OpenCLI's `tweets` command, navigate Chrome to the user's X profile and scroll. Each scroll triggers X's web UI to load older tweets via its own pagination. This can go back much further than the ~200 tweet cap.

### Prerequisites on Windows host

1. Chrome with X logged in (the one OpenCLI's browser bridge uses)
2. User enables `chrome://inspect/#remote-debugging` and checks "Allow remote debugging" (resets on Chrome restart)
3. CDP port (typically 9222) is accessible

### Chrome 148+ CDP changes

In Chrome 148, the "Allow remote debugging" toggle binds a TCP port BUT does NOT serve the standard HTTP CDP API. `/json/version` and `/json/list` return 404. The toggle enables mDNS/WebSocket discovery for DevTools on the same machine only.

For the separate `--remote-debugging-port` approach (launching Chrome with a fresh temp profile):

- **GET `/json/version` and `/json/list`** WORK — return valid JSON with browser metadata and target list
- **BUT `curl` returns empty** due to Chrome 148's origin blocking (only allows `chrome://` and `devtools://` origins). Use `System.Net.Http.HttpClient` from PowerShell instead, or run Python natively on the Windows host (no origin issue):
  ```powershell
  Add-Type -AssemblyName System.Net.Http
  $client = New-Object System.Net.Http.HttpClient
  $resp = $client.GetAsync("http://127.0.0.1:<port>/json/version").Result
  $content = $resp.Content.ReadAsStringAsync().Result
  ```
- **POST `/devtools/page/<id>`** returns HTTP 200 with `Content-Length: 0` — the command is accepted but no response body. Must use WebSocket.
- **Chrome 148+ on Windows merges ALL new instances** — even with a different `--user-data-dir`, you cannot run two Chrome instances from the same binary. Every `Start-Process` silently merges into the already-running Chrome process. Use Chrome Canary (separate binary) if you need a CDP-capable Chrome alongside the user's existing session.

**Summary table for Chrome 148 CDP:**

| Endpoint | `curl` (remote) | .NET HttpClient (local) | Python on Windows (local) |
|----------|----------------|------------------------|---------------------------|
| GET `/json/version` | Empty (origin block) | ✅ Works | ✅ Works |
| GET `/json/list` | Empty (origin block) | ✅ Works | ✅ Works |
| POST `/json/new?url=` | Empty | Empty | Empty |
| POST `/devtools/page/<id>` | Empty body | Empty body | Empty body |
| WebSocket `ws://...` | N/A | N/A | ✅ Full CDP |

### Scroll-and-extract pattern

```python
# WinRM → PowerShell → CDP WebSocket → Chrome
# 1. Connect to CDP WebSocket endpoint (ws://127.0.0.1:<port>/devtools/page/<tab-id>)
# 2. Send Page.enable, then Runtime.evaluate("window.scrollTo(0, document.body.scrollHeight)")
# 3. Wait 2-3s for tweets to load
# 4. Runtime.evaluate to extract tweet data from DOM
# 5. Repeat 20-50 times
# 6. Deduplicate by tweet ID
```

### Observed CDP scroll limits (May 2026)

In practice, X's web profile page saturates after ~55 scrolls yielding ~99 unique tweets regardless of account size:
- @marclou (active daily poster): 55 scrolls → 99 tweets (Jan 2023 – May 2026)
- Fewer tweets for less active accounts
- No additional tweets load after 10-12 consecutive "no new" scrolls
- Increasing scroll delay from 1.5s to 3s doesn't change the cap — it's X's lazy-load limit, not a rate limit

**Root cause:** X's web UI loads tweets in batches of ~12, and the lazy-loader stops fetching after ~8-10 batches regardless of how far you scroll. This is functionally the same ~200 tweet cap as the OpenCLI `tweets` command, just loaded from the DOM instead of the API.

For full historical archives, X API v2 is the only reliable path (up to 3,200 tweets with cursor pagination).

## X API v2 as the cleanest alternative

For any serious full-history collection, the X API v2 is dramatically better:

| Factor | OpenCLI / CDP | X API v2 |
|--------|--------------|----------|
| Tweets per user | ~200 max | Up to 3,200 |
| Historical depth | ~6-12 months | Full history |
| Rate limit | ~5-10 calls then 429 | 100 req/15min (documented) |
| Pagination | None | Cursor-based |
| Parallelism | No (shared session) | Yes (stateless) |
| Setup | Zero (just login) | Needs bearer token |
| Cost | Free | Free tier exists; Basic $100/mo |

Rule of thumb: use OpenCLI for quick looks (<200 tweets, recent only). Use X API v2 for full archives. Use CDP scrolling as a fallback when you can't get API credentials but need more than 200 tweets.
