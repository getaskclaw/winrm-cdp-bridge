from pathlib import Path
import winrm, sys

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
    if not host.startswith('http'):
        host=f'http://{host}:5985/wsman'
    user=data.get('user') or data.get('username')
    pwd=data.get('pass') or data.get('password')
    return winrm.Session(host, auth=(user,pwd), transport='ntlm', server_cert_validation='ignore')

s=get_session()
ps=r'''
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
New-Item -ItemType Directory -Force -Path C:\Temp\opencli | Out-Null
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
  $url='https://nodejs.org/dist/v22.22.2/node-v22.22.2-x64.msi'
  $msi='C:\Temp\opencli\node-v22.22.2-x64.msi'
  if (-not (Test-Path $msi)) { Invoke-WebRequest -Uri $url -OutFile $msi -UseBasicParsing }
  $p=Start-Process msiexec.exe -ArgumentList @('/i',$msi,'/qn','/norestart') -Wait -PassThru
  "NODE_INSTALL_EXIT=$($p.ExitCode)"
}
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
"NODE_VER=$(& node -v)"
"NPM_VER=$(& npm -v)"
& npm install -g @jackwener/opencli
"OPENCLI_VER=$(& opencli --version)"
'''
r=s.run_ps(ps)
print(r.std_out.decode('utf-8','replace'))
if r.std_err:
    print(r.std_err.decode('utf-8','replace'), file=sys.stderr)
sys.exit(0 if r.status_code==0 else r.status_code)
