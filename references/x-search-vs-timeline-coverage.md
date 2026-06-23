# X Search vs Profile Timeline — Observed Coverage

Empirical data from @marclou collection (33,400 lifetime tweets), May 2026.

## The two approaches

| Approach | URL | What it hits | Coverage observed |
|----------|-----|-------------|-------------------|
| **Profile scroll** | `https://x.com/<user>` | X's UserTweets timeline (lazy-load) | ~14 months back (Mar 2025 → Apr 2026) |
| **Search results** | `https://x.com/search?q=from%3A<user>%20since%3A...%20until%3A...&f=live` | X's SearchTimeline GraphQL endpoint | ~3 months additional (Oct → Dec 2024) |

## Key findings

### 1. Zero overlap between approaches

When both datasets were merged by tweet ID:

```
Profile: 656 tweets (Mar 2025 → Apr 2026)
Search:   968 tweets (Oct 27 → Dec 29, 2024)
Merged:   1,624 tweets — 0 duplicates
```

The two approaches cover **completely non-overlapping time windows**. The profile view won't serve anything before ~Mar 2025; search won't serve anything after ~Dec 2024. They are complementary, not alternative.

### 2. Profile hits a hard stop, not a gradual taper

The profile scraper collected 1-5 new tweets per scroll for ~350 scrolls, then stopped at **20 consecutive scrolls with zero new tweets** — not because it ran out of scroll budget, but because X stopped serving older articles in the timeline DOM. The scroll position kept increasing (pixels) but no new `article[data-testid="tweet"]` elements appeared.

Stop condition: `no_new_count >= 20` consecutive empty scrolls.

### 3. Search is date-bounded by the query parameters

The search for `from:marclou since:2022-01-01 until:2024-12-31` returned tweets only from Oct–Dec 2024 — the query spanned 3 years but X only served ~3 months. Narrower date ranges (month-by-month) don't extend the reach; X's search index has its own retention cap independent of the query window.

### 4. Login state doesn't limit results as much as expected

The search ran while not logged in (`SideNav_AccountSwitcher_Button` absent) and still returned 968 tweets. The profile scroll ran while logged in (`HAS_ACCOUNT=True`). Login helps the profile view but search works well enough without it — though results may differ with login.

## Strategy recommendation

For full historical collection of an X account:

1. **Run search first** — covers the oldest reachable period (~3 months deeper)
2. **Then run profile scroll** — covers the recent ~14 months
3. **Merge by tweet ID** — zero overlap expected, simple union
4. **You'll still miss 2022–early 2024** unless using X API v2 with cursor pagination (up to 3,200 tweets)

### Quick script for merging

```python
import json, sys

profile_path = "marclou_tweets_final.json"
search_path = "marclou_search_final.json"
out_path = "marclou_all_merged.json"

with open(profile_path, encoding='utf-8') as f:
    profile = json.load(f)
with open(search_path, encoding='utf-8') as f:
    search = json.load(f)

merged = {}
for t in profile:
    merged[t['id']] = t
for t in search:
    merged[t['id']] = t

tweets = sorted(merged.values(), key=lambda t: t.get('datetime', ''))
print(f"Merged: {len(tweets)} unique ({len(profile)} + {len(search)} - {len(profile)+len(search)-len(tweets)} overlap)")

with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(tweets, f, indent=2, ensure_ascii=False)
```

## What this means for the 33,400 tweet claim

@marclou has 33,400 lifetime tweets according to `opencli twitter profile`. Our combined collection (1,624) is ~5% of the total. The rest (2022–Oct 2024, May–present 2026) requires either:
- X API v2 with paginated timeline endpoint
- Multiple search queries with different date ranges and different accounts overlapping
- Direct access to the user's X archive export
