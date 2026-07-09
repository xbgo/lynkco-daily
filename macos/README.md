# macOS

macOS 版本通过桌面配置面板管理 `launchd` 定时任务。发布包会提供 `LynkcoDaily-macOS.dmg`。

作者：小八  
抖音：小八的03  
官网：https://xbcars.cn

## 准备

源码运行时，先在仓库根目录完成配置：

```bash
cp .env.example .env
```

手动执行一次：

```bash
python3 lynkco_auto.py
```

打开桌面配置面板：

```bash
python3 lynkco_gui.py
```

如果使用 GitHub Actions 构建出来的 macOS 包，打开 `LynkcoDaily-macOS.dmg`，把 App 拖到 Applications 后运行即可。打包版配置和日志保存在：

```text
~/Library/Application Support/lynkco-daily
```

源码运行如需指定 Python 路径，可在 `.env` 中填写：

```env
PYTHON_EXE=/opt/homebrew/bin/python3
```

## 自动化

打开桌面配置面板，在“自动化”页操作：

- 每日定时执行：默认每天 `10:00`，可在时间选择框调整。
- 开机登录后执行一次：登录 macOS 后自动跑一次。
- 运行一次：立即执行签到和分享。
- 查看状态：只刷新并读取状态，不执行分享。

## 日志

日志保存在仓库根目录 `logs/`。
