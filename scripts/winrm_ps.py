from pathlib import Path
import sys, winrm

def creds():
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
    return host, data.get('user') or data.get('username'), data.get('pass') or data.get('password')

host,user,pwd=creds()
ps=sys.stdin.read()
s=winrm.Session(host, auth=(user,pwd), transport='ntlm', server_cert_validation='ignore')
r=s.run_ps(ps)
sout=r.std_out.decode('utf-8','replace')
serr=r.std_err.decode('utf-8','replace')
print(sout, end='')
if serr:
    print('\n[STDERR]\n'+serr, file=sys.stderr)
sys.exit(0 if r.status_code==0 else r.status_code)
