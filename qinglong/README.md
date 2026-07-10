# 青龙面板

青龙版本入口为 `qinglong/lynkco_ql.py`，核心逻辑复用仓库根目录脚本。

作者：小八  
抖音：小八的03  
官网：https://xbcars.cn

## 订阅

仓库地址：

```text
https://github.com/xbgo/lynkco-daily.git
```

任务命令：

```bash
python3 qinglong/lynkco_ql.py
```

定时：

```cron
0 10 * * *
```

安装依赖：

```bash
cd /ql/data/repo/<仓库目录>
pip3 install -r requirements.txt
```

## 单账号

在青龙“环境变量”中添加：

```env
LYNKCO_REFRESH_TOKEN=bearer...
LYNKCO_DEVICE_ID=your_device_id
LYNKCO_DEVICE_TYPE=IOS
LYNKCO_APP_VERSION=4.1.4
```

签名配置可使用环境变量：

```env
LYNKCO_APP_CODE=
LYNKCO_CA_KEY=
LYNKCO_CA_SECRET=
```

也可在仓库根目录放置 `lynkco_private.py`。不要把真实配置提交到公开仓库。

## 多账号

使用 `LYNKCO_CONFIG`，值为 JSON。`name` 会作为推送显示名称。

```json
[
  {
    "name": "account1",
    "refreshToken": "bearer...",
    "deviceId": "device_id_1",
    "deviceType": "IOS",
    "appVersion": "4.1.4"
  },
  {
    "name": "account2",
    "refreshToken": "bearer...",
    "deviceId": "device_id_2",
    "deviceType": "ANDROID",
    "appVersion": "4.1.4"
  }
]
```

如需为单个账号指定签名配置：

```json
{
  "appCode": "",
  "caKey": "",
  "caSecret": ""
}
```

## 通知

默认优先调用青龙自带 `notify.py`。青龙通知正常时，脚本会推送任务结果。

常用变量：

```env
LYNKCO_ACCOUNT_NAME=
LYNKCO_FETCH_ACCOUNT_NAME=1
LYNKCO_SHARE_DELAY_SECONDS=60
LYNKCO_QL_ARGS=
LYNKCO_QL_TIMEOUT=180
LYNKCO_QL_NOTIFY=1
LYNKCO_NOTIFY_ON_SUCCESS=1
LYNKCO_QL_NOTIFY_LIMIT=6000
LYNKCO_QL_RAW_LOG=0
LYNKCO_HITOKOTO=1
```

默认日志显示用户摘要。排错时打开原始接口输出：

```env
LYNKCO_QL_RAW_LOG=1
```

追加底层脚本参数：

```env
LYNKCO_QL_ARGS=--status
```

## 缓存

青龙入口会把 token/device 缓存在：

```text
qinglong/.runtime/
```
