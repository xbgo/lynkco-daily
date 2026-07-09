#!/usr/bin/env python3
"""
领克每日任务自动化入口。

加载 .env，执行每日任务，写入脱敏日志，并通过配置的渠道发送通知。

作者：小八
抖音：小八的03
官网：https://xbcars.cn
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DEFAULT_SCRIPT_ARGS = ["--latest-article"]
AUTHOR_FOOTER = "作者：小八\n抖音：小八的03\n官网：https://xbcars.cn"


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


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


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def redact(text: str) -> str:
    replacements = [
        (re.compile(r"bearer[a-zA-Z0-9-]+", re.IGNORECASE), "bearer***"),
        (re.compile(r'("(?:token|refreshToken|refresh_token|deviceId|hardwareDeviceId)"\s*:\s*")[^"]+(")', re.IGNORECASE), r"\1***\2"),
        (re.compile(r"(LYNKCO_(?:TOKEN|REFRESH_TOKEN|DEVICE_ID|HARDWARE_DEVICE_ID|CA_SECRET)=)[^\s]+", re.IGNORECASE), r"\1***"),
    ]
    redacted = text
    for pattern, replacement in replacements:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def clip(text: str, limit: int = 3500) -> str:
    if len(text) <= limit:
        return text
    keep = max(0, limit - 80)
    return text[:keep] + "\n\n... 输出过长，已截断 ..."


def display_value(value: object, suffix: str = "") -> str:
    if value in (None, ""):
        return "未知"
    return f"{value}{suffix}"


def clean_text(value: object) -> str:
    if value in (None, ""):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"none", "null", "undefined"} else text


def account_display_name(account: dict[str, object], configured_name: str = "") -> str:
    return clean_text(configured_name) or clean_text(account.get("accountName")) or "车友"


def extract_json_sections(text: str) -> dict[str, dict[str, object]]:
    sections: dict[str, dict[str, object]] = {}
    decoder = json.JSONDecoder()
    for match in re.finditer(r"^\[([^\]]+)\]\s*$", text, re.MULTILINE):
        label = match.group(1)
        rest = text[match.end() :].lstrip()
        if not rest.startswith("{"):
            continue
        try:
            value, _ = decoder.raw_decode(rest)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            sections[label] = value
    return sections


def result_text(value: object) -> str:
    if not isinstance(value, dict):
        return "未知"
    code = str(value.get("code") or "")
    message = str(value.get("message") or value.get("msg") or "")
    success = value.get("success")
    data = value.get("data")
    if isinstance(data, dict) and data.get("todayFirstSign") is False:
        return "今日已签到"
    ok = code in {"success", "200"} or success is True
    if ok:
        return "成功"
    normalized = f"{code} {message}".lower()
    repeated_markers = ("已签到", "重复", "已完成", "今日已", "不能重复", "already", "repeat", "duplicate")
    if any(marker in normalized for marker in repeated_markers):
        return "已完成"
    return f"失败（{message or code or '未知'}）"


def share_result_text(value: object, view_value: object | None = None) -> str:
    status = result_text(value)
    view_status = result_text(view_value) if view_value is not None else ""
    if status == "成功":
        if view_value is not None and view_status not in {"成功", "已完成"}:
            return "成功（等待分享浏览完成）"
        return "成功（预计 +5 积分）"
    if status == "已完成":
        return "已完成（今日分享积分可能已领取）"
    return status


def fetch_hitokoto() -> str:
    if not env_bool("LYNKCO_HITOKOTO", True):
        return ""

    url = os.getenv("LYNKCO_HITOKOTO_URL", "https://v1.hitokoto.cn/?encode=json&charset=utf-8").strip()
    if not url:
        return ""

    try:
        raw = http_request(
            url,
            headers={"User-Agent": "Mozilla/5.0 lynkco-daily"},
            method="GET",
            timeout=int(os.getenv("LYNKCO_HITOKOTO_TIMEOUT", "2")),
        )
        data = json.loads(raw)
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return ""

    if not isinstance(data, dict):
        return ""

    text = str(data.get("hitokoto") or "").strip()
    if not text:
        return ""

    sources = []
    for key in ("from_who", "from"):
        value = str(data.get(key) or "").strip()
        if value and value not in sources:
            sources.append(value)

    if sources:
        return f"「{text}」\n出处：{' / '.join(sources)}"
    return f"「{text}」"


def build_user_summary(
    output: str,
    ok: bool,
    elapsed: float,
    account_name: str = "",
    hitokoto: str = "",
    headline: str = "",
) -> str:
    sections = extract_json_sections(output)
    account = sections.get("account_summary", {})
    sign_in = sections.get("sign_in")
    share_report = sections.get("share_report")
    share_code_report = sections.get("share_code_report")
    latest_article = sections.get("latest_article", {})
    display_name = account_display_name(account, account_name)

    lines = [
        f"你好，{display_name}",
        "",
        headline or f"今天的领克任务{'已完成' if ok else '执行失败'}。",
    ]
    task_lines = []
    if sign_in is not None:
        task_lines.append(f"签到：{result_text(sign_in)}")
    if share_report is not None:
        task_lines.append(f"分享：{share_result_text(share_report, share_code_report)}")
    if share_code_report is not None:
        task_lines.append(f"分享浏览：{result_text(share_code_report)}")
    if task_lines:
        lines.extend(["", *task_lines])
    if not ok:
        reason = extract_failure_reason(output)
        if reason:
            lines.extend(["", f"失败原因：{reason}"])

    lines.extend(
        [
            "",
            f"连续签到：{display_value(account.get('continueDays'), ' 天')}",
            f"补签卡：{display_value(account.get('signCardNumber'), ' 张')}",
            f"当前积分：{display_value(account.get('points'))}",
            f"当前能量体：{display_value(account.get('energy'))}",
        ]
    )

    title = latest_article.get("title")
    if title:
        lines.append(f"分享文章：{title}")

    lines.append(f"耗时：{elapsed:.1f}s")

    if hitokoto:
        lines.extend(["", "今日一言：", hitokoto])

    return "\n".join(lines)


def extract_failure_reason(output: str) -> str:
    candidates = []
    for line in output.splitlines():
        text = line.strip()
        if not text or text in {"[stderr]", "{", "}"}:
            continue
        if text.startswith(("[", '"', "}", "{")):
            continue
        candidates.append(text)
    if not candidates:
        return ""
    return clip(candidates[-1], 180).replace("\n", " ")


def build_display_message(title: str, content: str, log_file: Path | None = None) -> str:
    lines = [title, "", content, "", AUTHOR_FOOTER]
    if log_file is not None:
        lines.extend(["", f"原始日志已保存：{log_file}"])
    return "\n".join(lines)


def http_request(url: str, data: bytes | None = None, headers: dict[str, str] | None = None, method: str = "POST", timeout: int = 15) -> str:
    req = Request(url, data=data, headers=headers or {}, method=method)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def post_json(url: str, payload: dict[str, object]) -> str:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return http_request(url, body, {"Content-Type": "application/json"})


def post_form(url: str, payload: dict[str, str]) -> str:
    body = urlencode(payload).encode("utf-8")
    return http_request(url, body, {"Content-Type": "application/x-www-form-urlencoded"})


def send_notifications(title: str, content: str, status: str) -> list[str]:
    sent: list[str] = []
    errors: list[str] = []

    pushplus_token = os.getenv("LYNKCO_PUSHPLUS_TOKEN", "").strip()
    if pushplus_token:
        try:
            post_json(
                "https://www.pushplus.plus/send",
                {"token": pushplus_token, "title": title, "content": content, "template": "markdown"},
            )
            sent.append("pushplus")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            errors.append(f"pushplus: {exc}")

    serverchan_sendkey = os.getenv("LYNKCO_SERVERCHAN_SENDKEY", "").strip()
    if serverchan_sendkey:
        try:
            post_form(f"https://sctapi.ftqq.com/{quote(serverchan_sendkey, safe='')}.send", {"title": title, "desp": content})
            sent.append("serverchan")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            errors.append(f"serverchan: {exc}")

    bark_url = os.getenv("LYNKCO_BARK_URL", "").strip().rstrip("/")
    if bark_url:
        try:
            url = f"{bark_url}/{quote(title, safe='')}/{quote(clip(content, 2500), safe='')}"
            http_request(url, method="GET")
            sent.append("bark")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            errors.append(f"bark: {exc}")

    webhook = os.getenv("LYNKCO_NOTIFY_WEBHOOK", "").strip()
    if webhook:
        try:
            post_json(webhook, {"title": title, "content": content, "status": status})
            sent.append("webhook")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            errors.append(f"webhook: {exc}")

    for error in errors:
        print(f"[notify] {error}", file=sys.stderr)
    return sent


def should_try_notify(args: argparse.Namespace) -> bool:
    return args.notify or env_bool("LYNKCO_NOTIFY")


def write_log(text: str) -> Path:
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / (time.strftime("%Y-%m-%d") + ".log")
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write("\n" + "=" * 80 + "\n")
        fh.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
        fh.write(text.rstrip() + "\n")
    return log_file


def run_daily(script_args: list[str], timeout: int, env_overrides: dict[str, str] | None = None) -> tuple[int, str, float]:
    command = [sys.executable, str(ROOT / "lynkco_daily.py"), *script_args]
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if env_overrides:
        env.update(env_overrides)
    started = time.time()
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    elapsed = time.time() - started
    output = (proc.stdout or "") + ("\n[stderr]\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, output, elapsed


def main() -> int:
    load_env_file(ROOT / ".env")

    parser = argparse.ArgumentParser(description="执行 lynkco_daily.py 并发送通知")
    parser.add_argument("--notify", action="store_true", help="即使未设置 LYNKCO_NOTIFY，也发送通知")
    parser.add_argument("--notify-on-success", action="store_true", default=env_bool("LYNKCO_NOTIFY_ON_SUCCESS", True))
    parser.add_argument("--notify-test", action="store_true", help="只发送一条测试通知，不执行签到和分享")
    parser.add_argument("--status-only", action="store_true", help="只读取账号状态，并输出用户可读摘要")
    parser.add_argument("--raw-output", action="store_true", help="打印 lynkco_daily.py 原始输出")
    parser.add_argument("--timeout", type=int, default=int(os.getenv("LYNKCO_AUTO_TIMEOUT", "180")))
    parser.add_argument("script_args", nargs=argparse.REMAINDER, help="透传给 lynkco_daily.py 的参数，默认：--latest-article")
    args = parser.parse_args()

    if args.notify_test:
        title = os.getenv("LYNKCO_NOTIFY_TITLE", "领克每日任务")
        content = "\n".join(
            [
                "你好，车友",
                "",
                "这是一条通知测试。收到这条消息，说明通知渠道配置正常。",
                "",
                "后续每日任务会推送连续签到、补签卡、当前积分、当前能量体和分享结果。",
            ]
        )
        hitokoto = fetch_hitokoto()
        if hitokoto:
            content += "\n\n今日一言：\n" + hitokoto
        print(build_display_message(f"{title}测试", content))
        sent = send_notifications(f"{title}测试", content + "\n\n" + AUTHOR_FOOTER, "测试")
        if sent:
            print(f"\n通知渠道：{', '.join(sent)}")
            return 0
        print("\n通知发送失败：未配置通知渠道，或所有通知渠道都发送失败。", file=sys.stderr)
        return 2

    script_args = args.script_args
    if script_args and script_args[0] == "--":
        script_args = script_args[1:]
    if args.status_only:
        script_args = ["--status"]
    if not script_args:
        script_args = DEFAULT_SCRIPT_ARGS

    try:
        env_overrides = {"LYNKCO_LATEST_ARTICLE": "0"} if args.status_only else None
        code, raw_output, elapsed = run_daily(script_args, args.timeout, env_overrides=env_overrides)
    except subprocess.TimeoutExpired as exc:
        code = 124
        elapsed = args.timeout
        raw_output = f"任务超时：{args.timeout}s\n{exc.stdout or ''}\n{exc.stderr or ''}"

    output = redact(raw_output)
    log_file = write_log(output)

    ok = code == 0
    status = "成功" if ok else "失败"
    title = os.getenv("LYNKCO_NOTIFY_TITLE", "领克每日任务")
    title = f"{title}{'状态' if args.status_only else ('成功' if ok else '失败')}"
    account_name = clean_text(os.getenv("LYNKCO_ACCOUNT_NAME", ""))
    should_send = False if args.status_only else should_try_notify(args) and ((ok and args.notify_on_success) or not ok)
    hitokoto = fetch_hitokoto()
    headline = f"当前账户状态{'读取成功' if ok else '读取失败'}。" if args.status_only else ""
    content = build_user_summary(output, ok, elapsed, account_name=account_name, hitokoto=hitokoto, headline=headline)

    if args.raw_output:
        print(output, end="" if output.endswith("\n") else "\n")
    else:
        print(build_display_message(title, content, log_file))

    if should_send:
        sent = send_notifications(title, content + "\n\n" + AUTHOR_FOOTER, status)
        if sent:
            print(f"\n通知渠道：{', '.join(sent)}")
        else:
            print("\n通知发送失败：未配置通知渠道，或所有通知渠道都发送失败。", file=sys.stderr)

    return code


if __name__ == "__main__":
    raise SystemExit(main())
