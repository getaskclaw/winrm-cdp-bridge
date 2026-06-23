"""WinRM PowerShell helper.

Usage:
  echo "Get-Process" | python3 winrm_ps.py --credentials host.env

  # Or set env var:
  export WINRM_CREDENTIALS=host.env
  echo "Get-Process" | python3 winrm_ps.py

Security:
  - Never hardcode credential paths exposed to public repos.
  - Must pass --credentials flag or set $WINRM_CREDENTIALS.
  - Default lookup paths are intentionally absent.
"""

import sys, winrm, os, argparse
from pathlib import Path

def load_creds(path: str) -> tuple[str, str, str]:
    data = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            k, v = line.split('=', 1)
        elif ':' in line:
            k, v = line.split(':', 1)
        else:
            continue
        data[k.strip().lower()] = v.strip()
    host = data.get('host') or data.get('url', '')
    if host and not host.startswith('http'):
        host = f'http://{host}:5985/wsman'
    return host, data.get('user') or data.get('username', ''), data.get('pass') or data.get('password', '')

def main():
    parser = argparse.ArgumentParser(description='Run PowerShell via WinRM')
    parser.add_argument('--credentials', '-c', help='Path to credentials file (or set $WINRM_CREDENTIALS)')
    parser.add_argument('--transport', default='ntlm', help='WinRM transport (ntlm, basic, kerberos)')
    parser.add_argument('--no-verify-cert', action='store_true', default=True, help='Skip server cert validation (not for production)')
    args = parser.parse_args()

    cred_path = args.credentials or os.environ.get('WINRM_CREDENTIALS')
    if not cred_path:
        print("ERROR: No credentials file specified. Use --credentials or $WINRM_CREDENTIALS.", file=sys.stderr)
        print("  echo 'Get-Process' | python3 winrm_ps.py --credentials myhost.env", file=sys.stderr)
        sys.exit(1)

    host, user, pwd = load_creds(cred_path)
    if not host or not user or not pwd:
        print(f"ERROR: Missing host/user/pass in {cred_path}", file=sys.stderr)
        sys.exit(1)

    ps = sys.stdin.read()
    if not ps.strip():
        print("ERROR: No PowerShell command received on stdin", file=sys.stderr)
        sys.exit(1)

    print(f"Connecting to {host} as {user}...", file=sys.stderr)
    s = winrm.Session(
        host,
        auth=(user, pwd),
        transport=args.transport,
        server_cert_validation='ignore' if args.no_verify_cert else 'validate'
    )
    r = s.run_ps(ps)
    sout = r.std_out.decode('utf-8', 'replace')
    serr = r.std_err.decode('utf-8', 'replace')
    if sout:
        print(sout, end='')
    if serr:
        print('[STDERR]', serr, sep='\n', file=sys.stderr)
    sys.exit(0 if r.status_code == 0 else r.status_code)

if __name__ == '__main__':
    main()