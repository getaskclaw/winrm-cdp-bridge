# Chrome CDP Live Session Notes

Use this when controlling the user's already-running, logged-in Chrome session — especially on Windows VPS / RDP sessions.

## Correct modern path: Chrome 144+

For current Chrome, do **not** kill/relaunch Chrome just to enable CDP.

Instead:

1. In the user's existing Chrome window, open:
   ```text
   chrome://inspect/#remote-debugging
   ```
2. Toggle **Remote debugging** on.
3. Accept the per-tab **Allow debugging** prompt if Chrome shows one.
4. Attach to the live browser session via CDP / DevToolsActivePort.

Reference:
- https://github.com/pasky/chrome-cdp-skill
- https://chromedevtools.github.io/devtools-protocol/

## What not to do

Do **not** do this unless the user explicitly approves an isolated automation profile:

- force-close Chrome
- copy the user's real Chrome profile
- launch Chrome with `--remote-debugging-port` against the copied/default profile
- create `C:\Temp\ChromeCDPProfile` or similar session-data copies

That is disruptive and may confuse logged-in sessions.

## Why the old path is dangerous / outdated

Older CDP workflows used:

```text
--remote-debugging-port=9222
```

But since Chrome 136, Chrome does not respect that flag for the default user-data directory. It requires a non-standard `--user-data-dir`, because malware abused the flag to steal cookies.

So the flag-based workaround becomes:

```text
--remote-debugging-port=9222 --user-data-dir=C:\Temp\some-profile
```

That is only appropriate for isolated/headless automation — **not** for the user's live logged-in browser.

## Safe rule

If the task needs the user's logged-in Chrome state:

> Use `chrome://inspect/#remote-debugging`, not profile copying.

If a separate automation browser is acceptable:

> Use a fresh throwaway `--user-data-dir`, never a copied real profile unless the user explicitly asked for that risk.

## Incident note

During the NousResearch/X scraping task, Chrome was force-closed and a copied profile was launched with CDP. That was the wrong approach. The copied profile was deleted afterward, but the correct future workflow is the live Chrome toggle above.
