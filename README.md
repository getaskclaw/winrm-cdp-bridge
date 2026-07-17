# winrm-cdp-bridge

> 从 Linux 或 Hermes 通过 Tailscale + WinRM 控制远程 Windows，并用 Chrome CDP 操作独立的浏览器会话。

## 先说结论：Windows Chrome 应该先设置什么？

**先保留日常使用的 Chrome，不要改它。需要 CDP 时，优先安装 Chrome Canary，并为它使用独立的新配置目录。**

推荐顺序：

1. 两台机器先连入同一个 **Tailscale** 网络。
2. 在 Windows 上启用 **WinRM**，只允许控制端的 Tailscale IP 访问。
3. 从 Linux 测试 WinRM：`hostname` 和 `whoami` 必须成功。
4. 在 Windows 上启动独立的 **Chrome Canary + CDP**。
5. 在这个 Canary 窗口里手动登录目标网站。
6. 在 Windows 本机验证 `http://127.0.0.1:9250/json/version`。
7. 默认让 CDP 脚本在 Windows 本机运行；只有 Hermes 必须直接连接时，才临时建立受限隧道。

不要一上来就开放 CDP 端口。**CDP 没有登录验证，拿到端口的人几乎等于拿到这个浏览器。**

---

## 什么时候需要 CDP？

| 需求 | 推荐方式 | 是否需要 CDP |
|---|---|---:|
| 在 Windows 上远程执行 PowerShell | WinRM | 否 |
| 使用 OpenCLI 的 `[cookie]` 命令读取已有登录状态 | 日常 Chrome + OpenCLI | 否 |
| 导航、点击、执行 JavaScript、读取 DOM | Chrome Canary + CDP WebSocket | 是 |
| 从 Hermes 的浏览器工具直接控制 Windows Chrome | Chrome Canary + 临时受限隧道 | 是 |
| 没有 CDP 时读取可见窗口 | UI Automation，最后手段 | 否，但会影响桌面 |

如果只是运行 `twitter profile`、`twitter tweets` 等 OpenCLI `[cookie]` 命令，**不要设置 CDP**。直接使用已有 Chrome 会更简单。

---

## 架构

```text
Linux / Hermes
  │
  ├── Tailscale + WinRM ───────────────► Windows PowerShell
  │
  └── 可选：受限的临时 CDP 隧道 ──────► Windows Tailscale IP
                                           │
                                           └── 127.0.0.1:9250
                                               Chrome Canary + 独立配置目录
```

默认安全边界：

- WinRM 只在 Tailscale 内使用。
- Chrome CDP 只监听 `127.0.0.1`。
- 日常 Chrome 和 CDP Chrome 分开。
- 网站登录由用户在 Canary 中手动完成。
- 不复制 Chrome Cookies，不复制真实浏览器配置目录。

---

## 快速开始

### 1. 准备两台机器

**Linux / Hermes 控制端：**

- Git
- Python 3
- Tailscale

**Windows 浏览器端：**

- Tailscale
- WinRM
- Chrome Canary（推荐）
- Python 3 + `websockets`（仅运行 CDP 脚本时需要）

两台机器连入同一个 tailnet 后，记下：

- `<windows-tailscale-ip>`
- `<controller-tailscale-ip>`

### 2. 在 Windows 上启用 WinRM

用管理员 PowerShell 执行：

```powershell
Enable-PSRemoting -Force -SkipNetworkProfileCheck

# 只允许控制端的 Tailscale IP 访问 WinRM。
Get-NetFirewallRule -Name 'WINRM-HTTP-In-TCP*' |
  Set-NetFirewallRule -RemoteAddress '<controller-tailscale-ip>'
```

建议使用专门的远程管理账号，并只授予任务真正需要的权限。不要把 WinRM 或 RDP 暴露到公网。

> 当前 `winrm_ps.py` 在只填写主机名/IP 时使用 HTTP 5985 + NTLM，适合受控的 Tailscale 网络。更严格的生产环境应使用 WinRM HTTPS 5986、证书验证和最小权限账号。

### 3. 在 Linux 上安装并测试 WinRM

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

如果 Windows 本地账号认证失败，可尝试：

```ini
user=.\<windows-username>
```

测试连接：

```bash
export WINRM_CREDENTIALS="$PWD/.credentials"
printf '$env:COMPUTERNAME; whoami\n' | python3 scripts/winrm_ps.py
```

看到 Windows 主机名和正确用户后，再继续设置 Chrome。不要把 `.credentials` 提交到 Git；它已经在 `.gitignore` 中。

### 4. 在 Windows 上启动独立的 Chrome Canary

先安装 Chrome Canary。然后在普通 PowerShell 中运行：

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

然后：

1. 在新打开的 Canary 中手动登录目标网站。
2. 不要强制结束这个 Chrome。
3. 不要把日常 Chrome 的配置或 Cookies 复制过来。

为什么推荐 Canary：Windows 上已有普通 Chrome 时，再启动同一个 Chrome 程序，新的启动参数可能被合并到旧进程并被忽略。Canary 是独立程序，最少踩坑。

### 5. 在 Windows 本机验证 CDP

```powershell
$cdp = Invoke-RestMethod 'http://127.0.0.1:9250/json/version'
$cdp.Browser
$cdp.webSocketDebuggerUrl
```

必须返回浏览器名称和 `webSocketDebuggerUrl`。如果失败，先检查 Chrome 的启动参数：

```powershell
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
  Where-Object { $_.CommandLine -match 'remote-debugging-port' } |
  Select-Object ProcessId, CommandLine
```

不要把“端口正在监听”当成验证成功。以 `/json/version` 的实际响应为准。

---

## 在 Windows 本机运行 CDP 脚本（推荐）

这是最简单、最安全的方式：CDP 保持在 `127.0.0.1`，不开放网络端口。

在 Windows 上克隆仓库并安装依赖：

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

采集 X 搜索页：

```powershell
# 先在 Canary 中打开目标搜索页。
$env:CDP_PORT = '9250'
$env:CDP_OUTPUT_DIR = "$env:USERPROFILE\Desktop\x-search-output"
py .\scripts\cdp-ws-search-scraper.py
```

这两个脚本依赖 X 当前页面结构和登录状态。X 改版、限流或登出后，结果可能为空；不要把空结果直接理解成“没有数据”。

---

## 让 Hermes 直接连接 Windows Chrome（可选）

只有 Hermes 浏览器工具必须直接连接时才做这一步。默认应让脚本在 Windows 本机连接 `127.0.0.1:9250`。

### 1. 在 Windows 上建立受限转发

用管理员 PowerShell 执行。注意两个 IP 不一样：

- `listenaddress` 是 **Windows 的 Tailscale IP**。
- `RemoteAddress` 是 **Linux/Hermes 控制端的 Tailscale IP**。

```powershell
$windowsIp = '<windows-tailscale-ip>'
$controllerIp = '<controller-tailscale-ip>'
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

### 2. 在 Linux 上验证并配置 Hermes

```bash
CDP_HTTP='http://<windows-tailscale-ip>:19250'
curl -fsS "$CDP_HTTP/json/version"

UUID=$(curl -fsS "$CDP_HTTP/json/version" |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["webSocketDebuggerUrl"].rsplit("/",1)[-1])')

hermes config set browser.cdp_url \
  "ws://<windows-tailscale-ip>:19250/devtools/browser/$UUID"
```

重新启动 Hermes 或开启新会话后，再测试浏览器工具。Chrome 每次重启都会生成新的 UUID；重启后必须重新读取 `/json/version` 并更新 `browser.cdp_url`。

### 3. 用完立即清理

在 Windows 管理员 PowerShell 中执行：

```powershell
$windowsIp = '<windows-tailscale-ip>'
$externalPort = 19250
$ruleName = "winrm-cdp-bridge-$externalPort"

netsh interface portproxy delete v4tov4 `
  listenaddress=$windowsIp listenport=$externalPort
Remove-NetFirewallRule -DisplayName $ruleName

netsh interface portproxy show v4tov4
```

最后一条命令中不应再出现刚才的转发。

---

## 文件说明

### 建议优先使用

| 文件 | 用途 |
|---|---|
| `scripts/winrm_ps.py` | 从 Linux 通过 WinRM 执行 PowerShell |
| `scripts/cdp-ws-scraper.py` | 在 Windows 本机通过 CDP WebSocket 采集 X 用户时间线 |
| `scripts/cdp-ws-search-scraper.py` | 在 Windows 本机采集当前 X 搜索页 |
| `references/chrome-control-windows-runbook.md` | Windows Chrome 控制流程和常见问题 |
| `references/remote-cdp-tunnel-via-portproxy.md` | 临时 CDP 转发与清理 |
| `references/x-api-caps-rate-limits.md` | X 限流和退避策略 |

### 实验性脚本

以下脚本来自特定环境，不是通用的一键工具。运行前必须阅读和修改：

| 文件 | 注意事项 |
|---|---|
| `enable_cdp_no_clipboard.py` | 使用 UI Automation 和计划任务；依赖交互式桌面与特定窗口 |
| `refresh_chrome_policy.py` | 使用 SendKeys，焦点错误会操作错误窗口 |
| `install_opencli_windows.py` | 会在远程 Windows 上安装软件；生产使用前应锁定版本并校验下载文件 |
| `winrm_uia_collector.py` | UIA 模板，会抢焦点并可能覆盖剪贴板 |
| `winrm_uia_live_collector.py` | UIA 模板，需要先修改 `CONFIG`，不要直接运行 |

仓库没有承诺这些实验性脚本适用于所有 Windows 版本或所有 Chrome 环境。

---

## 安全规则

1. **不要强制结束全部 Chrome。** 禁止 `Stop-Process -Name chrome -Force`。这会影响所有浏览器实例，并可能破坏未写入的数据或登录状态。
2. **不要让 CDP 监听 `0.0.0.0`。** 默认只用 `127.0.0.1`。
3. **不要公开 CDP 端口。** 必须临时开放时，只允许控制端的 Tailscale IP，并在任务完成后删除转发和防火墙规则。
4. **不要复制 Cookies、`Local State` 或真实 Chrome 配置目录。** 使用新的配置目录，并手动登录。
5. **不要提交凭据。** `.credentials`、密码、令牌和真实主机信息都不能进入 Git。
6. **UI Automation 是最后手段。** 它会抢焦点、发送按键，也可能影响剪贴板。
7. **只自动化你有权控制的机器、账号和数据。**

---

## 常见问题

| 问题 | 最可能原因 | 处理方法 |
|---|---|---|
| WinRM 超时 | Tailscale 未连通或 5985/5986 被防火墙拦截 | 先检查 Tailscale，再检查端口和 Windows 防火墙 |
| WinRM 返回 401 | 用户名格式或认证方式不匹配 | 尝试 `.\用户名`，并使用 NTLM |
| Canary 已打开，但 `/json/version` 失败 | 启动参数未生效或端口不同 | 检查 Chrome 进程命令行中的 `remote-debugging-port` |
| 新 Chrome 没有网站登录状态 | 使用了新的配置目录，这是正常现象 | 在该窗口中手动登录，不要复制 Cookies |
| Hermes 连接返回 404 | Chrome 重启后 UUID 已变化 | 重新读取 `/json/version` 并更新 `browser.cdp_url` |
| OpenCLI `[intercept]` 返回空结果 | CDP 不可用 | 先用 `[cookie]` 命令验证登录和 Browser Bridge |
| CDP 脚本一直没有结果 | 页面未加载、已登出、被限流或 DOM 已变化 | 查看浏览器页面，降低频率，检查脚本日志 |
| 用户看不到远程启动的 Chrome | Chrome 被启动在非交互式 Windows 会话 | 在已登录用户的桌面中手动启动，或使用交互式计划任务 |

---

## 项目范围

这个仓库提供的是可复用的脚本、模板和踩坑记录，不是完整的远程桌面产品，也不是绕过网站权限或安全控制的工具。

最稳妥的默认路径只有一句话：

> **Tailscale → WinRM 测通 → 独立 Canary + 新配置目录 → 本机验证 CDP → 本机运行脚本；非必要不开放 CDP。**

---

由 [AskClaw](https://x.com/GetAskClaw) 维护。🜂
