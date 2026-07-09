# Fiddler 抓包获取配置

本文用于获取自己账号运行脚本所需的配置字段。不要抓取、保存或传播他人账号数据。

## 准备

- 电脑安装 Fiddler Classic 或 Fiddler Everywhere
- 手机已安装领克 App
- 电脑和手机连接同一个局域网

## 配置 Fiddler

以 Fiddler Classic 为例：

1. 打开 Fiddler。
2. 进入 `Tools` -> `Options` -> `HTTPS`。
3. 勾选 `Capture HTTPS CONNECTs` 和 `Decrypt HTTPS traffic`。
4. 按提示安装并信任 Fiddler 根证书。
5. 进入 `Tools` -> `Options` -> `Connections`。
6. 勾选 `Allow remote computers to connect`。
7. 记录监听端口，默认是 `8888`。
8. 重启 Fiddler。

查看电脑局域网 IP：

```powershell
ipconfig
```

常见格式为 `192.168.x.x`。

## 配置手机代理

在手机 Wi-Fi 设置中，将当前 Wi-Fi 的代理改为手动：

```text
服务器：电脑局域网 IP
端口：8888
```

然后用手机浏览器访问：

```text
http://电脑局域网IP:8888
```

下载并安装 Fiddler 证书。

iOS 还需要到：

```text
设置 -> 通用 -> 关于本机 -> 证书信任设置
```

打开对应证书的完全信任。

如果 App 无法联网或 Fiddler 看不到解密内容，先恢复手机代理和证书设置。本文不提供绕过证书校验的步骤。

## 抓取登录接口

1. 在 Fiddler 中清空当前会话。
2. 手机打开领克 App。
3. 退出当前账号。
4. 重新登录账号，建议使用验证码登录。
5. 在 Fiddler 中搜索以下接口：

```text
/auth/login/mobileCodeLogin
```

常见 Host：

```text
app-services.lynkco.com.cn
app-api-gw-toc.lynkco.com
```

打开该请求，查看请求 URL、请求头和响应 JSON。

## 填写字段

### `.env`

从登录接口请求 URL 获取：

```text
deviceId=...
deviceType=IOS 或 ANDROID
appVersion=...
```

填入：

```env
LYNKCO_DEVICE_ID=登录接口 URL 里的 deviceId
LYNKCO_DEVICE_TYPE=IOS 或 ANDROID
LYNKCO_APP_VERSION=登录接口 URL 里的 appVersion
```

从登录接口响应 JSON 获取：

```json
{
  "data": {
    "centerTokenDto": {
      "refreshToken": "bearer..."
    }
  }
}
```

填入：

```env
LYNKCO_REFRESH_TOKEN=bearer...
```

可选昵称：

```env
LYNKCO_ACCOUNT_NAME=
```

不填时脚本会尽量从接口返回中读取。

### `lynkco_private.py`

签名配置放在本地私有文件：

```bash
cp lynkco_private.example.py lynkco_private.py
```

Windows PowerShell：

```powershell
Copy-Item lynkco_private.example.py lynkco_private.py
```

从请求头中可看到：

```text
X-Ca-Key: ...
```

填入：

```python
SECRETS = {
    "LYNKCO_APP_CODE": "",
    "LYNKCO_CA_KEY": "请求头里的 X-Ca-Key",
    "LYNKCO_CA_SECRET": "",
}
```

`CA Secret` 不会出现在普通请求头或响应里，不能通过一次 Fiddler 抓包从 `X-Ca-Signature` 反推。已有签名配置时填入本地 `lynkco_private.py`。

## 验证

先检查账号状态：

```bash
python lynkco_auto.py --status-only
```

再运行每日任务：

```bash
python lynkco_auto.py
```

看到连续签到、补签卡、积分、能量体等摘要后，说明基础配置可用。

## 收尾

抓包完成后：

1. 关闭手机 Wi-Fi 代理。
2. 关闭 Fiddler HTTPS 解密。
3. 妥善保存 `.env` 和 `lynkco_private.py`。
4. 不要公开 Fiddler 抓包文件、截图、token、设备 ID 或签名配置。
