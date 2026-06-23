# OpenCLI tweet collection: `tweets` vs `search` vs `profile` patterns

Collected during marclou full-history collection (May 2026).

## Endpoint behavior

| Command | Strategy | Cap | Date coverage | `--product` flag |
|---------|----------|-----|---------------|------------------|
| `tweets <user>` | `[cookie]` | ~200 tweets | ~14 months back (e.g. Mar 2025 -> May 2026) | N/A |
| `search "from:<user>"` | `[intercept]` | 500 per call | ~6 weeks back (e.g. Apr 3 -> May 13) | `--product live` returns results for `from:` queries; `--product top` returns empty |
| `profile <user>` | `[cookie]` | N/A — metadata only | N/A | N/A |

Returns: bio, follower count, following count, tweet count (lifetime), location, verified status, URL.

**Key finding:** `tweets` gives widest date range but low density (~1 tweet/week over 14 months = ~200). `search --product live "from:<user>"` gives higher density but only ~6 weeks back (~500 tweets). Merge them and deduplicate by tweet ID.

## Practical max from OpenCLI

Collected from @marclou (33,400 lifetime tweets):

| Source | Raw count | Unique after dedup | Date range |
|--------|-----------|-------------------|------------|
| `tweets marclou --limit 200` | 200 | 200 | Mar 2025 -> May 2026 |
| `search 'from:marclou' --product live --limit 500` | 500 | ~220 unique | Apr 3 -> May 13 |
| **Merged** | 700 | **353** (326 orig + 27 RTs) | Apr 3 -> May 13 |

## Date filtering limitation

`since:`/`until:` operators in the `search` query string do NOT filter server-side. Monthly-windowed calls all return the same 500 most-recent tweets. Dedup catches the duplicates. The same applies to x-timeline-sqlite's `--date-start`/`--date-end` flags — they filter locally after fetch.

## 429 handling

Error signature:
```
HTTP 429: UserTweets fetch failed — queryId may have expired
```

Recovery: wait 5-15 min, or `opencli profile use <profile>` (resets connection but not rate limit), or restart Chrome (wipes session — re-login needed).

## Better approaches for full history

Beyond the ~200-400 OpenCLI ceiling:

1. **X API v2** cursor pagination — up to 3,200 tweets per user, 100 req/15min. Needs bearer token.
2. **CDP scroll harvest** — open x.com/user in Chrome, scroll via CDP WebSocket, extract DOM. Chrome 148+ requires WebSocket (HTTP POST returns empty body). Requires separate Chrome instance (Canary, or kill existing + re-login).
3. **`opencli twitter download <user>`** — media download only, not text.
4. **Accept the ceiling** if 14 months of coverage is sufficient.
