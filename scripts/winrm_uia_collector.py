#!/usr/bin/env python3
"""

⚠️  WARNING: This script uses UI Automation with SendKeys/Clipboard.
This can interfere with the user's active desktop — keystrokes may go
to the wrong window, clipboard content will be overwritten.

Prefer CDP WebSocket approach (scripts/cdp-ws-*.py) which operates
in the background without disrupting the user.

If UIA is the only option:
- Validate the target window handle before every input.
- Restore clipboard content after the operation.
- Never assume window focus is stable.
"""

"""
Template runner for x-timeline.

Fill CONFIG, then run from Hermes/Linux. Writes a PowerShell UI Automation collector
into the active Windows desktop session via WinRM without killing Chrome or copying profiles.
"""
from pathlib import Path
import base64
import re
import sys
import winrm

CONFIG = {
    "credential_file": "./2604/26429",  # env-style: host=..., user=..., pass=...
    "target_url": "https://x.com/NousResearch",
    "target_count": 1000,
    "output_stem": "x_profile_timeline",
    "task_name": "KestrelXProfileCollector",
    "remote_dir": r"C:\Temp\x_profile_collect",
}


def read_creds(path: str) -> dict:
    data = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
        elif ":" in line:
            k, v = line.split(":", 1)
        else:
            continue
        data[k.strip()] = v.strip()
    return data


def ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def build_powershell(cfg: dict) -> str:
    target_url = cfg["target_url"]
    target_count = int(cfg["target_count"])
    remote_dir = cfg["remote_dir"]
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", cfg.get("output_stem") or "x_profile_timeline")
    return rf'''
$ErrorActionPreference='Continue'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public class KWin {{ [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd); }}
"@
$TargetUrl={ps_quote(target_url)}
$TargetCount={target_count}
$OutDir={ps_quote(remote_dir)}
$Stem={ps_quote(stem)}
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
$RawPath=Join-Path $OutDir ($Stem + '.raw.tsv')
$JsonPath=Join-Path $OutDir ($Stem + '.jsonl')
$MdPath=Join-Path $OutDir ($Stem + '.md')
$LogPath=Join-Path $OutDir ($Stem + '.log')
Remove-Item $RawPath,$JsonPath,$MdPath,$LogPath -ErrorAction SilentlyContinue
function Log($s){{ Add-Content $LogPath ('{{0:u}} {{1}}' -f (Get-Date),$s) -Encoding UTF8 }}
function Clean($s){{ return (($s -replace "`r?`n",' ') -replace '\s+',' ').Trim() }}
function Get-ChromeWindow(){{
  $root=[System.Windows.Automation.AutomationElement]::RootElement
  $cond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ClassNameProperty,'Chrome_WidgetWin_1')
  $wins=$root.FindAll([System.Windows.Automation.TreeScope]::Children,$cond)
  for($i=0;$i -lt $wins.Count;$i++){{
    $n=$wins.Item($i).Current.Name
    if($n -like '*X - Google Chrome*' -or $n -like '*Twitter*' -or $n -like '*Google Chrome*'){{ return $wins.Item($i) }}
  }}
  return $null
}}
function Focus-Chrome(){{
  $w=Get-ChromeWindow
  if(!$w){{ return $false }}
  [KWin]::SetForegroundWindow([IntPtr]$w.Current.NativeWindowHandle) | Out-Null
  $w.SetFocus(); Start-Sleep -Milliseconds 400
  return $true
}}
function Dump-Groups-And-Links(){{
  $w=Get-ChromeWindow
  if(!$w){{ return @() }}
  $walker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
  $q=New-Object System.Collections.Queue; $q.Enqueue($w); $count=0; $arr=@()
  while($q.Count -gt 0 -and $count -lt 14000){{
    $e=$q.Dequeue(); $count++
    $n=Clean $e.Current.Name
    $t=$e.Current.ControlType.ProgrammaticName
    $r=$e.Current.BoundingRectangle
    if($n -and $n.Length -gt 70 -and $n -match '@[A-Za-z0-9_]+' -and $n -match '(repl|repost|like|view|bookmark|likes|views)'){{
      $kind='post'
      if($n -match 'Replying to|replied|Show replies|^Reply'){{ $kind='comment' }}
      $arr += [pscustomobject]@{{Kind=$kind; Text=$n; Link=''; X=[int]$r.X; Y=[int]$r.Y; W=[int]$r.Width; H=[int]$r.Height}}
    }}
    if($n -match 'x\.com/.+/status/\d+' -or $n -match '/status/\d+'){{
      $arr += [pscustomobject]@{{Kind='link'; Text=$n; Link=$n; X=[int]$r.X; Y=[int]$r.Y; W=[int]$r.Width; H=[int]$r.Height}}
    }}
    $c=$walker.GetFirstChild($e); while($c -ne $null){{ $q.Enqueue($c); $c=$walker.GetNextSibling($c) }}
  }}
  return $arr
}}
function Key($s){{
  $k=($s -replace '\d+ replies.*$','' -replace '\d+ reposts.*$','' -replace '\d+ likes.*$','')
  if($k.Length -gt 320){{ $k=$k.Substring(0,320) }}
  return $k
}}
function Add-Item($kind,$text,$link,$parent){{
  $k=Key $text
  if($script:Seen.ContainsKey($k)){{ return $false }}
  $script:Seen[$k]=$true
  $obj=[ordered]@{{kind=$kind; visible_time=''; author=''; handle=''; link=$link; parent_link=$parent; text=$text}}
  ($obj | ConvertTo-Json -Compress) | Add-Content $JsonPath -Encoding UTF8
  Add-Content $RawPath (($kind + "`t" + $link + "`t" + $parent + "`t" + $text)) -Encoding UTF8
  [void]$script:Items.Add([pscustomobject]$obj)
  return $true
}}
Log "start target_url=$TargetUrl target_count=$TargetCount"
Focus-Chrome | Out-Null
[System.Windows.Forms.SendKeys]::SendWait('^l'); Start-Sleep -Milliseconds 200
[System.Windows.Forms.Clipboard]::SetText($TargetUrl)
[System.Windows.Forms.SendKeys]::SendWait('^v'); [System.Windows.Forms.SendKeys]::SendWait('{{ENTER}}')
Start-Sleep -Seconds 5
$script:Seen=@{{}}
$script:Items=New-Object System.Collections.ArrayList
for($i=0;$i -lt ([Math]::Max(250,[int]($TargetCount*0.75))) -and $script:Items.Count -lt $TargetCount;$i++){{
  Focus-Chrome | Out-Null
  $visible=Dump-Groups-And-Links
  $new=0
  foreach($v in $visible){{
    if($v.Kind -eq 'link'){{ continue }}
    if($v.Text -match '^Pinned '){{ continue }}
    if(Add-Item $v.Kind $v.Text $v.Link ''){{ $new++ }}
    if($script:Items.Count -ge $TargetCount){{ break }}
  }}
  Log "scroll=$i total=$($script:Items.Count) visible=$($visible.Count) new=$new"
  [System.Windows.Forms.SendKeys]::SendWait('{{PGDN}}')
  Start-Sleep -Milliseconds 1200
}}
$md=@()
$md += '# X profile timeline collection'
$md += ''
$md += ('Collected: {{0:u}}' -f (Get-Date))
$md += "Source: $TargetUrl"
$md += 'Method: logged-in live Windows Chrome session; no Chrome kill, no profile copy.'
$md += "Total items: $($script:Items.Count)"
$md += ''
$idx=1
foreach($it in $script:Items){{
  $md += "## $idx. $($it.kind)"
  if($it.link){{ $md += "Link: $($it.link)" }}
  if($it.parent_link){{ $md += "Parent: $($it.parent_link)" }}
  $md += ''
  $md += $it.text
  $md += ''
  $idx++
}}
$md -join "`r`n" | Set-Content $MdPath -Encoding UTF8
Log "done total=$($script:Items.Count) md=$MdPath raw=$RawPath json=$JsonPath"
'''


def main() -> int:
    cfg = CONFIG
    creds = read_creds(cfg["credential_file"])
    session = winrm.Session(
        f"http://{creds['host']}:5985/wsman",
        auth=(creds["user"], creds["pass"]),
        transport="ntlm",
        server_cert_validation="ignore",
    )
    ps = build_powershell(cfg)
    b64 = base64.b64encode(ps.encode("utf-8")).decode("ascii")
    remote_b64 = r"C:\Temp\x_profile_collector.b64"
    remote_ps1 = r"C:\Temp\x_profile_collector.ps1"
    session.run_ps(f"Remove-Item '{remote_b64}','{remote_ps1}' -ErrorAction SilentlyContinue")
    for i in range(0, len(b64), 750):
        session.run_ps(f"Add-Content -Path '{remote_b64}' -Value '{b64[i:i+750]}'")
    session.run_ps(f"$b=(Get-Content '{remote_b64}' -Raw) -replace '\\s',''; [IO.File]::WriteAllBytes('{remote_ps1}', [Convert]::FromBase64String($b))")
    task = cfg["task_name"]
    run = rf'''
$tn='{task}'
Unregister-ScheduledTask -TaskName $tn -Confirm:$false -ErrorAction SilentlyContinue
$action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File "{remote_ps1}"'
$trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5)
$principal=New-ScheduledTaskPrincipal -UserId 'Administrator' -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $tn -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName $tn
Start-Sleep -Seconds 3
Get-ScheduledTask -TaskName $tn | Select-Object TaskName,State | Format-List
'''
    r = session.run_ps(run)
    sys.stdout.write(r.std_out.decode(errors="replace"))
    sys.stderr.write(r.std_err.decode(errors="replace"))
    return 0 if r.status_code == 0 else r.status_code


if __name__ == "__main__":
    raise SystemExit(main())
