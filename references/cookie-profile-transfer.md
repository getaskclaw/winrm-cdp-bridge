# Cookie-Only Profile Transfer for Chrome Login

## When to use this

You need a Chrome instance with an existing login session (e.g. X.com) but:
- You can't attach CDP to the running Chrome (OpenCLI bridge, no `--remote-debugging-port`)
- You can't ask the user to log in again (they're busy, or it's a headless/server setup)
- A full profile clone (robocopy of everything) fails on relaunch (see `chrome-148-cdp-profile-clone.md`)
- The existing Chrome has the session and you want to duplicate it

## The approach

Chrome stores encrypted cookies in **two files** that together form the login session:

| File | Path (Chrome 148+) | Purpose |
|------|-------------------|---------|
| `Local State` | `User Data/Local State` | Contains the DPAPI-encrypted AES key for cookie decryption |
| `Network/Cookies` | `User Data/Default/Network/Cookies` | The actual cookie database (SQLite) |

Copying **both files** from a logged-in Chrome profile to a new profile directory allows the new Chrome to decrypt and use the existing session cookies — because DPAPI works on the same Windows machine and same user account.

**Why it works:** Chrome encrypts the cookie AES key using Windows DPAPI (Data Protection API), which is bound to the machine + user identity, NOT the profile directory path. As long as the same Windows user runs both Chrome instances on the same machine, the DPAPI decryption succeeds regardless of `--user-data-dir`.

**Why earlier attempts failed:** 
1. Chrome 148 moved cookies from `User Data/Default/Cookies` to `User Data/Default/Network/Cookies` — copying the old path gets nothing
2. Not copying `Local State` means the new Chrome has no encryption key
3. The full-clone approach (robocopy of everything) fails on relaunch because Chrome detects profile corruption from the cloned Crashpad/BrowserMetrics/temp files, not because of cookie issues

## Procedure (PowerShell via WinRM)

```powershell
# 1. Create a fresh profile root
New-Item -ItemType Directory -Force -Path "C:\Users\Public\chrome-transfer\User Data\Default"

# 2. Copy Local State (contains the DPAPI-encrypted AES key)
Copy-Item "C:\Users\Administrator\AppData\Local\Google\Chrome\User Data\Local State" `
  "C:\Users\Public\chrome-transfer\User Data\Local State" -Force

# 3. Copy the cookie database (Chrome 148+ stores in Network subdirectory)
if (Test-Path "C:\Users\Administrator\AppData\Local\Google\Chrome\User Data\Default\Network\Cookies") {
    New-Item -ItemType Directory -Force -Path "C:\Users\Public\chrome-transfer\User Data\Default\Network"
    Copy-Item "C:\Users\Administrator\AppData\Local\Google\Chrome\User Data\Default\Network\Cookies" `
      "C:\Users\Public\chrome-transfer\User Data\Default\Network\Cookies" -Force
} else {
    # Legacy path (pre-Chrome 148)
    Copy-Item "C:\Users\Administrator\AppData\Local\Google\Chrome\User Data\Default\Cookies" `
      "C:\Users\Public\chrome-transfer\User Data\Default\Cookies" -Force
}

# 4. Copy Login Data (optional — some sites store auth tokens here)
Copy-Item "C:\Users\Administrator\AppData\Local\Google\Chrome\User Data\Default\Login Data" `
  "C:\Users\Public\chrome-transfer\User Data\Default\Login Data" -Force -ErrorAction SilentlyContinue
```

## Launching the cookie-transferred Chrome

```powershell
$Chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$Args = '--remote-debugging-address=127.0.0.1 --remote-debugging-port=9250 --user-data-dir="C:\Users\Public\chrome-transfer\User Data" --no-first-run --no-default-browser-check --new-window about:blank'
Start-Process -FilePath $Chrome -ArgumentList $Args
```

**⚠️ Chrome 148 process merging:** If a Chrome instance is ALREADY running with the same binary, launching a new one with `Start-Process` may route the request to the existing process instead of creating a new one. This happens because Chrome's desktop launch protocol on Windows sends the command-line args to the existing process.

**Workarounds:**
- **Copy to a genuinely different `--user-data-dir`** — a directory Chrome has never used before. The mutex key is derived from the user-data-dir path, so a truly unique path should force a new process. If it still merges, the existing Chrome is intercepting ALL chrome.exe launches regardless (Chrome 148 behavior). In that case:
  - **Stop the existing Chrome's desktop-launch handler** — kill the existing Chrome process (if safe)
  - **Use Invoke-Expression** instead of Start-Process (sometimes helps)
  - **Use Chrome Canary** — different binary, no process merging at all

## Verification

After launching, verify the session transferred:

```powershell
# Via .NET HttpClient (works where curl returns empty on Chrome 148)
Add-Type -AssemblyName System.Net.Http
$client = New-Object System.Net.Http.HttpClient
$resp = $client.GetAsync("http://127.0.0.1:9250/json/list").Result
$content = $resp.Content.ReadAsStringAsync().Result
# Check for the X page to verify login-state
```

For X.com, check if `[data-testid="SideNav_AccountSwitcher_Button"]` exists in the DOM via CDP Runtime.evaluate.

## Limitations

- **Does NOT survive Chrome restart.** If you kill the transferred-profile Chrome and relaunch, Chrome re-derives the encryption key and can't decrypt old cookies again. This is the same limitation as full-clone profiles.
- **Works for same-machine-only.** DPAPI keys don't transfer between machines.
- **Requires the same Windows user** (the user whose DPAPI encrypted the Local State key).
- **Chrome 148+ only tested.** Older Chrome versions may use different cookie file paths.
