from pathlib import Path
import base64, winrm
creds={}
for line in Path('/root/2604/26429').read_text().splitlines():
    if '=' in line:
        k,v=line.split('=',1); creds[k.strip()]=v.strip()
s=winrm.Session('http://' + creds['host'] + ':5985/wsman', auth=(creds['user'],creds['pass']), transport='ntlm', server_cert_validation='ignore')
ps=r'''
$Out='C:\Temp\x_profile_collect\enable_cdp_no_clipboard.txt'
Remove-Item $Out -ErrorAction SilentlyContinue
function O($s){ Add-Content $Out $s -Encoding UTF8 }
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public class KWin { [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd); }
"@
function Clean($s){ (($s -replace "`r?`n",' ') -replace '\s+',' ').Trim() }
function Win(){
  $root=[System.Windows.Automation.AutomationElement]::RootElement
  $cond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ClassNameProperty,'Chrome_WidgetWin_1')
  $wins=$root.FindAll([System.Windows.Automation.TreeScope]::Children,$cond)
  for($i=0;$i -lt $wins.Count;$i++){
    $nm=$wins.Item($i).Current.Name
    O "WIN $i $nm"
    if($nm -like '*Nous Research*' -or $nm -like '*X - Google Chrome*' -or $nm -like '*chrome://inspect*' -or $nm -like '*Inspect*'){
      $w=$wins.Item($i); [KWin]::SetForegroundWindow([IntPtr]$w.Current.NativeWindowHandle)|Out-Null; $w.SetFocus(); Start-Sleep -Milliseconds 250; return $w
    }
  }
}
function AddressElement(){
  $w=Win; if(!$w){return $null}
  $walker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
  $q=New-Object System.Collections.Queue; $q.Enqueue($w); $n=0
  while($q.Count -gt 0 -and $n -lt 5000){
    $e=$q.Dequeue(); $n++
    if($e.Current.ClassName -match 'Omnibox' -or $e.Current.Name -eq 'Address and search bar'){ return $e }
    $c=$walker.GetFirstChild($e); while($c){$q.Enqueue($c); $c=$walker.GetNextSibling($c)}
  }
  return $null
}
function Url(){
  $e=AddressElement; if(!$e){return ''}
  try { $vp=$e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern); return $vp.Current.Value } catch { return '' }
}
function Nav($url){
  $e=AddressElement; if(!$e){O 'NO_OMNIBOX'; return}
  $e.SetFocus(); Start-Sleep -Milliseconds 100
  try { $vp=$e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern); $vp.SetValue($url); O "SETVALUE $url" } catch { O ('SET_ERR '+$_.Exception.Message); return }
  [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
  Start-Sleep -Seconds 4
  O ('URL_NOW '+(Url))
}
function ClickNamed($patterns){
  $w=Win; if(!$w){return $false}
  $walker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
  $q=New-Object System.Collections.Queue; $q.Enqueue($w); $n=0
  while($q.Count -gt 0 -and $n -lt 12000){
    $e=$q.Dequeue(); $n++
    $name=Clean $e.Current.Name; $type=$e.Current.ControlType.ProgrammaticName; $r=$e.Current.BoundingRectangle
    foreach($p in $patterns){
      if($name -match $p){
        O "CLICK_CAND type=$type name=$name [$([int]$r.X),$([int]$r.Y),$([int]$r.Width),$([int]$r.Height)]"
        try { $ip=$e.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern); $ip.Invoke(); Start-Sleep -Seconds 2; return $true } catch {}
        try { $tp=$e.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern); $tp.Toggle(); Start-Sleep -Seconds 2; return $true } catch {}
        try { $sp=$e.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern); $sp.Select(); Start-Sleep -Seconds 2; return $true } catch {}
        try { [System.Windows.Forms.Cursor]::Position=New-Object System.Drawing.Point(([int]($r.X+$r.Width/2)),([int]($r.Y+$r.Height/2))); [System.Windows.Forms.SendKeys]::SendWait('{ENTER}'); Start-Sleep -Seconds 2; return $true } catch {}
      }
    }
    $c=$walker.GetFirstChild($e); while($c){$q.Enqueue($c); $c=$walker.GetNextSibling($c)}
  }
  return $false
}
function DumpInteresting(){
  $w=Win; if(!$w){return}
  $walker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
  $q=New-Object System.Collections.Queue; $q.Enqueue($w); $n=0; $hits=0
  while($q.Count -gt 0 -and $n -lt 10000){
    $e=$q.Dequeue(); $n++
    $name=Clean $e.Current.Name; $type=$e.Current.ControlType.ProgrammaticName; $r=$e.Current.BoundingRectangle
    if($name -match 'Remote|debug|Discover|Port|Configure|Allow|inspect|Target|Devices|toggle|Enable'){
      O ("EL $type $name [$([int]$r.X),$([int]$r.Y),$([int]$r.Width),$([int]$r.Height)]")
      $hits++; if($hits -gt 120){break}
    }
    $c=$walker.GetFirstChild($e); while($c){$q.Enqueue($c); $c=$walker.GetNextSibling($c)}
  }
}
O ('START '+(Get-Date).ToUniversalTime().ToString('u')+' url='+ (Url))
Nav 'chrome://inspect/#remote-debugging'
DumpInteresting
ClickNamed @('Remote debugging','Enable remote debugging','debugging') | Out-Null
Start-Sleep -Seconds 3
DumpInteresting
ClickNamed @('Allow debugging','Allow') | Out-Null
Start-Sleep -Seconds 2
try { $c=(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:9222/json/version -TimeoutSec 2).Content; O ('CDP_OK '+$c.Substring(0,[Math]::Min(500,$c.Length))) } catch { O ('CDP_ERR '+$_.Exception.Message) }
'''
b64=base64.b64encode(ps.encode('utf-8')).decode()
s.run_ps(r"Remove-Item 'C:\Temp\enable_cdp_no_clipboard.b64','C:\Temp\enable_cdp_no_clipboard.ps1' -ErrorAction SilentlyContinue")
for i in range(0,len(b64),700):
    s.run_ps("Add-Content -Path 'C:\\Temp\\enable_cdp_no_clipboard.b64' -Value '{}'".format(b64[i:i+700]))
s.run_ps(r"$b=(Get-Content 'C:\Temp\enable_cdp_no_clipboard.b64' -Raw) -replace '\s',''; [IO.File]::WriteAllBytes('C:\Temp\enable_cdp_no_clipboard.ps1',[Convert]::FromBase64String($b))")
run=r'''
$tn='KestrelEnableCDPNoClip'
Unregister-ScheduledTask -TaskName $tn -Confirm:$false -ErrorAction SilentlyContinue
$action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\Temp\enable_cdp_no_clipboard.ps1"'
$trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5)
$principal=New-ScheduledTaskPrincipal -UserId 'Administrator' -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $tn -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName $tn
Start-Sleep -Seconds 18
Get-Content 'C:\Temp\x_profile_collect\enable_cdp_no_clipboard.txt' -ErrorAction SilentlyContinue | Select-Object -First 220
'''
r=s.run_ps(run)
print(r.std_out.decode(errors='replace')[:20000])
err=r.std_err.decode(errors='replace')
if err.strip(): print('STDERR',err[:3000])
