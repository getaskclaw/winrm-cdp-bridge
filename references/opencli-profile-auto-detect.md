# OpenCLI Profile Auto-Detection

When OpenCLI integrations (especially X/Twitter `[intercept]` commands) stop returning results, the most likely cause is a stale browser bridge profile ID.

## Problem

OpenCLI Browser Bridge assigns a hash ID (e.g. `vwncsxtf`, `stable_profile`) to each connected Chrome instance. If Chrome restarts, the bridge reconnects and generates a **new profile ID**. Scripts that hardcode the old ID silently fail — commands hang until timeout with no error because the daemon is alive but can't find the browser session to intercept requests from.

## Profile Ordering — Not All Profiles Have X Cookies

When multiple Chromes are running (e.g. stable + Canary), `opencli profile list` returns multiple profiles. **The "default" tag does not guarantee X login cookies** — it only marks the last-used profile. A Canary profile may become "default" after being launched, but it won't have X cookies unless someone logged into X in that browser.

**Strategy to find the cookie-bearing profile:**

1. Collect all connected profile IDs
2. Try each with a `[cookie]` command like `opencli --profile <id> twitter profile <known-user>`
3. The first one that returns non-empty user data has X cookies
4. Cache the working ID and re-detect when collection returns 0 for all profiles

Example priority order: known-working profile (from prior session) → "default"-tagged profile → first connected → fallback hardcoded ID.

## Solution: Detect at Runtime

Instead of a hardcoded `X_OC_PROFILE = "vwncsxtf"`, probe the daemon:

```python
import subprocess, json

def detect_opencli_profile() -> str | None:
    """Return the first connected profile name, or None."""
    r = subprocess.run(
        ["opencli", "profile", "list", "--json"],
        capture_output=True, text=True, timeout=15
    )
    profiles = json.loads(r.stdout)
    connected = [p for p in profiles if p.get("connected")]
    return connected[0]["name"] if connected else None
```

**For remote Windows (WinRM):** the profile list command runs in a fresh PowerShell session each time, so parse JSON from stdout:

```python
def detect_remote_profile(session) -> str | None:
    r = session.run_ps("opencli profile list --json 2>$null")
    profiles = json.loads(r.std_out.decode("utf-8", errors="replace"))
    connected = [p for p in profiles if p.get("connected")]
    return connected[0]["name"] if connected else None
```

## Usage in Cron Scripts

In a `no_agent=true` wrapper script, wrap uv/python call to run detection before each collection cycle. The detection runs in ~2-3 seconds and costs nothing if the profile hasn't changed.

## Strategy-Aware Fallback

- Only `[intercept]` and `[ui]` strategy commands need an active CDP connection / profile match. `[cookie]` strategy commands (`twitter tweets`, `twitter profile`) work regardless of CDP state but DO need a profile with X login cookies.
- If no profile returns data with a `[cookie]` test, the X session has expired. Re-login in Chrome is needed.
- If profiles are connected but `[intercept]` commands return 0-length output (silently, no error), CDP is unavailable. Fall back to `[cookie]` commands like `twitter tweets` instead of `twitter search`.
- Detection handles multi-browser setups: if both stable Chrome and Chrome Canary are running with bridges, prefer the profile that passes a `[cookie]` smoke test, not the first connected or "default" marker.
