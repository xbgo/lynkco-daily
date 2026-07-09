# Windows

Windows 版本通过桌面配置面板管理计划任务。

作者：小八  
抖音：小八的03  
官网：https://xbcars.cn

## 准备

先在仓库根目录完成配置：

```powershell
Copy-Item .env.example .env
notepad .env
```

手动执行一次：

```powershell
python .\lynkco_auto.py
```

打开桌面配置面板：

```powershell
python .\lynkco_gui.py
```

如需指定 Python 路径，在 `.env` 中填写：

```env
PYTHON_EXE=C:\Path\To\python.exe
```

## 自动化

打开桌面配置面板，在“自动化”页操作：

- 每日定时执行：默认每天 `10:00`，可在时间选择框调整。
- 开机登录后执行一次：登录 Windows 后自动跑一次。
- 运行一次：立即执行签到和分享。
- 查看状态：只刷新并读取状态，不执行分享。

日志保存在仓库根目录 `logs/`。
