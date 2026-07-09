#!/usr/bin/env python3
"""
领克 App 每日签到和分享脚本。

请仅用于你自己的账号。脚本会复用 refresh token 和设备信息，刷新 access token 后执行签到和分享。

作者：小八
抖音：小八的03
官网：https://xbcars.cn
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from lynkco_paths import APP_ROOT


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_private_config() -> None:
    private_path = APP_ROOT / "lynkco_private.py"
    if private_path.exists():
        spec = importlib.util.spec_from_file_location("lynkco_private", private_path)
        if spec is None or spec.loader is None:
            return
        lynkco_private = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lynkco_private)
    else:
        try:
            import lynkco_private  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            return

    mapping = {
        "LYNKCO_APP_CODE": ("LYNKCO_APP_CODE", "APP_CODE"),
        "LYNKCO_CA_KEY": ("LYNKCO_CA_KEY", "CA_KEY"),
        "LYNKCO_CA_SECRET": ("LYNKCO_CA_SECRET", "CA_SECRET"),
    }
    private_values = getattr(lynkco_private, "SECRETS", {})
    for env_name, attr_names in mapping.items():
        if os.getenv(env_name):
            continue
        value = private_values.get(env_name) if isinstance(private_values, dict) else None
        for attr_name in attr_names:
            value = value or getattr(lynkco_private, attr_name, "")
        if value:
            os.environ[env_name] = str(value)


def normalize_config_value(value: str) -> str:
    """兼容误填的 b"..."、引号和首尾空白。"""
    value = str(value or "").strip()
    if len(value) >= 3 and value[0] in "bB" and value[1] in {"'", '"'} and value[-1] == value[1]:
        value = value[2:-1].strip()
    if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
        value = value[1:-1].strip()
    return value


load_env_file(APP_ROOT / ".env")
load_private_config()


API_BASE = "https://app-api-gw-toc.lynkco.com"
SERVICE_BASE = "https://app-services.lynkco.com.cn"
APP_CODE = normalize_config_value(os.getenv("LYNKCO_APP_CODE", ""))
CA_KEY = normalize_config_value(os.getenv("LYNKCO_CA_KEY", ""))
CA_SECRET = normalize_config_value(os.getenv("LYNKCO_CA_SECRET", "")).encode("utf-8")
SIGN_HEADERS = "X-Ca-Key,X-Ca-Timestamp,X-Ca-Nonce,X-Ca-Signature-Method"
DEFAULT_TOKEN_FILE = APP_ROOT / "lynkco_token.json"
DEFAULT_DEVICE_FILE = APP_ROOT / "lynkco_device.json"
TOKEN_CACHE_KEYS = ("token", "refreshToken", "accountName")


def _uuid4_like() -> str:
    chars = []
    for ch in "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx":
        if ch == "x":
            chars.append(random.choice("0123456789abcdef"))
        elif ch == "y":
            chars.append(random.choice("89ab"))
        else:
            chars.append(ch)
    return "".join(chars)


def _header_get(headers: dict[str, str], name: str) -> str | None:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


def _canonical_url(path: str, headers: dict[str, str], data: dict[str, Any] | None) -> str:
    split = urlsplit(path)
    params: dict[str, str] = {}

    content_type = _header_get(headers, "content-type") or ""
    if content_type.lower().startswith("application/x-www-form-urlencoded") and data:
        for key, value in data.items():
            params[str(key)] = "" if value is None else str(value)

    for key, value in parse_qsl(split.query, keep_blank_values=True):
        params[key] = value

    if not params:
        return split.path

    items = []
    for key in sorted(params):
        value = params[key]
        items.append(key if value == "" else f"{key}={value}")
    return f"{split.path}?{'&'.join(items)}"


def build_signature_headers(method: str, path: str, headers: dict[str, str], data: dict[str, Any] | None) -> dict[str, str]:
    if not CA_KEY or not CA_SECRET:
        raise RuntimeError("missing LYNKCO_CA_KEY or LYNKCO_CA_SECRET")

    accept = _header_get(headers, "accept") or "*/*"
    content_type = _header_get(headers, "content-type") or "application/json"
    nonce = _uuid4_like()
    timestamp = str(int(time.time() * 1000))

    ca_headers = {
        "X-Ca-Key": CA_KEY,
        "X-Ca-Nonce": nonce,
        "X-Ca-Signature-Method": "HmacSHA256",
        "X-Ca-Timestamp": timestamp,
    }
    canonical = [
        method.upper(),
        accept,
        "",
        content_type,
        "",
    ]
    canonical.extend(f"{key}:{value}" for key, value in ca_headers.items())
    canonical.append(_canonical_url(path, headers, data))
    payload = "\n".join(canonical).encode("utf-8")
    digest = base64.b64encode(hmac.new(CA_SECRET, payload, hashlib.sha256).digest()).decode("ascii")

    return {
        **ca_headers,
        "X-Ca-Signature-Headers": SIGN_HEADERS,
        "X-Ca-Signature": digest,
        "Accept": accept,
        "Content-Type": content_type,
    }


def mask_secret(value: str, keep: int = 6) -> str:
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}...{value[-keep:]}"


def clean_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"none", "null", "undefined"} else text


def load_token_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read token file {path}: {exc}") from exc


def save_token_file(path: Path, token: str = "", refresh_token: str = "", extra: dict[str, Any] | None = None) -> None:
    loaded = load_token_file(path)
    current = {key: loaded[key] for key in TOKEN_CACHE_KEYS if loaded.get(key) not in (None, "")}
    if token:
        current["token"] = token
    if refresh_token:
        current["refreshToken"] = refresh_token
    if extra:
        account_name = clean_text(extra.get("accountName"))
        if account_name:
            current["accountName"] = account_name
    current["updatedAt"] = int(time.time())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(current, fh, ensure_ascii=False, indent=2)


def save_json_file(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False, indent=2)


def load_device_profile(path: Path) -> dict[str, Any]:
    return load_token_file(path)


def save_device_profile(path: Path, profile: dict[str, Any]) -> dict[str, Any]:
    clean = {key: value for key, value in profile.items() if value not in (None, "")}
    clean["updatedAt"] = int(time.time())
    save_json_file(path, clean)
    return clean


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _adb_shell(args: list[str], serial: str = "") -> str:
    adb = shutil.which("adb")
    if not adb:
        raise RuntimeError("adb not found in PATH")
    cmd = [adb]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(["shell", *args])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(detail or f"adb exited with {proc.returncode}")
    return proc.stdout.strip()


def capture_android_device_profile(serial: str = "", use_android_id_as_device_id: bool = False) -> dict[str, Any]:
    props = {
        "brand": _adb_shell(["getprop", "ro.product.brand"], serial),
        "manufacturer": _adb_shell(["getprop", "ro.product.manufacturer"], serial),
        "deviceModel": _adb_shell(["getprop", "ro.product.model"], serial),
        "productDevice": _adb_shell(["getprop", "ro.product.device"], serial),
        "osVersion": _adb_shell(["getprop", "ro.build.version.release"], serial),
        "sdkInt": _adb_shell(["getprop", "ro.build.version.sdk"], serial),
        "androidId": _adb_shell(["settings", "get", "secure", "android_id"], serial),
    }
    profile = {
        "deviceType": "ANDROID",
        "deviceModel": props["deviceModel"] or props["productDevice"],
        "deviceBrand": props["brand"] or props["manufacturer"],
        "osVersion": props["osVersion"],
        "adbSerial": serial,
        "adbAndroidId": props["androidId"],
        "source": "adb",
    }
    if use_android_id_as_device_id and props["androidId"] and props["androidId"].lower() != "null":
        profile["deviceId"] = props["androidId"]
    return {key: value for key, value in profile.items() if value not in (None, "")}


def capture_device_profile_from_login_url(url: str) -> dict[str, Any]:
    params = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
    profile = {
        "deviceId": params.get("deviceId", ""),
        "deviceType": params.get("deviceType", ""),
        "deviceModel": params.get("deviceModel", ""),
        "hardwareDeviceId": params.get("hardwareDeviceId", ""),
        "appVersion": params.get("appVersion", ""),
        "source": "login_url",
    }
    return {key: value for key, value in profile.items() if value not in (None, "")}


def _profile_from_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    profile = {
        "deviceId": value.get("deviceId") or value.get("x-push-deviceId") or value.get("pushDeviceId") or "",
        "hardwareDeviceId": (
            value.get("hardwareDeviceId")
            or value.get("x-new-deviceId")
            or value.get("newDeviceId")
            or value.get("geelyDeviceId")
            or value.get("gl_dev_id")
            or ""
        ),
        "deviceType": value.get("deviceType") or value.get("platform") or value.get("publicPlatform") or "",
        "deviceModel": value.get("deviceModel") or value.get("model") or "",
        "appVersion": value.get("appVersion") or value.get("gl_app_version") or value.get("appVersionCode") or "",
    }
    return {key: str(item) for key, item in profile.items() if item not in (None, "")}


def _find_profile_in_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        direct = _profile_from_mapping(value)
        if direct.get("deviceId") or direct.get("hardwareDeviceId"):
            return direct
        for key in ("device", "deviceProfile", "profile", "rawEnvironment", "WXEnvironment", "weexEnv", "data"):
            found = _find_profile_in_json(value.get(key))
            if found:
                return found
        for item in value.values():
            found = _find_profile_in_json(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_profile_in_json(item)
            if found:
                return found
    return {}


def capture_device_profile_from_text(text: str) -> dict[str, Any]:
    raw = text.strip()
    profile: dict[str, Any] = {}

    if raw:
        try:
            loaded = json.loads(raw)
            profile.update(_find_profile_in_json(loaded))
        except json.JSONDecodeError:
            pass

    for match in re.finditer(r"https?://[^\s\"']+", raw):
        url_profile = capture_device_profile_from_login_url(match.group(0))
        profile.update({key: value for key, value in url_profile.items() if value})

    request_line = re.search(r"(?:GET|POST)\s+(/[^\s?]*\?[^\s]+)\s+HTTP/", raw, flags=re.IGNORECASE)
    if request_line:
        params = dict(parse_qsl(urlsplit(request_line.group(1)).query, keep_blank_values=True))
        profile.update({key: value for key, value in _profile_from_mapping(params).items() if value})

    headers: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key:
            headers[key] = value.strip()

    if headers:
        profile.update({key: value for key, value in _profile_from_mapping(headers).items() if value})
        if not profile.get("hardwareDeviceId"):
            gl_dev_id = _header_get(headers, "gl_dev_id")
            if gl_dev_id:
                profile["hardwareDeviceId"] = gl_dev_id
        sweet = _header_get(headers, "sweet_security_info")
        if sweet:
            try:
                sweet_profile = _profile_from_mapping(json.loads(sweet))
                profile.update({key: value for key, value in sweet_profile.items() if value})
            except json.JSONDecodeError:
                pass

    if profile.get("deviceType"):
        value = str(profile["deviceType"]).upper()
        if "IOS" in value:
            profile["deviceType"] = "IOS"
        elif "ANDROID" in value:
            profile["deviceType"] = "ANDROID"

    profile["source"] = "captured_text"
    return {key: value for key, value in profile.items() if value not in (None, "")}


def merge_device_profile(profile: dict[str, Any], args: argparse.Namespace) -> dict[str, str]:
    return {
        "deviceId": args.device_id or str(profile.get("deviceId") or ""),
        "deviceType": args.device_type or str(profile.get("deviceType") or "IOS"),
        "appVersion": args.app_version or str(profile.get("appVersion") or ""),
    }


def find_center_token_dto(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        dto = value.get("centerTokenDto")
        if isinstance(dto, dict):
            return dto
        for key in ("data", "result", "body"):
            found = find_center_token_dto(value.get(key))
            if found:
                return found
    return {}


ACCOUNT_NAME_NODES = ("centerUserInfoDto", "centerUserInfo", "userInfo", "user_info", "data", "result", "body")


def pick_account_name(value: dict[str, Any] | None) -> str:
    if not isinstance(value, dict):
        return ""
    text = clean_text(value.get("accountName") or value.get("displayName"))
    if text:
        return text
    for key in ACCOUNT_NAME_NODES:
        found = pick_account_name(value.get(key))
        if found:
            return found
    return ""


def extract_account_profile(response: dict[str, Any]) -> dict[str, Any]:
    account_name = pick_account_name(response)
    return {"accountName": account_name} if account_name else {}


def merge_account_profile(current: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    incoming_name = pick_account_name(response)
    if incoming_name:
        current["accountName"] = incoming_name
    return current


def extract_tokens(response: dict[str, Any]) -> tuple[str, str]:
    dto = find_center_token_dto(response)
    access_token = (
        dto.get("accessToken")
        or dto.get("token")
        or response.get("accessToken")
        or response.get("token")
        or ""
    )
    refresh_token = dto.get("refreshToken") or response.get("refreshToken") or ""
    return str(access_token or ""), str(refresh_token or "")


def extract_share_info_from_url(share_url: str) -> dict[str, str]:
    split = urlsplit(share_url)
    params = dict(parse_qsl(split.query, keep_blank_values=True))
    path = split.path

    first = ""
    if "/exploration/article/index" in path or "/shop-mall/lynk-shop-page/article/page-web" in path:
        first = "文章"
    elif "/dynamic/page-dynamic" in path:
        first = "动态"
    elif "/activityDetail/page-activityDetail" in path or "/shop-mall/lynk-shop-page/series/page-detail" in path:
        first = "活动"
    elif "/shop-mall/goods/page-info" in path:
        first = "商品"
    elif "/exploration/activity/page-special-info" in path:
        first = "专题"

    return {
        "businessNo": params.get("id") or params.get("dynamicId") or params.get("articleId") or params.get("goodId") or "",
        "firstClassification": first,
        "secondClassification": params.get("typeCode") or "",
        "shareCode": params.get("shareCode") or "",
    }


def build_article_share_url(article_id: str) -> str:
    route = f"lynkco://wx/?routeUrl=/pages/exploration/article/index.js?id={article_id}"
    return (
        "https://h5.lynkco.com/app-h5/dist/web/pages/exploration/article/index.html?"
        + urlencode({"id": article_id, "isShare": route})
    )


def share_content_type_from_url(share_url: str) -> int:
    path = urlsplit(share_url).path
    if "exploration/article/index" in path:
        return 1
    if "exploration/dynamic/page-dynamic" in path:
        return 2
    if "activity/activityDetail/page-activityDetail-web" in path or "activityDetail/page-activityDetail" in path:
        return 3
    if "club/partners/detail/index" in path:
        return 4
    if "shop-mall" in path:
        return 5
    if "couponCenter/page-detail" in path:
        return 7
    if "lynkco/lynk-fullcar/configuration/page-configurationDetails" in path:
        return 8
    if "exploration/activity/page-special-info" in path:
        return 10
    return 0


def coerce_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def format_timestamp_ms(value: Any) -> str:
    timestamp = coerce_int(value)
    if timestamp <= 0:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp / 1000))


def extract_article_candidates(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            article_id = item.get("articleId")
            content_type = str(item.get("contentType") or "")
            content_type_code = str(item.get("contentTypeCode") or "")
            if article_id and (content_type == "文章" or content_type_code == "article" or not content_type_code):
                article_id = str(article_id)
                if article_id not in seen:
                    seen.add(article_id)
                    found.append(dict(item))
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return found


def unwrap_article_detail(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]
    return data if isinstance(data, dict) else {}


def article_timestamp_ms(article: dict[str, Any]) -> int:
    for key in ("publishTime", "createdDate", "createdTime", "createTime", "updated", "updatedTime", "updateTime"):
        timestamp = coerce_int(article.get(key))
        if timestamp > 0:
            return timestamp
    return 0


def response_data(response: dict[str, Any]) -> Any:
    return response.get("data") if isinstance(response, dict) else None


@dataclass
class LynkClient:
    token: str = ""
    api_base: str = API_BASE
    verbose: bool = False

    def request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        token_required: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not APP_CODE:
            raise RuntimeError("missing LYNKCO_APP_CODE")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"APPCODE {APP_CODE}",
        }
        if token_required:
            headers["token"] = self.token
        if extra_headers:
            headers.update(extra_headers)

        headers.update(build_signature_headers(method, path, headers, data))
        body = None
        if method.upper() in {"POST", "PUT", "PATCH"}:
            body = json.dumps(data or {}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

        url = self.api_base.rstrip("/") + path
        if self.verbose:
            print(f"> {method.upper()} {url}")
            if data is not None:
                print(json.dumps(data, ensure_ascii=False))

        req = Request(url, data=body, headers=headers, method=method.upper())
        try:
            with urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {raw}") from exc
        except URLError as exc:
            raise RuntimeError(f"network error: {exc}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}

    def refresh_access_token(
        self,
        refresh_token: str,
        device_id: str = "",
        device_type: str = "ANDROID",
    ) -> dict[str, Any]:
        if not refresh_token:
            raise ValueError("refresh token is empty")

        paths: list[str] = []
        if device_id:
            paths.append(
                "/auth/login/refresh?"
                + urlencode(
                    {
                        "refreshToken": refresh_token,
                        "deviceId": device_id,
                        "deviceType": device_type or "ANDROID",
                    }
                )
            )
        paths.append("/auth/login/refresh?" + urlencode({"refreshToken": refresh_token}))

        errors: list[str] = []
        for base in (self.api_base, SERVICE_BASE):
            for path in paths:
                probe = LynkClient(token="", api_base=base, verbose=self.verbose)
                try:
                    response = probe.request("GET", path, token_required=False)
                except RuntimeError as exc:
                    errors.append(f"{base}{path}: {exc}")
                    continue
                access_token, new_refresh_token = extract_tokens(response)
                if access_token or new_refresh_token or response.get("code") == "success":
                    return response
                errors.append(f"{base}{path}: {json.dumps(response, ensure_ascii=False)[:500]}")

        raise RuntimeError("refresh token failed:\n" + "\n".join(errors[-4:]))

    def sign_in(self) -> dict[str, Any]:
        return self.request("POST", "/up/api/v1/user/sign", {})

    def sign_summary(self) -> dict[str, Any]:
        return self.request("GET", "/up/api/v1/userReward/getContinueDaysAndSignCard")

    def task_list(self) -> dict[str, Any]:
        return self.request("GET", "/up/api/v1/userReward/getTaskList")

    def point_balance(self) -> dict[str, Any]:
        return self.request("GET", "/app/energy/myEnergy")

    def energy_growth(self) -> dict[str, Any]:
        return self.request("GET", "/app/energy/my/growth")

    def user_info(self) -> dict[str, Any]:
        return LynkClient(token=self.token, api_base=SERVICE_BASE, verbose=self.verbose).request("GET", "/auth/user/info")

    def account_summary(
        self,
        sign_response: dict[str, Any] | None = None,
        account_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "accountName": pick_account_name(account_profile),
            "continueDays": "",
            "signCardNumber": "",
            "points": "",
            "energy": "",
        }

        try:
            sign_data = response_data(sign_response or self.sign_summary())
            if isinstance(sign_data, dict):
                summary["continueDays"] = sign_data.get("continueDays", "")
                summary["signCardNumber"] = sign_data.get("signCardNumber", "")
        except RuntimeError:
            pass

        try:
            point_data = response_data(self.point_balance())
            if isinstance(point_data, dict):
                summary["points"] = point_data.get("point", "")
        except RuntimeError:
            pass

        try:
            energy_data = response_data(self.energy_growth())
            if isinstance(energy_data, dict):
                level = energy_data.get("accountLevelVo")
                if isinstance(level, dict):
                    summary["energy"] = level.get("growth", "")
        except RuntimeError:
            pass

        return summary

    def square_index(self) -> dict[str, Any]:
        return self.request("POST", "/app/explore/home-page/square/index2", {})

    def article_detail(self, article_id: str) -> dict[str, Any]:
        if not article_id:
            raise ValueError("article_id is empty")
        return self.request("GET", f"/app/explore/home-page/article/content/{article_id}")

    def latest_article(self, detail_limit: int = 0) -> dict[str, Any]:
        feed = self.square_index()
        candidates = extract_article_candidates(feed)
        if not candidates:
            raise RuntimeError("no article candidates found in square feed")

        best: dict[str, Any] | None = None
        limit = max(0, min(detail_limit, len(candidates)))
        if limit == 0:
            best = dict(candidates[0])
            article_id = str(best.get("articleId") or "")
            best["articleId"] = article_id
            best["shareUrl"] = build_article_share_url(article_id)
            best["timestamp"] = article_timestamp_ms(best)
        else:
            for candidate in candidates[:limit]:
                article_id = str(candidate.get("articleId") or "")
                merged = dict(candidate)
                try:
                    detail = unwrap_article_detail(self.article_detail(article_id))
                    if detail:
                        merged.update(detail)
                except RuntimeError as exc:
                    merged["detailError"] = str(exc)

                merged["articleId"] = article_id
                merged["shareUrl"] = build_article_share_url(article_id)
                merged["timestamp"] = article_timestamp_ms(merged)
                if best is None or merged["timestamp"] > best.get("timestamp", 0):
                    best = merged

        if best is None:
            best = dict(candidates[0])
            article_id = str(best.get("articleId") or "")
            best["articleId"] = article_id
            best["shareUrl"] = build_article_share_url(article_id)
            best["timestamp"] = article_timestamp_ms(best)

        return {
            "articleId": str(best.get("articleId") or ""),
            "title": str(best.get("title") or ""),
            "publishTime": best.get("publishTime") or best.get("createdDate") or "",
            "publishTimeText": format_timestamp_ms(best.get("publishTime") or best.get("createdDate")),
            "shareUrl": str(best.get("shareUrl") or ""),
            "candidateCount": len(candidates),
            "checkedCount": limit,
        }

    def get_share_code(self, share_url: str, app_version: str = "4.2.3") -> dict[str, Any]:
        risk_request_info = {
            "openTimeStamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "shareContentType": share_content_type_from_url(share_url),
            "shareContentURL": share_url,
        }
        extra_headers = {
            "use_security": "true",
            "risk_type": "1",
            "appVersion": app_version or "4.2.3",
            "risk_request_info": json.dumps(risk_request_info, ensure_ascii=False, separators=(",", ":")),
        }
        return self.request("GET", "/app/v1/task/getShareCode", token_required=True, extra_headers=extra_headers)

    def report_share(
        self,
        business_no: str,
        first_classification: str = "文章",
        second_classification: str = "",
    ) -> dict[str, Any]:
        payload = {
            "businessNo": business_no,
            "eventData": {
                "firstClassification": first_classification,
                "secondClassification": second_classification,
            },
        }
        return self.request("POST", "/app/v1/task/reporting?type=99", payload)

    def report_share_code(
        self,
        share_code: str,
        business_no: str,
        first_classification: str = "文章",
        second_classification: str = "",
    ) -> dict[str, Any]:
        payload = {
            "businessNo": business_no,
            "eventData": {
                "firstClassification": first_classification,
                "secondClassification": second_classification,
            },
        }
        encoded_code = quote(share_code, safe="")
        return self.request("POST", f"/app/v1/task/shareReporting?shareCode={encoded_code}", payload, token_required=False)


def print_json(label: str, value: dict[str, Any]) -> None:
    print(f"\n[{label}]")
    print(json.dumps(value, ensure_ascii=False, indent=2))


def print_token_result(token_file: Path, access_token: str, refresh_token: str, show_secrets: bool = False) -> None:
    value = {
        "token_file": str(token_file),
        "token": access_token if show_secrets else mask_secret(access_token),
        "refreshToken": refresh_token if show_secrets else mask_secret(refresh_token),
    }
    print_json("token", value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Lynk & Co sign/share helper")
    parser.add_argument("--token", default=os.getenv("LYNKCO_TOKEN", ""), help="access token, or env LYNKCO_TOKEN")
    parser.add_argument("--refresh-token", default=os.getenv("LYNKCO_REFRESH_TOKEN", ""), help="refresh token, or env LYNKCO_REFRESH_TOKEN")
    parser.add_argument("--token-file", default=os.getenv("LYNKCO_TOKEN_FILE", str(DEFAULT_TOKEN_FILE)), help="local JSON token cache")
    parser.add_argument("--device-file", default=os.getenv("LYNKCO_DEVICE_FILE", str(DEFAULT_DEVICE_FILE)), help="local JSON device profile")
    parser.add_argument("--device-id", default=os.getenv("LYNKCO_DEVICE_ID", ""), help="app deviceId, usually x-push-deviceId")
    parser.add_argument("--device-type", default=os.getenv("LYNKCO_DEVICE_TYPE", ""), help="ANDROID/IOS/Web")
    parser.add_argument("--capture-device-from-url", default="", help="save device profile from a captured mobileCodeLogin URL")
    parser.add_argument("--auto-adb-device", action="store_true", help="read Android model/brand/os/android_id via adb")
    parser.add_argument("--adb-serial", default=os.getenv("LYNKCO_ADB_SERIAL", ""), help="adb serial when multiple devices are connected")
    parser.add_argument("--use-android-id-as-device-id", action="store_true", help="use adb android_id as deviceId when no app deviceId is known")
    parser.add_argument("--save-device-profile", action="store_true", help="save current device arguments/profile to --device-file")
    parser.add_argument("--print-device-profile", action="store_true", help="print effective device profile and exit")
    parser.add_argument("--app-version", default=os.getenv("LYNKCO_APP_VERSION", ""), help="app version sent to share risk headers")
    parser.add_argument("--capture-device-from-text", default="", help="save device profile from copied probe JSON or raw captured request text")
    parser.add_argument("--refresh-only", action="store_true", help="refresh token, save token file, then exit")
    parser.add_argument("--no-refresh", action="store_true", help="do not refresh before sign/share even if refresh token is available")
    parser.add_argument("--save-token", action="store_true", help="save provided --token/--refresh-token to token file")
    parser.add_argument("--show-secrets", action="store_true", help="print full tokens instead of masked tokens")
    parser.add_argument("--business-no", default=os.getenv("LYNKCO_BUSINESS_NO", ""), help="shared article/dynamic/activity id")
    parser.add_argument("--share-url", default=os.getenv("LYNKCO_SHARE_URL", ""), help="shared H5 URL; businessNo/shareCode can be parsed from it")
    parser.add_argument("--first", default=os.getenv("LYNKCO_FIRST_CLASSIFICATION", ""), help="文章/动态/活动/商品/专题, default inferred from --share-url or 文章")
    parser.add_argument("--second", default=os.getenv("LYNKCO_SECOND_CLASSIFICATION", ""), help="typeCode, optional")
    parser.add_argument("--share-code", default=os.getenv("LYNKCO_SHARE_CODE", ""), help="optional shareCode for shareReporting")
    parser.add_argument("--share-view-only", action="store_true", help="only run the shared-page shareReporting callback")
    parser.add_argument("--get-share-code-only", action="store_true", help="only call getShareCode for --share-url/--business-no")
    parser.add_argument("--latest-article", action="store_true", default=env_bool("LYNKCO_LATEST_ARTICLE"), help="auto-select newest article from community feed when no share target is set")
    parser.add_argument("--latest-article-only", action="store_true", help="print newest article from community feed, then exit")
    parser.add_argument("--latest-article-limit", type=int, default=env_int("LYNKCO_LATEST_ARTICLE_LIMIT", 0), help="max feed articles to detail-check for publishTime; 0 means use first feed item directly")
    parser.add_argument("--no-get-share-code", action="store_true", help="do not call getShareCode automatically")
    parser.add_argument("--skip-share", action="store_true", help="only sign in")
    parser.add_argument("--status", action="store_true", help="only read sign summary and task list")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    token_file = Path(args.token_file)
    device_file = Path(args.device_file)
    device_profile = load_device_profile(device_file)
    did_update_device_profile = False

    if args.capture_device_from_url:
        parsed_profile = capture_device_profile_from_login_url(args.capture_device_from_url)
        device_profile.update(parsed_profile)
        device_profile = save_device_profile(device_file, device_profile)
        did_update_device_profile = True

    if args.capture_device_from_text:
        parsed_profile = capture_device_profile_from_text(args.capture_device_from_text)
        device_profile.update(parsed_profile)
        device_profile = save_device_profile(device_file, device_profile)
        did_update_device_profile = True

    if args.auto_adb_device:
        try:
            adb_profile = capture_android_device_profile(args.adb_serial, args.use_android_id_as_device_id)
            device_profile.update(adb_profile)
            did_update_device_profile = True
        except RuntimeError as exc:
            print(f"auto adb device failed: {exc}", file=sys.stderr)

    effective_device = merge_device_profile(device_profile, args)
    if args.save_device_profile or did_update_device_profile:
        device_profile.update(effective_device)
        device_profile = save_device_profile(device_file, device_profile)

    if args.print_device_profile:
        print_json("device_profile", device_profile or effective_device)
        return 0

    if (args.capture_device_from_url or args.capture_device_from_text) and not any(
        [
            args.refresh_only,
            args.status,
            args.business_no,
            args.share_url,
            args.share_code,
            args.share_view_only,
            args.get_share_code_only,
            args.latest_article,
            args.latest_article_only,
            args.save_token,
        ]
    ):
        print_json("device_profile", device_profile)
        return 0

    saved = load_token_file(token_file)
    token = args.token or str(saved.get("token") or "")
    refresh_token = args.refresh_token or str(saved.get("refreshToken") or "")
    account_profile = extract_account_profile(saved)
    share_info = extract_share_info_from_url(args.share_url) if args.share_url else {}
    business_no = args.business_no or share_info.get("businessNo", "")
    first = args.first or share_info.get("firstClassification", "") or "文章"
    second = args.second or share_info.get("secondClassification", "")
    share_code = args.share_code or share_info.get("shareCode", "")
    share_url = args.share_url
    if not share_url and business_no and first == "文章":
        share_url = build_article_share_url(business_no)

    if args.save_token:
        save_token_file(token_file, token=token, refresh_token=refresh_token)
        print_token_result(token_file, token, refresh_token, args.show_secrets)

    if args.share_view_only:
        if not business_no or not share_code:
            print("Share view needs --share-url with shareCode, or both --business-no and --share-code.", file=sys.stderr)
            return 2
        share_client = LynkClient(token=token, verbose=args.verbose)
        print_json("share_code_report", share_client.report_share_code(share_code, business_no, first, second))
        return 0

    if refresh_token and (args.refresh_only or not args.no_refresh):
        refresh_client = LynkClient(verbose=args.verbose)
        refresh_response = refresh_client.refresh_access_token(refresh_token, effective_device["deviceId"], effective_device["deviceType"])
        new_token, new_refresh_token = extract_tokens(refresh_response)
        if not new_token:
            print_json("refresh_response", refresh_response)
            print("Refresh succeeded but no access token was found in response.", file=sys.stderr)
            return 1
        token = new_token
        refresh_token = new_refresh_token or refresh_token
        merge_account_profile(account_profile, refresh_response)
        save_token_file(token_file, token=token, refresh_token=refresh_token, extra=account_profile)
        print_token_result(token_file, token, refresh_token, args.show_secrets)

    if args.refresh_only:
        if not refresh_token:
            print("Missing refresh token. Set LYNKCO_REFRESH_TOKEN or pass --refresh-token.", file=sys.stderr)
            return 2
        return 0

    if not token:
        print("Missing token. Set LYNKCO_TOKEN/--token once, or set LYNKCO_REFRESH_TOKEN/--refresh-token.", file=sys.stderr)
        return 2

    client = LynkClient(token=token, verbose=args.verbose)
    if not pick_account_name(account_profile) and env_bool("LYNKCO_FETCH_ACCOUNT_NAME", True):
        try:
            merge_account_profile(account_profile, client.user_info())
        except RuntimeError:
            pass
        if pick_account_name(account_profile):
            save_token_file(token_file, token=token, refresh_token=refresh_token, extra=account_profile)

    if args.latest_article_only or (args.latest_article and not business_no and not share_url):
        latest_article = client.latest_article(args.latest_article_limit)
        print_json("latest_article", latest_article)
        if args.latest_article_only:
            return 0
        business_no = latest_article["articleId"]
        first = "文章"
        second = ""
        share_url = latest_article["shareUrl"]

    if args.get_share_code_only:
        if not share_url:
            print("getShareCode needs --share-url, or an article --business-no.", file=sys.stderr)
            return 2
        print_json("get_share_code", client.get_share_code(share_url, effective_device["appVersion"] or "4.2.3"))
        return 0

    if args.status:
        sign_summary_response = client.sign_summary()
        print_json("sign_summary", sign_summary_response)
        print_json("account_summary", client.account_summary(sign_summary_response, account_profile))
        print_json("task_list", client.task_list())
        return 0

    print_json("sign_in", client.sign_in())
    sign_summary_response = client.sign_summary()
    print_json("sign_summary", sign_summary_response)
    print_json("account_summary", client.account_summary(sign_summary_response, account_profile))

    if not args.skip_share:
        if not business_no:
            print("\n[share] skipped: pass --business-no/--share-url or set LYNKCO_BUSINESS_NO/LYNKCO_SHARE_URL")
        else:
            if not share_code and share_url and not args.no_get_share_code:
                share_code_response = client.get_share_code(share_url, effective_device["appVersion"] or "4.2.3")
                print_json("get_share_code", share_code_response)
                if share_code_response.get("code") == "success" and share_code_response.get("data"):
                    share_code = str(share_code_response["data"])
            print_json("share_report", client.report_share(business_no, first, second))
            if share_code:
                print_json("share_code_report", client.report_share_code(share_code, business_no, first, second))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
