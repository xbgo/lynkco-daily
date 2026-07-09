#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cron: 0 10 * * *
new Env('领克每日任务')

作者：小八
抖音：小八的03
官网：https://xbcars.cn
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = Path(os.getenv("LYNKCO_RUNTIME_DIR", Path(__file__).resolve().parent / ".runtime"))
DAILY_SCRIPT = ROOT / "lynkco_daily.py"
AUTHOR_FOOTER = "作者：小八\n抖音：小八的03\n官网：https://xbcars.cn"


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def safe_name(value: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return value[:48] or fallback


def redact(text: str) -> str:
    patterns = [
        (re.compile(r"bearer[a-zA-Z0-9-]+", re.IGNORECASE), "bearer***"),
        (re.compile(r'("(?:token|refreshToken|refresh_token|deviceId|hardwareDeviceId)"\s*:\s*")[^"]+(")', re.IGNORECASE), r"\1***\2"),
        (re.compile(r"(LYNKCO_(?:TOKEN|REFRESH_TOKEN|DEVICE_ID|HARDWARE_DEVICE_ID|CA_SECRET)=)[^\s]+", re.IGNORECASE), r"\1***"),
    ]
    for pattern, replacement in patterns:
        text = pattern.sub(replacement, text)
    return text


def clip(text: str, limit: int = 3800) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 80)] + "\n\n... 输出过长，已截断 ..."


def clean_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"none", "null", "undefined"} else text


def parse_accounts() -> list[dict[str, Any]]:
    raw = os.getenv("LYNKCO_CONFIG", "").strip()
    if not raw:
        return [{"name": clean_text(os.getenv("LYNKCO_ACCOUNT_NAME", ""))}]

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LYNKCO_CONFIG must be JSON: {exc}") from exc

    if isinstance(parsed, dict) and isinstance(parsed.get("accounts"), list):
        parsed = parsed["accounts"]
    elif isinstance(parsed, dict):
        parsed = [parsed]

    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        raise RuntimeError("LYNKCO_CONFIG must be a JSON object/list or {'accounts': [...]}")

    return parsed


def apply_account_env(base_env: dict[str, str], account: dict[str, Any]) -> dict[str, str]:
    env = dict(base_env)
    mapping = {
        "appCode": "LYNKCO_APP_CODE",
        "caKey": "LYNKCO_CA_KEY",
        "caSecret": "LYNKCO_CA_SECRET",
        "token": "LYNKCO_TOKEN",
        "refreshToken": "LYNKCO_REFRESH_TOKEN",
        "deviceId": "LYNKCO_DEVICE_ID",
        "deviceType": "LYNKCO_DEVICE_TYPE",
        "appVersion": "LYNKCO_APP_VERSION",
    }
    for key, env_key in mapping.items():
        value = account.get(key)
        if value is None:
            value = account.get(env_key)
        if value not in (None, ""):
            env[env_key] = str(value)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def run_account(index: int, account: dict[str, Any]) -> tuple[bool, str, str, float, str]:
    configured_name = clean_text(account.get("name") or account.get("remark"))
    label = configured_name or f"account{index}"
    file_key = safe_name(label, f"account{index}")
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    script_args = ["--latest-article"]
    extra_args = os.getenv("LYNKCO_QL_ARGS", "").strip()
    if extra_args:
        script_args.extend(shlex.split(extra_args))

    command = [
        sys.executable,
        str(DAILY_SCRIPT),
        "--token-file",
        str(RUNTIME_DIR / f"{file_key}_token.json"),
        "--device-file",
        str(RUNTIME_DIR / f"{file_key}_device.json"),
        *script_args,
    ]
    timeout = int(os.getenv("LYNKCO_QL_TIMEOUT", os.getenv("LYNKCO_AUTO_TIMEOUT", "180")))
    started = time.time()
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        env=apply_account_env(os.environ.copy(), account),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    elapsed = time.time() - started
    output = (proc.stdout or "") + ("\n[stderr]\n" + proc.stderr if proc.stderr else "")
    header = f"## {label}\n状态：{'成功' if proc.returncode == 0 else '失败'}，退出码：{proc.returncode}，耗时：{elapsed:.1f}s\n"
    return proc.returncode == 0, label, header + redact(output), elapsed, configured_name


def account_notice(name: str, output: str, ok: bool, elapsed: float, configured_name: str = "") -> str:
    sys.path.insert(0, str(ROOT))
    try:
        from lynkco_auto import build_user_summary

        body = build_user_summary(output, ok, elapsed, account_name=configured_name)
    except Exception:
        body = f"你好，{name}\n\n今天的领克任务{'已完成' if ok else '执行失败'}。"
    return body


def qinglong_notify(title: str, content: str) -> bool:
    if not env_bool("LYNKCO_QL_NOTIFY", True):
        return False

    for candidate in (Path.cwd(), Path("/ql/data/scripts"), Path("/ql/scripts")):
        if candidate.exists():
            sys.path.insert(0, str(candidate))

    try:
        from notify import send  # type: ignore

        send(title, content)
        return True
    except Exception as exc:
        print(f"[notify] 青龙 notify.py 不可用：{exc}", file=sys.stderr)
        return False


def fallback_notify(title: str, content: str, ok: bool) -> bool:
    sys.path.insert(0, str(ROOT))
    try:
        from lynkco_auto import send_notifications

        return bool(send_notifications(title, content, "成功" if ok else "失败"))
    except Exception as exc:
        print(f"[notify] 备用通知不可用：{exc}", file=sys.stderr)
        return False


def main() -> int:
    accounts = parse_accounts()
    results: list[tuple[bool, str, str, float, str]] = []
    for index, account in enumerate(accounts, start=1):
        name = clean_text(account.get("name") or account.get("remark")) or f"account{index}"
        configured_name = clean_text(account.get("name") or account.get("remark"))
        try:
            ok, name, output, elapsed, configured_name = run_account(index, account)
        except subprocess.TimeoutExpired as exc:
            ok = False
            elapsed = 0.0
            output = f"## {name}\n状态：失败，原因：超时\n{exc.stdout or ''}\n{exc.stderr or ''}"
        except Exception as exc:
            ok = False
            elapsed = 0.0
            output = f"## {name}\n状态：失败\n{exc}"
        results.append((ok, name, output, elapsed, configured_name))
        if env_bool("LYNKCO_QL_RAW_LOG"):
            print(output)
        else:
            print(f"## {name}\n{account_notice(name, output, ok, elapsed, configured_name)}\n")

    success_count = sum(1 for ok, _, _, _, _ in results if ok)
    all_ok = success_count == len(results)
    title = os.getenv("LYNKCO_NOTIFY_TITLE", "领克每日任务")
    title = f"{title}{'成功' if all_ok else '失败'} ({success_count}/{len(results)})"
    content = "\n\n".join(account_notice(name, output, ok, elapsed, configured_name) for ok, name, output, elapsed, configured_name in results)
    try:
        from lynkco_auto import fetch_hitokoto

        hitokoto = fetch_hitokoto()
    except Exception:
        hitokoto = ""
    if hitokoto:
        content += "\n\n今日一言：\n" + hitokoto
    content = clip(content + "\n\n" + AUTHOR_FOOTER, int(os.getenv("LYNKCO_QL_NOTIFY_LIMIT", "6000")))

    notify_on_success = env_bool("LYNKCO_NOTIFY_ON_SUCCESS", True)
    if (all_ok and notify_on_success) or not all_ok:
        if not qinglong_notify(title, content):
            fallback_notify(title, content, all_ok)

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
