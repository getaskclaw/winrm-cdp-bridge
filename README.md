# winrm-cdp-bridge

> 让 Hermes 控制 Windows 上的 Chrome。支持原生 Windows、WSL2，以及远程 Linux → Windows 三种方式。

## 先选正确的方式

Hermes 已原生支持 Windows，也可以安装在 WSL2。**如果 Hermes 和 Chrome 在同一台 Windows 电脑上，不需要先配置 Tailscale 或 WinRM。**

| 场景 | 推荐方式 | 是否需要 WinRM / Tailscale |
|---|---|---:|
| 只想在 Windows 上使用 Hermes 和 Chrome | **原生 Windows，最简单** | 否 |
| 需要 Linux/POSIX 环境或 Dashboard 内嵌终端 | **WSL2** | 否 |
| Hermes 在另一台 Linux 机器，Chrome 在 Windows | **Tailscale + WinRM** | 是 |

### 一句话答案

- **普通用户：先在 Windows 原生安装 Hermes。**
- **已经在 WSL2 开发：把 Hermes 安装在 WSL2。**
- **只有 Hermes 和 Chrome 位于不同机器时，才先设置 Tailscale 和 WinRM。**

如果不需要已有网站登录状态，直接使用 Hermes 自带的浏览器工具即可，不必配置这个仓库。

如果要控制已登录的网站：保留日常 Chrome 不动，另外启动 **Chrome Canary + 独立配置目录 + CDP**，然后在 Canary 里手动登录。

---

## 三种架构

### A. Hermes 原生运行在 Windows（推荐）

```text
Windows
├── Hermes
└── Chrome Canary
    └── CDP: 127.0.0.1:9250
```

没有跨系统网络，没有 WinRM，也不需要开放 CDP 端口。

### B. Hermes 运行在同一台电脑的 WSL2

```text
Windows                         WSL2
└── Chrome Canary  ◄──────────  Hermes
    127.0.0.1:9250              localhost 或受限的本机桥接
```

Windows 11 镜像网络通常可以直接使用 `localhost`。如果不通，再使用本文后面的受限桥接。

### C. Hermes 运行在另一台 Linux 机器

```text
Linux / Hermes
  │
  ├── Tailscale + WinRM ───────► Windows PowerShell
  └── 临时受限 CDP 隧道 ───────► Windows Chrome Canary
```

这是本仓库最初解决的场景，也是配置最多的场景。

---

# A. 原生 Windows：最短路径

## 1. 安装 Hermes

在 PowerShell 或 Windows Terminal 中运行：

```powershell
iex (irm https://hermes-agent.nousresearch.com/install.ps1)
```

安装完成后打开新的 PowerShell：

```powershell
hermes doctor
hermes setup
```

原生 Windows 支持 Hermes CLI、Gateway、TUI、Cron、浏览器工具和 MCP。只有 Dashboard 的 `/chat` 内嵌终端需要 WSL2。

官方文档：[Windows 原生指南](https://hermes-agent.nousresearch.com/docs/user-guide/windows-native)

## 2. 判断是否真的需要连接现有 Chrome

| 需求 | 做法 |
|---|---|
| 普通网页自动化，不需要已有登录 | 直接使用 Hermes 浏览器工具 |
| 要使用已登录的网站 | 继续设置 Chrome Canary + CDP |
| 只使用 OpenCLI `[cookie]` 命令 | 使用现有 Chrome，不需要 CDP |

## 3. 启动 Chrome Canary + CDP

先安装 Chrome Canary，并确保 Canary 当前没有运行。然后在普通 PowerShell 中执行：

```powershell
$candidates = @(
  "$env:LOCALAPPDATA\Google\Chrome SxS\Application\chrome.exe",
  "$env:ProgramFiles\Google\Chrome SxS\Application\chrome.exe"
)
$chrome = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { throw '找不到 Chrome Canary，请先安装。' }

$profile = "$env:LOCALAPPDATA\winrm-cdp-bridge\canary-profile"
Start-Process -FilePath $chrome -ArgumentList @(
  '--remote-debugging-address=127.0.0.1',
  '--remote-debugging-port=9250',
  "--user-data-dir=`"$profile`"",
  '--no-first-run',
  '--no-default-browser-check',
  '--new-window',
  'https://example.com'
)
```

在新打开的 Canary 中手动登录目标网站。不要复制日常 Chrome 的 Cookies 或配置目录。

## 4. 验证并连接 Hermes

```powershell
$cdp = Invoke-RestMethod 'http://127.0.0.1:9250/json/version'
$cdp.Browser
$cdp.webSocketDebuggerUrl

hermes config set browser.cdp_url $cdp.webSocketDebuggerUrl
```

重新启动 Hermes 或打开新会话，再使用浏览器工具。

Chrome 每次重启都会生成新的 WebSocket UUID。重启 Canary 后，需要重新运行上面的命令。

---

# B. WSL2：Hermes 在 Linux，Chrome 在 Windows

## 1. 安装 WSL2 和 Hermes

在管理员 PowerShell 中安装 WSL2：

```powershell
wsl --install
```

重启后进入 WSL2，在 WSL shell 中安装 Hermes：

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
source ~/.bashrc
hermes doctor
hermes setup
```

官方文档：[Windows WSL2 指南](https://hermes-agent.nousresearch.com/docs/user-guide/windows-wsl-quickstart)

## 2. 在 Windows 中启动 Canary

使用上一节的 **Chrome Canary + CDP** PowerShell 命令。Chrome 仍然运行在 Windows，不是在 WSL2 中。

## 3. 先测试 WSL2 能否直接访问 Windows CDP

在 WSL2 中运行：

```bash
curl -fsS http://127.0.0.1:9250/json/version
```

### 如果成功

```bash
WS=$(curl -fsS http://127.0.0.1:9250/json/version |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["webSocketDebuggerUrl"])')

hermes config set browser.cdp_url "$WS"
```

重新启动 Hermes 或打开新会话即可。

### 如果失败

WSL2 与 Windows 的 `localhost` 没有互通。优先选择：

1. Windows 11 22H2+：按照官方 WSL2 文档启用镜像网络。
2. 仍然不通：使用本文后面的“受限 CDP 桥接”。

WSL2 的 IP 可能在重启后变化。不要把临时 WSL IP 永久写死在防火墙规则里。

---

# C. 远程 Linux → Windows：Tailscale + WinRM

只有 Hermes 和 Chrome 位于不同机器时，才需要这一节。

## 1. 连接 Tailscale

让 Linux/Hermes 和 Windows 加入同一个 tailnet。记下：

- `<windows-tailscale-ip>`
- `<controller-tailscale-ip>`

## 2. 在 Windows 上启用 WinRM

用管理员 PowerShell 执行：

```powershell
Enable-PSRemoting -Force -SkipNetworkProfileCheck

Get-NetFirewallRule -Name 'WINRM-HTTP-In-TCP*' |
  Set-NetFirewallRule -RemoteAddress '<controller-tailscale-ip>'
```

不要把 WinRM 或 RDP 暴露到公网。建议使用专门的远程管理账号，并只授予任务需要的权限。

> `scripts/winrm_ps.py` 在只填写 IP/主机名时使用 HTTP 5985 + NTLM，适合受控的 Tailscale 网络。更严格的生产环境应使用 WinRM HTTPS 5986、证书验证和最小权限账号。

## 3. 在 Linux 上安装并测试 WinRM

```bash
git clone https://github.com/getaskclaw/winrm-cdp-bridge.git
cd winrm-cdp-bridge

python3 -m venv .venv
. .venv/bin/activate
pip install pywinrm requests-ntlm

cp .credentials.example .credentials
chmod 600 .credentials
```

编辑 `.credentials`：

```ini
host=<windows-tailscale-ip>
user=<windows-username>
pass=<windows-password>
```

本地 Windows 账号认证失败时，可尝试：

```ini
user=.\<windows-username>
```

测试：

```bash
export WINRM_CREDENTIALS="$PWD/.credentials"
printf '$env:COMPUTERNAME; whoami\n' | python3 scripts/winrm_ps.py
```

看到正确的 Windows 主机名和用户后，再设置 Chrome。

## 4. 在 Windows 上启动 Canary 并验证 CDP

使用前面的 Canary 启动命令，然后在 Windows 本机验证：

```powershell
Invoke-RestMethod 'http://127.0.0.1:9250/json/version'
```

默认让 CDP 脚本在 Windows 本机运行。只有 Hermes 必须直接连接时，才建立下一节的临时桥接。

---

# 受限 CDP 桥接（WSL2 NAT 或远程 Linux）

CDP 没有登录验证。拿到 CDP 端口的人几乎等于拿到这个浏览器。**能不用桥接，就不要用。**

## 1. 确定两个地址

- `<windows-reachable-ip>`：控制端能访问的 Windows 本机地址。
  - 远程 Linux：通常是 Windows Tailscale IP。
  - WSL2 NAT：使用 WSL2 能访问到的 Windows 宿主机地址。
- `<controller-ip>`：控制端地址。
  - 远程 Linux：Linux 的 Tailscale IP。
  - WSL2 NAT：当前 WSL2 IP。

## 2. 在 Windows 上建立受限转发

用管理员 PowerShell 执行：

```powershell
$windowsIp = '<windows-reachable-ip>'
$controllerIp = '<controller-ip>'
$externalPort = 19250
$cdpPort = 9250
$ruleName = "winrm-cdp-bridge-$externalPort"

netsh interface portproxy add v4tov4 `
  listenaddress=$windowsIp listenport=$externalPort `
  connectaddress=127.0.0.1 connectport=$cdpPort

New-NetFirewallRule `
  -DisplayName $ruleName `
  -Direction Inbound -Action Allow -Protocol TCP `
  -LocalAddress $windowsIp -LocalPort $externalPort `
  -RemoteAddress $controllerIp
```

关键区别：

- `listenaddress` 是 **Windows 本机地址**。
- `RemoteAddress` 是 **允许连接的控制端地址**。

不要使用 `listenaddress=*`、`0.0.0.0` 或 Tailscale Funnel。

## 3. 从控制端验证并配置 Hermes

在 WSL2 或远程 Linux 中执行：

```bash
CDP_HTTP='http://<windows-reachable-ip>:19250'
curl -fsS "$CDP_HTTP/json/version"

UUID=$(curl -fsS "$CDP_HTTP/json/version" |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["webSocketDebuggerUrl"].rsplit("/",1)[-1])')

hermes config set browser.cdp_url \
  "ws://<windows-reachable-ip>:19250/devtools/browser/$UUID"
```

重新启动 Hermes 或打开新会话。

## 4. 用完立即清理

在 Windows 管理员 PowerShell 中执行：

```powershell
$windowsIp = '<windows-reachable-ip>'
$externalPort = 19250
$ruleName = "winrm-cdp-bridge-$externalPort"

netsh interface portproxy delete v4tov4 `
  listenaddress=$windowsIp listenport=$externalPort
Remove-NetFirewallRule -DisplayName $ruleName

netsh interface portproxy show v4tov4
```

最后一条命令中不应再出现刚才的转发。

---

# 在 Windows 本机运行仓库脚本

CDP 保持在 `127.0.0.1` 时最安全。可以在 Windows 原生 Hermes、普通 PowerShell，或通过 WinRM 触发这些脚本。

```powershell
git clone https://github.com/getaskclaw/winrm-cdp-bridge.git
cd winrm-cdp-bridge
py -m pip install websockets
```

采集 X 用户时间线：

```powershell
$env:CDP_PORT = '9250'
$env:CDP_TARGET = 'https://x.com/<username>'
$env:CDP_OUTPUT = "$env:TEMP\cdp_scrape_results.json"
py .\scripts\cdp-ws-scraper.py
```

采集当前 X 搜索页：

```powershell
$env:CDP_PORT = '9250'
$env:CDP_OUTPUT_DIR = "$env:USERPROFILE\Desktop\x-search-output"
py .\scripts\cdp-ws-search-scraper.py
```

这些脚本依赖 X 当前页面结构、登录状态和限流策略。空结果可能表示页面未加载、登录失效、CDP 不可用或被限流，不一定表示没有数据。

---

# 文件说明

## 建议优先使用

| 文件 | 用途 |
|---|---|
| `scripts/winrm_ps.py` | 远程 Linux 通过 WinRM 执行 Windows PowerShell |
| `scripts/cdp-ws-scraper.py` | 通过本机 CDP WebSocket 采集 X 用户时间线 |
| `scripts/cdp-ws-search-scraper.py` | 采集当前 X 搜索页 |
| `references/chrome-control-windows-runbook.md` | Windows Chrome 控制流程和常见问题 |
| `references/remote-cdp-tunnel-via-portproxy.md` | 临时 CDP 转发与清理 |
| `references/x-api-caps-rate-limits.md` | X 限流和退避策略 |

## 实验性脚本

以下脚本来自特定环境，不是通用的一键工具。运行前必须阅读和修改：

| 文件 | 注意事项 |
|---|---|
| `enable_cdp_no_clipboard.py` | 使用 UI Automation 和计划任务；依赖交互式桌面与特定窗口 |
| `refresh_chrome_policy.py` | 使用 SendKeys；焦点错误会操作错误窗口 |
| `install_opencli_windows.py` | 会安装远程软件；生产使用前应锁定版本并验证下载文件 |
| `winrm_uia_collector.py` | UIA 模板，会抢焦点并可能覆盖剪贴板 |
| `winrm_uia_live_collector.py` | UIA 模板，需要先修改 `CONFIG`，不要直接运行 |

---

# 安全规则

1. **日常 Chrome 和 CDP Chrome 分开。** 优先使用 Canary 和独立配置目录。
2. **不要复制 Cookies、`Local State` 或真实 Chrome 配置目录。** 在 Canary 中手动登录。
3. **不要强制结束全部 Chrome。** 禁止 `Stop-Process -Name chrome -Force`。
4. **CDP 默认只监听 `127.0.0.1`。** 不要监听所有接口。
5. **非必要不开放 CDP。** 临时开放时，只允许控制端 IP，用完立即删除规则。
6. **不要提交凭据。** `.credentials`、密码、令牌和真实主机信息不能进入 Git。
7. **UI Automation 是最后手段。** 它会抢焦点、发送按键，也可能影响剪贴板。
8. **只自动化你有权控制的机器、账号和数据。**

---

# 常见问题

| 问题 | 最可能原因 | 处理方法 |
|---|---|---|
| Windows 上可以直接运行 Hermes 吗？ | 可以，原生支持 | 使用官方 `install.ps1`，不需要 WSL |
| 应该选择原生 Windows 还是 WSL2？ | 取决于是否需要完整 POSIX 环境 | 普通使用选原生；需要 Dashboard 终端或 Linux 开发环境选 WSL2 |
| 原生 Windows 还需要 WinRM 吗？ | 不需要 | Hermes 和 Chrome 在同一系统内直接通信 |
| WSL2 还需要 Tailscale 吗？ | 同一台电脑通常不需要 | 先测试 localhost；失败时设置镜像网络或本机桥接 |
| `/json/version` 失败 | Canary 启动参数未生效或端口不同 | 检查 Chrome 进程命令行中的 `remote-debugging-port` |
| 新 Canary 没有网站登录状态 | 使用了独立配置目录，这是正常现象 | 在 Canary 中手动登录，不要复制 Cookies |
| Hermes 连接返回 404 | Chrome 重启后 UUID 已变化 | 重新读取 `/json/version` 并更新 `browser.cdp_url` |
| OpenCLI `[intercept]` 返回空结果 | CDP 不可用 | 先用 `[cookie]` 命令验证登录和 Browser Bridge |
| 远程 WinRM 超时 | Tailscale、端口或防火墙问题 | 依次检查 Tailscale、5985/5986 和 Windows 防火墙 |
| 用户看不到远程启动的 Chrome | Chrome 被启动在非交互式 Windows 会话 | 在登录用户桌面中手动启动，或使用交互式计划任务 |

---

# 官方 Hermes 文档

- [安装指南](https://hermes-agent.nousresearch.com/docs/getting-started/installation)
- [Windows 原生指南](https://hermes-agent.nousresearch.com/docs/user-guide/windows-native)
- [Windows WSL2 指南](https://hermes-agent.nousresearch.com/docs/user-guide/windows-wsl-quickstart)

---

# 项目范围

这个仓库提供 Windows Chrome CDP、WinRM 和跨环境桥接的脚本与踩坑记录。它不是远程桌面产品，也不是绕过网站权限或安全控制的工具。

最简单的默认路径是：

> **Windows 原生 Hermes → 独立 Chrome Canary → 本机 CDP。**

只有需要 Linux/POSIX 环境时才选择 WSL2；只有 Hermes 和 Chrome 位于不同机器时才使用 Tailscale + WinRM。

---

由 [AskClaw](https://x.com/GetAskClaw) 维护。🜂
