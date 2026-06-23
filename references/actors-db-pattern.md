# Actors DB — Person-Level X Timeline Tracking

A standalone SQLite system for tracking specific people (actors) and their X posts over time. Decoupled from the x-timeline-sqlite pipeline — lives on 41030, not 26423.

## When to use

- User wants to **track specific people** over time (not keyword-based signal discovery)
- Need recurring collection for a **known set of accounts**
- Want a **shareable dataset** other agents can consume (over HTTP or Tailscale)
- Need structured metadata about each tracked person (tags, notes, profile info)

## Architecture

```
/root/actors/
├── actors.py       # CLI tool
├── actors.db       # SQLite database
├── schema.sql      # Table definitions
└── collect_actors.sh  # Cron wrapper script
```

### Schema

- **actors** — person registry: handle, name, X user ID, tags (JSON), notes, status (active/paused/archived)
- **items** — collected tweets: x_status_id, item_type (post/reply/retweet/quote), text, created_at, engagement stats, raw_json
- **collection_runs** — collection history: date window, items_before/after/new, status, error_message
- **actor_notes** — human notes per actor: insights, observations, profile facts

### CLI Commands

```
python3 actors.py add <handle>             # Add actor (--name, --tags, --notes)
python3 actors.py list                      # List all with stats
python3 actors.py info <handle>             # Detailed view + notes
python3 actors.py collect <handle>          # Incremental X collection
python3 actors.py backfill <handle>         # Full backfill
python3 actors.py export <handle>           # JSON export
python3 actors.py import <handle> --path <x_timeline.sqlite>  # Import existing data
python3 actors.py note <handle> <text>      # Add note
```

## OpenCLI/WinRM Collection

The collection hits the Windows host (26429) via WinRM using the same credential file as the signal pipeline.

### Collection strategy: `tweets` not `search`

OpenCLI has two approaches for reading X data:

| Strategy | Command | Mechanism | CDP needed? | Works with Chrome 148+? |
|----------|---------|-----------|-------------|------------------------|
| `[cookie]` | `opencli twitter tweets <handle>` | Reads X cookies from Chrome's DPAPI-encrypted store | **No** | ✅ Yes |
| `[intercept]` | `opencli twitter search "from:<handle>"` | Launches Chrome, intercepts network requests via CDP | Yes | ❌ No — HTTP CDP endpoint removed in Chrome 148+ |

**Always use `tweets` for actor collection.** It's faster (no browser launch), avoids CDP dependency and Chrome version compatibility issues, and returns cleaner JSON.

**Known `tweets` limitations:**
- Returns at most ~200 tweets per account regardless of `--limit` value — X's internal GraphQL endpoint caps it.
- **No date filtering.** Unlike `search` which supported `since:YYYY-MM-DD`, the `tweets` command doesn't accept a date parameter. Every call fetches the same ~200 most recent tweets. Don't attempt date-windowing to reach older content — you'll get the same 200 tweets 52 times.
- For historical coverage, use `opencli twitter search "from:user"` (if CDP works), X API v2 with pagination, or CDP browser scrolling (see `cdp-x-scraping.md`).

### Profile auto-detection with multiple Chrome instances

Both Chrome Stable and Chrome Canary may be running simultaneously on 26429, each creating a separate OpenCLI Browser Bridge profile. The profile with X login cookies is not always the first connected one. **Use priority-based selection:**

```python
# 1. Collect all connected profiles from `opencli profile list`
profiles = []
for line in profile_out.split("\n"):
    if "connected" in line and "\u2014" in line:
        pid = line.split()[0].strip()
        profiles.append(pid)

# 2. Identify which one is marked "default"
default_profile = None
for line in profile_out.split("\n"):
    if "default" in line and "connected" in line and "\u2014" in line:
        default_profile = line.split()[0].strip()

# 3. Build priority list: known-cookie profile > default > any
priority = []
if "stable_profile" in profiles:       # Stable Chrome — has X login
    priority.append("stable_profile")
if default_profile and default_profile not in priority:
    priority.append(default_profile)
for p in profiles:
    if p not in priority:
        priority.append(p)
profile = priority[0]
```

**Why profile `stable_profile` specifically?** This is the Stable Chrome profile on 26429 that is logged into X. Chrome Canary (`canary_profile`) may be connected but has no X cookies. The priority ensures collection always uses the correct profile.

### Stateful command execution

Each `sess.run_ps()` creates an independent PowerShell session. Profile detection as a separate call is fine (it's just querying state). For the actual collection, use the `--profile` flag instead of a separate `profile use` command:

```powershell
# CORRECT — --profile flag avoids separate profile-use command
opencli --profile stable_profile twitter tweets marclou -f json --limit 200 2>&1
```

The `--profile <id>` flag is cleaner than `profile use` + command in one PS call — no chaining needed, no state corruption risk.

### JSON output stripping

OpenCLI prepends `Default Browser Bridge profile: <name>\n` before the JSON array. Also emits noise lines from PowerShell wrapping. Strip before parsing:

```python
lines = stdout.split("\n")
clean = [l for l in lines if "#<" not in l and "Preparing modules" not in l
         and "node.exe" not in l and "Update available" not in l
         and "Extension update" not in l and "Download:" not in l]
out = "\n".join(clean).strip()
# Find JSON start — look for [, {, or null
for start in ("[", "{", "null"):
    idx = out.find(start)
    if idx >= 0:
        out = out[idx:].strip()
        break
```

### OpenCLI version management

OpenCLI is installed as a global npm package on the Windows host. Update via WinRM:

```powershell
npm install -g @jackwener/opencli@latest
```

Check current vs latest versions:
```powershell
# Installed version
npm ls -g @jackwener/opencli
# Latest available
npm view @jackwener/opencli version
```

The Windows host (26429) uses `C:\Users\winrm_user\AppData\Roaming\npm` as the global install location. Make sure `$env:Path` includes `C:\Program Files\nodejs` and the npm global bin directory when running OpenCLI via WinRM.

## Adding a New Actor

```bash
# Add
python3 actors.py add xkajon --tags "indie-hacker" --notes "description"

# Import existing data if we have it
python3 actors.py import xkajon --path /path/to/x_timeline.sqlite

# Set up recurring collection
# (copy collect_actors.sh, add line for new actor, create cron)
```

## Data Sharing for Other Agents

When other agents need the data, the simplest approach is a Python HTTP server:

```bash
cd /root/actors && python3 -m http.server 9090 --bind 100.106.39.34
```

Then from any Tailscale node:

```bash
curl -o /tmp/actors.db http://100.106.39.34:9090/actors.db
```

## Cron Setup

### Daily collection loop (all actors)

The `daily-collect.sh` script handles the full pipeline — collect all actors, metadata export, SQL dump backup, and git push:

```bash
#!/bin/bash
cd /root/actors
# 1. Collect for all active actors
python3 actors.py list 2>/dev/null | tail -n +3 | while read line; do
  handle=$(echo "$line" | awk '{print $1}' | sed 's/^@//')
  [[ -z "$handle" ]] && continue
  python3 actors.py collect "$handle" --limit 200
done
# 2. Export actor metadata
python3 -c '...write data/actors.json...'
# 3. SQL dump the DB for version history
sqlite3 actors.db .dump > data/actors-dump.sql
# 4. Commit & push to Forgejo
git add -A
git commit -m "daily collect $(date -u +'%Y-%m-%d')"
git push origin main
```

**Why SQL dump instead of binary DB in git:**
- Text diffable — `git log -p data/actors-dump.sql` shows exactly which tweets arrived each day
- Full recovery — `sqlite3 actors.db < data/actors-dump.sql` restores from any commit
- Git compresses SQL dumps well (335KB DB → ~100KB in git)
- The `.gitignore` excludes `actors.db` itself; `data/` is tracked

**One-time setup:**
```bash
git remote add origin ssh://forgejo@26423.tail744929.ts.net:2222/ash/actors.git
```

**Cron:**
```bash
cronjob create --name daily-actors-collect --schedule "0 6 * * *" \
  --prompt "Run /root/actors/daily-collect.sh"
```

## Adding Actors in Bulk from a Following List

To add tracked actors from an X account's following list:

```python
# get_following.py — uses WinRM + OpenCLI to fetch following list
opencli twitter following <account> --limit 1000 -f json
# Returns: {"handle": "levelsio", "name": "", "description": ""}
```

Then add each:
```bash
for handle in levelsio gregisenberg nikitabier karpathy; do
  python3 actors.py add "$handle"
done
```

Run `bash daily-collect.sh` after adding to backfill all new actors immediately.

## Pitfalls

1. **`search` command requires CDP — broken with Chrome 148+.** Chrome 148+ removed the standard HTTP DevTools Protocol endpoint that `opencli twitter search` (and its `[intercept]` strategy) depends on. Always use `opencli twitter tweets <handle>` (cookie strategy) for actor collection. It reads encrypted cookies from Chrome's DPAPI store — no CDP needed, no browser launch.

2. **Multiple Chromes = wrong profile auto-detection.** With both Stable and Canary running, the naive "first connected profile" pattern picks Canary (`canary_profile`) which has no X login cookies. Use priority-based selection preferring `stable_profile` (known-cookie profile), then default-marked profile, then any. See "Profile auto-detection with multiple Chrome instances" above.

3. **`tweets` has no date filtering.** Unlike `search` which accepted `since:YYYY-MM-DD`, the `tweets` command returns only the ~200 most recent tweets regardless of any date parameters you pass. Don't run 52 weekly windows expecting different data — you'll get the same results 52 times.

4. **`tweets` is capped at ~200 tweets.** X's internal UserTweets GraphQL endpoint caps the response. The `--limit` flag above ~200 doesn't help. For full history, use CDP browser scrolling, X API v2 with pagination, or `opencli twitter search "from:user"` (if your Chrome version supports CDP).

5. **OpenCLI npm updates break old patterns.** The installed version on 26429 (Windows host) gets out of sync with the latest npm release. Check with `npm view @jackwener/opencli version` and update with `npm install -g @jackwener/opencli@latest` via WinRM. After updates, re-verify the command syntax hasn't changed.

6. **Stateful commands across WinRM calls.** Each `sess.run_ps()` creates an independent PowerShell session. Use `--profile <id>` flag instead of `profile use` as a separate command — the flag works on any OpenCLI command and avoids state corruption.

7. **`$ErrorActionPreference='Stop'` causes silent failures.** Avoid it in PS scripts sent via WinRM.

8. **`node.exe` errors are noise.** OpenCLI's PowerShell wrapper sometimes emits `node.exe :` errors on stderr that don't affect results. Filter them out.

9. **"Default Browser Bridge profile:" prefix.** Strip before JSON parsing by finding the first `[` or `{` in the output.

10. **Cron PYTHONPATH.** The cron environment may not include `/usr/local/lib/python3.11/dist-packages`. Set it explicitly in the script.

11. **OpenCLI PID changes after Chrome update.** The profile ID (`stable_profile`, `canary_profile`) is a hash tied to the Chrome installation, not the user. If Chrome auto-updates or gets reinstalled, the PID may change. Re-detect with `opencli profile list` if collection stops working after a Chrome update.
