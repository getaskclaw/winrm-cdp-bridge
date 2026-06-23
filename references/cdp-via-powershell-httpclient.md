# CDP Operations via PowerShell .NET HttpClient

For intermediate CDP operations (navigate, extract page info, count tweets, check login) you can use PowerShell's `System.Net.Http.StringContent` to POST JSON CDP commands to `/devtools/page/<id>`. This avoids needing a WebSocket client running on Windows.

## Pattern: Navigate page tab to a URL

```powershell
Add-Type -AssemblyName System.Net.Http

# Discover page targets (GET /json list still works in Chrome 148+)
$c = New-Object System.Net.Http.HttpClient
$c.Timeout = [TimeSpan]::FromSeconds(5)
$resp = $c.GetAsync("http://127.0.0.1:9250/json/list").Result
$pages = $resp.Content.ReadAsStringAsync().Result
$parsed = $pages | ConvertFrom-Json
$page = $parsed | Where-Object { $_.type -eq "page" } | Select-Object -First 1

# Navigate via CDP POST (Page.navigate)
$navBody = '{"id":1,"method":"Page.navigate","params":{"url":"https://x.com/marclou"}}'
$content = New-Object System.Net.Http.StringContent($navBody, [System.Text.Encoding]::UTF8, "application/json")
$resp2 = $c.PostAsync("http://127.0.0.1:9250/devtools/page/$($page.id)", $content).Result
Write-Output $resp2.Content.ReadAsStringAsync().Result
```

## Pattern: Evaluate JavaScript

```powershell
# Extract page title
$evalBody = '{"id":2,"method":"Runtime.evaluate","params":{"expression":"document.title","returnByValue":true}}'
$content = New-Object System.Net.Http.StringContent($evalBody, [System.Text.Encoding]::UTF8, "application/json")
$resp = $c.PostAsync("http://127.0.0.1:9250/devtools/page/$($page.id)", $content).Result
$result = $resp.Content.ReadAsStringAsync().Result
# Parse JSON: look for result.result.value

# Count tweet articles
$countBody = '{"id":3,"method":"Runtime.evaluate","params":{"expression":"document.querySelectorAll(''[data-testid=\"tweet\"]'').length","returnByValue":true}}'
$content = New-Object System.Net.Http.StringContent($countBody, [System.Text.Encoding]::UTF8, "application/json")
$resp = $c.PostAsync("http://127.0.0.1:9250/devtools/page/$($page.id)", $content).Result

# Scroll down
$scrollBody = '{"id":4,"method":"Runtime.evaluate","params":{"expression":"window.scrollBy(0, window.innerHeight * 1.5)","returnByValue":true}}'
$content = New-Object System.Net.Http.StringContent($scrollBody, [System.Text.Encoding]::UTF8, "application/json")
$resp = $c.PostAsync("http://127.0.0.1:9250/devtools/page/$($page.id)", $content).Result
```

## Pattern: Check login state (multi-selector)

```powershell
$loginBody = @'
{"id":5,"method":"Runtime.evaluate","params":{"expression":"(() => { const selectors = [\"[data-testid='SideNav_AccountSwitcher_Button']\",\"[data-testid='SideNav_NewTweet_Button']\",\"[data-testid='AppTabBar_Profile_Tab']\"]; return selectors.some(s => !!document.querySelector(s)); })()","returnByValue":true}}
'@
$content = New-Object System.Net.Http.StringContent($loginBody, [System.Text.Encoding]::UTF8, "application/json")
$resp = $c.PostAsync("http://127.0.0.1:9250/devtools/page/$($page.id)", $content).Result
$result = $resp.Content.ReadAsStringAsync().Result
# value: true = logged in, false = logged out
```

## Chrome 148+ caveat

HTTP POST to `/devtools/page/<id>` may return HTTP 200 with `Content-Length: 0` (empty body). This is **inconsistent** — sometimes it works (returns full CDP response JSON), sometimes Chrome silently eats the body. Behavior varies per Chrome build and session.

**When it works:** use for quick operations (navigate, verify URL, check login, count elements).
**When it doesn't:** fall back to WebSocket (Python `websockets` lib on the Windows host).

The GET endpoints (`/json/version`, `/json/list`) are more reliable than POST. If POST returns empty, the command still executed on Chrome's side — you just don't get a response. Use WebSocket when you need the response data.

## Common use cases via WinRM

From Python on 26423, calling WinRM to run PowerShell that does CDP:

```python
import winrm
s = winrm.Session('http://<host>:5985/wsman', auth=(user, pass), transport='ntlm', server_cert_validation='ignore')

# Batch: Navigate + check login + count tweets
ps = '''
Add-Type -AssemblyName System.Net.Http
$c = New-Object System.Net.Http.HttpClient
$c.Timeout = [TimeSpan]::FromSeconds(5)
$resp = $c.GetAsync("http://127.0.0.1:9250/json/list").Result
$pages = $resp.Content.ReadAsStringAsync().Result
$parsed = $pages | ConvertFrom-Json
$page = $parsed | Where-Object { $_.type -eq "page" } | Select-Object -First 1
Write-Output "ID: $($page.id)"
'''
r = s.run_ps(ps)
print(r.std_out.decode('utf-8', errors='replace'))
```

Then use the page ID in subsequent CDP POST commands.
