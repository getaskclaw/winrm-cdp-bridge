from pathlib import Path
import base64, winrm, sys, time

def get_session():
    data={}
    for line in Path('/root/2604/26429').read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#'): continue
        if '=' in line: k,v=line.split('=',1)
        elif ':' in line: k,v=line.split(':',1)
        else: continue
        data[k.strip().lower()]=v.strip()
    host=data.get('host') or data.get('url')
    if not host.startswith('http'): host=f'http://{host}:5985/wsman'
    return winrm.Session(host, auth=(data.get('user') or data.get('username'), data.get('pass') or data.get('password')), transport='ntlm', server_cert_validation='ignore')

ps = r'''
$ErrorActionPreference='SilentlyContinue'
$log='C:\Temp\opencli\policy_refresh.log'
function L($m){ Add-Content -Path $log -Value ((Get-Date).ToString('s')+' '+$m) }
L 'start'
$chrome='C:\Program Files\Google\Chrome\Application\chrome.exe'
Start-Process $chrome -ArgumentList 'chrome://policy/'
Start-Sleep -Seconds 3
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait('{TAB}{TAB}{ENTER}')
Start-Sleep -Seconds 8
L 'done'
'''
b64=base64.b64encode(ps.encode('utf-16le')).decode()
s=get_session()
cmd=f"$b='{b64}'; $p='C:\\Temp\\opencli\\policy_refresh.ps1'; [IO.File]::WriteAllBytes($p,[Convert]::FromBase64String($b)); $tn='KestrelOpenCLIPolicyRefresh'; Unregister-ScheduledTask -TaskName $tn -Confirm:$false -ErrorAction SilentlyContinue; $a=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -File '+$p); $t=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5); $pr=New-ScheduledTaskPrincipal -UserId 'Administrator' -LogonType Interactive -RunLevel Highest; Register-ScheduledTask -TaskName $tn -Action $a -Trigger $t -Principal $pr -Force | Out-Null; Start-ScheduledTask -TaskName $tn; Start-Sleep -Seconds 15; Get-Content 'C:\\Temp\\opencli\\policy_refresh.log' -ErrorAction SilentlyContinue"
r=s.run_ps(cmd)
print(r.std_out.decode('utf-8','replace'))
if r.std_err: print(r.std_err.decode('utf-8','replace'), file=sys.stderr)
