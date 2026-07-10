# lynkco-daily

领克 App 每日签到与分享自动化脚本。脚本会使用你自己的 `refreshToken` 和设备信息刷新登录态，然后执行签到、自动选择社区文章、完成分享上报，并把结果推送到你配置的通知渠道。

作者：小八  
抖音：小八的03  
官网：https://xbcars.cn

## 适合谁用

- 想每天自动签到、自动完成分享任务的个人用户。
- 想部署到 Windows、macOS 或青龙面板定时执行的用户。
- 能自己准备 `refreshToken` 和设备信息的用户。

本项目不是领克官方项目。使用前请先阅读 [免责声明](DISCLAIMER.md)。

本脚本仅供学习交流使用，请勿用于商业用途。使用本脚本所造成的一切后果，与作者无关。请遵守相关法律法规，不得用于非法用途。

## 功能

- 自动刷新 `access token`
- 每日签到
- 自动获取社区文章并执行分享任务
- 读取连续签到天数、补签卡、积分、能量体
- 支持 PushPlus、Server 酱、Bark、通用 Webhook
- 支持桌面配置面板，配置、运行、定时开关都可以本地填写
- 支持 Windows 计划任务、macOS launchd、青龙面板
- GitHub Actions 可构建 Windows `.exe` 和 macOS `.dmg`

## 安全提醒

`refreshToken` 等同于长期登录凭证，泄露后别人可能复用你的登录状态。请不要把下面这些内容上传到 GitHub、Issue、截图、日志或群聊：

- `.env`
- `lynkco_token.json`
- `lynkco_device.json`
- 手机号、验证码
- `token` / `refreshToken`
- `deviceId` / `hardwareDeviceId`
- 抓包原文

上传前建议自己再扫一遍：

```bash
git status --short
```

如果 `refreshToken` 已经泄露，请立即修改账号密码、退出已登录设备，并重新获取新的 `refreshToken`。

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/xbgo/lynkco-daily.git
cd lynkco-daily
```

### 2. 准备 Python

需要 Python 3.8 或更高版本。

```bash
python --version
```

安装依赖：

```bash
pip install -r requirements.txt
```

日常签到和分享脚本只使用 Python 标准库。桌面配置面板使用 `customtkinter` 和 `Pillow`，安装依赖后界面会更接近现代桌面应用。

### 3. 复制配置文件

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

macOS / Linux：

```bash
cp .env.example .env
```

推荐先打开桌面配置面板：

```bash
python lynkco_gui.py
```

也可以手动编辑 `.env`，至少填写：

```env
LYNKCO_REFRESH_TOKEN=
LYNKCO_DEVICE_ID=
LYNKCO_DEVICE_TYPE=IOS
LYNKCO_APP_VERSION=4.1.4
```

当前日常任务只需要 `refreshToken`、`deviceId`、`deviceType`。`deviceId` 请保持和当前 App 登录设备一致，这样更不容易触发账号被其他设备挤下线。

不会获取字段的用户可参考：[Fiddler 抓包获取配置](docs/fiddler-capture.md)。

### 4. 测试账号状态

```bash
python lynkco_daily.py --status
```

看到连续签到、补签卡、积分、能量体等字段后，再执行每日任务：

```bash
python lynkco_auto.py
```

默认执行内容是：

```bash
python lynkco_daily.py --latest-article
```

桌面配置面板里的“运行日志”默认显示和推送一致的用户文案，原始接口输出会保存到 `logs/YYYY-MM-DD.log`，排错时再查看。

## 常用命令

查看脚本会选择哪篇文章：

```bash
python lynkco_daily.py --latest-article-only
```

签到并分享最新文章：

```bash
python lynkco_daily.py --latest-article
```

只签到，不分享：

```bash
python lynkco_daily.py --skip-share
```

只刷新 token：

```bash
python lynkco_daily.py --refresh-only
```

手动指定文章 ID：

```bash
python lynkco_daily.py --business-no 文章ID --first 文章
```

把参数透传给自动化入口：

```bash
python lynkco_auto.py -- --latest-article --skip-share
```

## 配置说明

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `LYNKCO_REFRESH_TOKEN` | 是 | 长期登录凭证 |
| `LYNKCO_TOKEN` | 否 | access token，不用手填 |
| `LYNKCO_DEVICE_ID` | 是 | App 登录设备的 deviceId，保持和当前登录设备一致 |
| `LYNKCO_DEVICE_TYPE` | 是 | `IOS` 或 `ANDROID` |
| `LYNKCO_APP_VERSION` | 否 | 例如 `4.1.4`；留空时分享接口默认使用 `4.2.3` |
| `LYNKCO_ACCOUNT_NAME` | 否 | 推送里显示的名称；留空则使用接口返回名称 |
| `LYNKCO_LATEST_ARTICLE` | 否 | 默认 `1`，自动选文章 |
| `LYNKCO_LATEST_ARTICLE_LIMIT` | 否 | 默认 `0`，速度最快；填 `1/3/5` 会额外校验发布时间 |
| `LYNKCO_SHARE_DELAY_SECONDS` | 否 | 签到完成后等待再分享，默认 `60` 秒 |
| `LYNKCO_SCHEDULE_TIME` | 否 | 图形界面安装定时任务时使用，默认 `10:00` |

## 通知

推荐直接打开桌面配置面板，在“通知配置”页填写。填完以后点“测试通知”，不用等定时任务执行。

命令行测试通知：

```bash
python lynkco_auto.py --notify-test
```

开启通知：

```env
LYNKCO_NOTIFY=1
LYNKCO_NOTIFY_ON_SUCCESS=1
LYNKCO_NOTIFY_TITLE=领克每日任务
```

至少填写一个渠道，任选一个即可：

```env
# PushPlus：只填 token，不填完整 URL
LYNKCO_PUSHPLUS_TOKEN=

# Server 酱 Turbo：只填 SendKey
LYNKCO_SERVERCHAN_SENDKEY=

# Bark：填完整前缀，例如 https://api.day.app/你的Key
LYNKCO_BARK_URL=

# 自建 Webhook：接收 POST JSON，字段为 title/content/status
LYNKCO_NOTIFY_WEBHOOK=
```

推送内容示例：

```text
领克每日任务成功

你好，车友昵称

今天的领克任务已完成。

签到：今日已签到
分享：成功（预计 +5 积分）

连续签到：2 天
补签卡：1 张
当前积分：1888
当前能量体：1888
分享文章：6月榜单丨比阳光更耀眼的，是Co客社区的精彩
耗时：3.8s

今日一言：
「真正重要的东西，总是没有的人比拥有的人清楚。」
出处：银魂

作者：小八
抖音：小八的03
官网：https://xbcars.cn
```

一言默认使用：

```env
LYNKCO_HITOKOTO_URL=https://v1.hitokoto.cn/?encode=json&charset=utf-8
```

关闭一言：

```env
LYNKCO_HITOKOTO=0
```

## Windows 定时

打开桌面配置面板：

```powershell
python .\lynkco_gui.py
```

在“自动化”页打开“每日定时执行”，默认每天 10:00 运行；也可以打开“开机登录后执行一次”。

## macOS 定时

打开桌面配置面板：

```bash
python3 lynkco_gui.py
```

在“自动化”页打开“每日定时执行”，默认每天 10:00 运行；也可以打开“开机登录后执行一次”。

## 青龙面板

青龙用户看这里：[qinglong/README.md](qinglong/README.md)

任务命令：

```bash
python3 qinglong/lynkco_ql.py
```

定时：

```cron
0 10 * * *
```

## 赞赏

觉得好用可以随缘支持：

![赞赏码](assets/zsm.png)

## License

MIT
