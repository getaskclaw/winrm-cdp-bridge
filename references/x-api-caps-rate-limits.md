# X/Twitter API Caps & Rate Limits (via OpenCLI + CDP)

## OpenCLI endpoint caps

| Command | Strategy | Cap | Date Range | Notes |
|---------|----------|-----|------------|-------|
| `opencli twitter tweets <user>` | `[cookie]` | ~200 tweets | ~14 months back | Every call returns the SAME 200 most recent tweets regardless of `--limit` or date args. |
| `opencli twitter search 'from:<user>' --product live` | `[intercept]` | ~500 tweets | ~6 weeks back | `since:`/`until:` date operators are passed but X ignores them for recent-only search. |
| `opencli twitter search 'from:<user>' --product top` | `[intercept]` | ~500 tweets | Varies | Top results, no historical depth. |
| `opencli twitter profile <user>` | `[cookie]` | N/A metadata | Current | Bio, counts, location, verified. No cap issues. |

## Proactive rate-limit counting discipline

**The user WILL ask "how many requests did you make in the past hour / 30 min?"** Build request counting into every scraping script:

- Maintain a running counter of all X-bound requests (OpenCLI calls, CDP navigations, CDP scrolls, page loads).
- When asked, report by type: "20 OpenCLI API calls + 57 CDP scroll actions = ~77 total".
- OpenCLI and CDP share X's IP-level rate limit bucket — combine the counts.
- Script output should log each request as it happens (e.g. `[REQ #42] search from:marclou`).
- Rate limit threshold on X web: ~50-80 requests in 30 min triggers a 15-30 min cooldown.
- If combining OpenCLI + CDP approaches, the total available requests is ~50-80 shared, not 50-80 each.

## Rate limit behavior

| Activity | Threshold | Cooldown |
|----------|-----------|----------|
| OpenCLI `search` calls | ~3-5 calls | ~15-30 min |
| OpenCLI `tweets` calls | ~5-10 calls | ~15-30 min |
| CDP scroll actions | ~50-80 scrolls in 30 min | ~15-30 min |
| Combined (OpenCLI + CDP) | Shared IP bucket | Shared cooldown |

**Rate limit indicators (check DOM body text):** "rate limit", "retry", "too many requests", "try again later", "something went wrong", "please wait", "blocked", "temporarily".

## Getting the full archive

The browser bridge (OpenCLI) cannot paginate beyond X's ~200-500 cap. No way to get full history (>33K tweets) through OpenCLI alone.

| Method | Max tweets | Reliable? | Notes |
|--------|------------|-----------|-------|
| OpenCLI `tweets` | ~200 | Yes | Same 200 every time |
| OpenCLI `search` | ~500 | Yes | Same ~500 every time |
| CDP scroll harvest | Unlimited (slow) | Yes, with rate limiting | 8s per scroll, ~1K tweets per hour |
| X API v2 (bearer token) | 3,200/user | Yes | 100 req/15min, needs OAuth |

**For CDP scroll harvest:** 8s base delay, rate-limit detection, adaptive backoff, save every 60s. 33,400 tweets at ~20/scroll = ~1,670 scrolls x 8s = ~3.7 hours estimated.

## Strategy relevance

- `[cookie]` commands (tweets, profile, trending) work on any normally-launched Chrome — no CDP needed. Extract cookies from encrypted SQLite store.
- `[intercept]` commands (search) need CDP to intercept XHR/fetch. Timeout without CDP.
- OpenCLI + CDP share the same IP-level rate limit bucket. Running both simultaneously accelerates rate limiting.
