# OpenUBMC Task Watcher

OpenUBMC Task Watcher 是一个面向 openUBMC 开源实习的任务监控器。它读取 GitCode issue 接口，自动识别新发布的实习任务和 SIG 表格里的“待认领”任务，并通过 Windows 桌面通知、微信、邮箱或通用 Webhook 提醒用户。

## 功能

- 识别新增的 `【开源实习】` issue
- 识别带 `intern` 标签的新 issue
- 解析 SIG 汇总 issue 表格
- 识别表格里新增或变成 `待认领` 的任务
- 使用 `state.json` 去重，避免重复提醒
- 支持 Windows 桌面通知、控制台通知、微信通知、邮箱通知和通用 Webhook
- 支持 Windows 定时任务，每隔几分钟自动检查

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 快速使用

```powershell
.\.venv\Scripts\python.exe .\openubmc_task_watcher.py --once --list
```

初始化基线，避免把已有任务都通知一遍：

```powershell
.\.venv\Scripts\python.exe .\openubmc_task_watcher.py --init --state .\state.json
```

测试通知：

```powershell
.\.venv\Scripts\python.exe .\openubmc_task_watcher.py --test-notify --notify toast,console
```

注册 Windows 定时任务，默认每 5 分钟检查一次：

```powershell
.\install_windows_task.ps1
```

卸载定时任务：

```powershell
.\uninstall_windows_task.ps1
```

## 配置微信和邮箱

复制配置模板：

```powershell
Copy-Item .\.env.example .\.env
```

然后编辑 `.env`。

微信通知支持两种方式，任选其一即可：

- Server 酱：配置 `SERVER_CHAN_SENDKEY`
- PushPlus：配置 `PUSHPLUS_TOKEN`

邮箱通知通过 SMTP 发送，例如 163 邮箱：

```env
SMTP_HOST=smtp.163.com
SMTP_PORT=465
SMTP_SSL=true
SMTP_STARTTLS=false
SMTP_USER=your_account@163.com
SMTP_PASSWORD=your_smtp_authorization_code
SMTP_FROM=your_account@163.com
SMTP_TO=receiver@example.com
```

注意：`SMTP_PASSWORD` 通常不是邮箱登录密码，而是邮箱后台生成的 SMTP 授权码。

配置完成后测试全部通知：

```powershell
.\.venv\Scripts\python.exe .\openubmc_task_watcher.py --test-notify --notify toast,wechat,email --env-file .\.env
```

## 通知后端

`--notify` 使用逗号分隔，可选值：

- `toast`：Windows 桌面通知
- `console`：控制台输出
- `wechat`：微信聚合通知，自动使用已配置的 Server 酱或 PushPlus
- `serverchan`：只使用 Server 酱
- `pushplus`：只使用 PushPlus
- `email`：SMTP 邮箱通知
- `webhook`：通用 JSON Webhook

## 数据源

工具读取 GitCode issue API：

```text
https://gitcode.com/issuepr/api/v1/issue/4064052/issues
```

目标仓库：

```text
https://gitcode.com/openUBMC/community
```
