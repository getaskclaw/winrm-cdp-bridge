# Cookie-only profile transfer

**⚠️ WARNING: This document describes a dangerous pattern. Do not follow it in production.**

Transferring Chrome cookies between profiles or machines creates session hijacking risk. Instead, use a **fresh profile and have the user log in manually** — this preserves DPAPI encryption and leaves no residual credential material in accessible locations.

## Safe alternative (preferred)

1. Launch Chrome with a fresh temp profile and `--remote-debugging-port`:
   ```powershell
   & "C:\Program Files\Google\Chrome\Application\chrome.exe" `
     --remote-debugging-address=127.0.0.1 `
     --remote-debugging-port=9250 `
     --user-data-dir="C:\Temp\chrome_scrape_$(Get-Random)" `
     --no-first-run --no-default-browser-check `
     --new-window https://x.com/login
   ```
2. A Chrome window appears on the user's desktop. **Ask the user to log into X manually.**
3. Run the WebSocket scraper against the live session.
4. **Do not kill Chrome** — the session cookies live in the process memory and the encrypted cookie store. Killing Chrome destroys the DPAPI session key.
5. When the scrape completes, close Chrome normally. Delete the temp profile directory.

## Why this is safer

| Approach | Risk |
|---|---|
| Fresh profile + user log in | ✅ No credential material written to accessible paths. Cookie encryption key is process-bound. |
| Clone full profile | ❌ DPAPI encryption path changes — old cookies can't be decrypted. Can't relaunch CDP after Chrome kill. |
| Copy Cookies DB to Public | ❌ **Session hijacking.** Any user/service on the machine can read cookies. Chrome key may also be accessible. |
| Copy Cookies + Local State | ❌ Machine/user-bound DPAPI may not re-decrypt on a different machine or user account. |

## If you absolutely must transfer (not recommended)

- **Never** write to `C:\Users\Public\` — use a private ACL'd directory under the user's `%TEMP%` or `%APPDATA%`.
- The destination directory must not be readable by other users or services.
- Destroy the transferred files immediately after use.
- This still won't survive a Chrome restart — so a fresh profile + manual login is always better.

## The hard problem

Chrome's DPAPI encryption key is derived from the profile directory path + Windows user SID + machine secret. When you clone a profile to a new path, the old cookies exist in the SQLite file but cannot be decrypted — Chrome generates a new key at the new path. **No file-copy approach works for Chrome 148+.** Use fresh profile + user login.
