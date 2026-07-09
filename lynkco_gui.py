#!/usr/bin/env python3
"""
领克每日任务桌面配置面板。

用于本地填写配置、运行测试、管理 Windows/macOS 定时任务和开机自启动。

作者：小八
抖音：小八的03
官网：https://xbcars.cn
"""

from __future__ import annotations

import os
import platform
import plistlib
import re
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox
from typing import Any

try:
    import customtkinter as ctk
except ModuleNotFoundError as exc:  # pragma: no cover - 给直接双击运行的用户看
    raise SystemExit("缺少图形界面依赖，请先执行：pip install -r requirements.txt") from exc

try:
    from PIL import Image
except ModuleNotFoundError:  # pragma: no cover
    Image = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
WINDOWS_DAILY_TASK = "LynkcoDaily"
WINDOWS_STARTUP_TASK = "LynkcoDailyStartup"
MACOS_DAILY_LABEL = "cn.xbcars.lynkco-daily"
MACOS_STARTUP_LABEL = "cn.xbcars.lynkco-daily.startup"
SUPPORT_QR = ROOT / "assets" / "zsm.png"

BG = "#eef3f4"
SURFACE = "#ffffff"
MUTED = "#6b7785"
TEXT = "#10202c"
GREEN = "#00a884"
GREEN_DARK = "#008f72"
BORDER = "#d9e3e8"
INPUT = "#f8fbfc"


# 字段元组：环境变量名、界面标题、是否密文显示、提示文案。
BASIC_FIELDS = [
    ("LYNKCO_REFRESH_TOKEN", "Refresh Token", True, "长期登录凭证。泄露后请及时修改密码并重新获取。"),
    ("LYNKCO_DEVICE_ID", "Device ID", True, "保持与当前 App 登录设备一致，减少被挤下线概率。"),
    ("LYNKCO_DEVICE_TYPE", "设备类型", False, "iPhone 填 IOS，安卓填 ANDROID。"),
    ("LYNKCO_APP_VERSION", "App 版本", False, "可选，例如 4.1.4；留空时分享接口默认使用 4.2.3。"),
    ("LYNKCO_ACCOUNT_NAME", "推送昵称", False, "可选。填写后推送优先显示这个名称，留空则使用接口返回名称。"),
]

NOTIFY_SWITCHES = [
    ("LYNKCO_NOTIFY", "开启通知", "关闭后不会主动发送通知，测试通知按钮除外。"),
    ("LYNKCO_NOTIFY_ON_SUCCESS", "成功也通知", "关闭后只在任务失败时通知。"),
    ("LYNKCO_HITOKOTO", "显示一言", "开启后推送末尾会附加一条免费一言。"),
]

NOTIFY_GENERAL_FIELDS = [
    ("LYNKCO_NOTIFY_TITLE", "通知标题", False, "推送标题前缀，例如：领克每日任务。"),
]

NOTIFY_CHANNELS = [
    (
        "PushPlus",
        "LYNKCO_PUSHPLUS_TOKEN",
        "Token",
        True,
        "登录 PushPlus 后，在一对一推送页面复制 token。只填 token，不要填完整 URL。",
        "https://www.pushplus.plus/",
    ),
    (
        "Server 酱",
        "LYNKCO_SERVERCHAN_SENDKEY",
        "SendKey",
        True,
        "登录 Server 酱 Turbo 后复制 SendKey。脚本会自动拼接 sctapi.ftqq.com 地址。",
        "https://sct.ftqq.com/",
    ),
    (
        "Bark",
        "LYNKCO_BARK_URL",
        "完整 URL",
        True,
        "iPhone 安装 Bark 后填完整推送前缀，例如：https://api.day.app/你的Key。",
        "https://bark.day.app/",
    ),
    (
        "通用 Webhook",
        "LYNKCO_NOTIFY_WEBHOOK",
        "Webhook URL",
        True,
        "自建服务填写接收地址。脚本会 POST JSON：title、content、status。",
        "",
    ),
]

ADVANCED_FIELDS = [
    ("LYNKCO_HITOKOTO_URL", "一言接口", False, "默认使用 https://v1.hitokoto.cn/?encode=json&charset=utf-8。"),
    ("LYNKCO_HITOKOTO_TIMEOUT", "一言超时", False, "单位秒，默认 2。接口超时会自动忽略，不影响签到。"),
    ("LYNKCO_AUTO_TIMEOUT", "任务超时", False, "单位秒，默认 180。网络慢可以适当调大。"),
    ("PYTHON_EXE", "Python 路径", False, "可选。留空时使用当前 Python；打包版通常不需要填。"),
]

MANAGED_KEYS = (
    {key for key, *_ in BASIC_FIELDS}
    | {key for key, *_ in NOTIFY_SWITCHES}
    | {key for key, *_ in NOTIFY_GENERAL_FIELDS}
    | {key for _, key, *_ in NOTIFY_CHANNELS}
    | {key for key, *_ in ADVANCED_FIELDS}
    | {
        "LYNKCO_LATEST_ARTICLE",
        "LYNKCO_LATEST_ARTICLE_LIMIT",
        "LYNKCO_SCHEDULE_TIME",
    }
)

SECRET_KEYS = {
    "LYNKCO_REFRESH_TOKEN",
    "LYNKCO_DEVICE_ID",
    "LYNKCO_PUSHPLUS_TOKEN",
    "LYNKCO_SERVERCHAN_SENDKEY",
    "LYNKCO_BARK_URL",
    "LYNKCO_NOTIFY_WEBHOOK",
}


def clean_env_value(value: str) -> str:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = clean_env_value(value)
    return values


def redact(text: str) -> str:
    patterns = [
        (re.compile(r"bearer[a-zA-Z0-9-]+", re.IGNORECASE), "bearer***"),
        (re.compile(r'("(?:token|refreshToken|deviceId)"\s*:\s*")[^"]+(")', re.IGNORECASE), r"\1***\2"),
        (
            re.compile(
                r"(LYNKCO_(?:TOKEN|REFRESH_TOKEN|DEVICE_ID|CA_SECRET|PUSHPLUS_TOKEN|SERVERCHAN_SENDKEY|BARK_URL|NOTIFY_WEBHOOK)=)[^\s]+",
                re.IGNORECASE,
            ),
            r"\1***",
        ),
    ]
    for pattern, replacement in patterns:
        text = pattern.sub(replacement, text)
    return text


def is_windows() -> bool:
    return platform.system().lower() == "windows"


def is_macos() -> bool:
    return platform.system().lower() == "darwin"


class LynkcoGui:
    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self.root.title("领克每日任务")
        self.root.geometry("980x720")
        self.root.minsize(780, 560)
        self.root.configure(fg_color=BG)

        self.values = {**read_env_file(ENV_EXAMPLE), **read_env_file(ENV_FILE)}
        self.entries: dict[str, Any] = {}
        self.bool_vars: dict[str, tk.BooleanVar] = {}
        self.secret_visible = tk.BooleanVar(value=False)
        self.daily_enabled = tk.BooleanVar(value=False)
        self.startup_enabled = tk.BooleanVar(value=False)
        hour, minute = self.time_parts(self.values.get("LYNKCO_SCHEDULE_TIME", "10:00"))
        self.hour_var = tk.StringVar(value=hour)
        self.minute_var = tk.StringVar(value=minute)
        self.output_var = tk.StringVar(value="就绪")
        self.support_popup_image: Any = None
        self.secret_button: ctk.CTkButton | None = None
        self.output: ctk.CTkTextbox | None = None

        self.build()
        self.refresh_switches()
        self.root.after(500, self.show_support_dialog)

    def build(self) -> None:
        shell = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        shell.pack(fill="both", expand=True, padx=18, pady=16)

        header = ctk.CTkFrame(shell, fg_color=SURFACE, corner_radius=8, border_width=1, border_color=BORDER)
        header.pack(fill="x", pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="ew", padx=18, pady=14)
        ctk.CTkLabel(title_box, text="领克每日任务", text_color=TEXT, font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(title_box, text="本地配置 / 一键运行 / 定时管理 / 通知测试", text_color=MUTED, font=ctk.CTkFont(size=13)).pack(anchor="w", pady=(3, 0))

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e", padx=18, pady=14)
        self.primary_button(actions, "运行一次", lambda: self.run_python(["lynkco_auto.py"])).pack(side="left", padx=(0, 8))
        self.secondary_button(actions, "查看状态", lambda: self.run_python(["lynkco_auto.py", "--status-only"])).pack(side="left", padx=(0, 8))
        self.secondary_button(actions, "保存配置", self.save_config).pack(side="left", padx=(0, 8))
        self.secret_button = self.secondary_button(actions, "显示密钥", self.toggle_secret)
        self.secret_button.pack(side="left")

        tabs = ctk.CTkTabview(
            shell,
            corner_radius=8,
            border_width=1,
            border_color=BORDER,
            fg_color=SURFACE,
            segmented_button_fg_color="#e7eef0",
            segmented_button_selected_color=GREEN,
            segmented_button_selected_hover_color=GREEN_DARK,
            segmented_button_unselected_color="#e7eef0",
            segmented_button_unselected_hover_color="#d8e5e6",
            text_color=TEXT,
            text_color_disabled=MUTED,
        )
        tabs.pack(fill="both", expand=True)

        basic_page = tabs.add("基础配置")
        notify_page = tabs.add("通知配置")
        automation_page = tabs.add("自动化")
        log_page = tabs.add("运行日志")

        self.add_basic_page(basic_page)
        self.add_notify_page(notify_page)
        self.add_automation_page(automation_page)
        self.add_output(log_page)
        self.tabs = tabs
        self.log_page_name = "运行日志"

    def primary_button(self, parent: tk.Widget, text: str, command) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            height=36,
            corner_radius=8,
            fg_color=GREEN,
            hover_color=GREEN_DARK,
            text_color="#ffffff",
            font=ctk.CTkFont(size=13, weight="bold"),
        )

    def secondary_button(self, parent: tk.Widget, text: str, command) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            height=36,
            corner_radius=8,
            fg_color="#f7fbfb",
            hover_color="#e8f2f1",
            text_color=TEXT,
            border_width=1,
            border_color=BORDER,
            font=ctk.CTkFont(size=13),
        )

    def ghost_button(self, parent: tk.Widget, text: str, command) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            height=32,
            corner_radius=8,
            fg_color="#edf8f6",
            hover_color="#d9efeb",
            text_color="#007966",
            font=ctk.CTkFont(size=12),
        )

    def scroll_page(self, parent: tk.Widget) -> ctk.CTkScrollableFrame:
        page = ctk.CTkScrollableFrame(parent, fg_color="transparent", corner_radius=0)
        page.pack(fill="both", expand=True, padx=12, pady=12)
        return page

    def card(self, parent: tk.Widget, title: str) -> ctk.CTkFrame:
        outer = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=8, border_width=1, border_color=BORDER)
        outer.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(outer, text=title, text_color=TEXT, font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=16, pady=(14, 8))
        return outer

    def add_basic_page(self, parent: tk.Widget) -> None:
        page = self.scroll_page(parent)
        self.add_field_card(page, "账号与设备", BASIC_FIELDS)
        self.add_safety_card(page)

    def add_notify_page(self, parent: tk.Widget) -> None:
        page = self.scroll_page(parent)
        self.add_notify_switch_card(page)
        self.add_field_card(page, "通知标题", NOTIFY_GENERAL_FIELDS)
        for title, key, label, secret, hint, url in NOTIFY_CHANNELS:
            self.add_channel_card(page, title, key, label, secret, hint, url)
        self.add_field_card(page, "一言与超时", ADVANCED_FIELDS)

    def add_automation_page(self, parent: tk.Widget) -> None:
        page = self.scroll_page(parent)
        self.add_switch_card(page)
        self.add_action_card(page)
        self.add_copyright_card(page)

    def add_entry_row(
        self,
        parent: tk.Widget,
        key: str,
        label: str,
        secret: bool,
        hint: str,
        values: list[str] | None = None,
    ) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 12))
        row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(row, text=label, text_color=TEXT, width=118, anchor="w", font=ctk.CTkFont(size=13)).grid(row=0, column=0, sticky="nw", pady=(7, 0))
        if values is not None:
            entry = ctk.CTkComboBox(
                row,
                values=values,
                height=36,
                corner_radius=8,
                border_width=1,
                border_color=BORDER,
                fg_color=INPUT,
                button_color="#dbe8e9",
                button_hover_color="#c9dcdd",
                dropdown_fg_color=SURFACE,
                text_color=TEXT,
            )
            entry.set(self.values.get(key, values[0]))
        else:
            entry = ctk.CTkEntry(
                row,
                height=36,
                corner_radius=8,
                border_width=1,
                border_color=BORDER,
                fg_color=INPUT,
                text_color=TEXT,
                show="*" if secret and not self.secret_visible.get() else "",
            )
            entry.insert(0, self.values.get(key, ""))
        entry.grid(row=0, column=1, sticky="ew")

        hint_label = ctk.CTkLabel(row, text=hint, text_color=MUTED, anchor="w", justify="left", wraplength=720, font=ctk.CTkFont(size=12))
        hint_label.grid(row=1, column=1, sticky="ew", pady=(4, 0))
        self.entries[key] = entry

    def add_field_card(self, parent: tk.Widget, title: str, fields: list[tuple[str, str, bool, str]]) -> None:
        frame = self.card(parent, title)
        for key, label, secret, hint in fields:
            choices = ["IOS", "ANDROID"] if key == "LYNKCO_DEVICE_TYPE" else None
            self.add_entry_row(frame, key, label, secret, hint, choices)

    def add_safety_card(self, parent: tk.Widget) -> None:
        frame = self.card(parent, "安全提醒")
        text = (
            "refreshToken 和 Device ID 都属于敏感信息。不要截图发群，不要提交到 GitHub；"
            "如果 refreshToken 泄露，请及时修改密码并重新获取。"
        )
        ctk.CTkLabel(frame, text=text, text_color=MUTED, justify="left", anchor="w", wraplength=820).pack(fill="x", padx=16, pady=(0, 16))

    def add_notify_switch_card(self, parent: tk.Widget) -> None:
        frame = self.card(parent, "通知开关")
        ctk.CTkLabel(
            frame,
            text="先打开“开启通知”，再在下面任选一个渠道填写。填完后点“测试通知”，不用等到第二天。",
            text_color=MUTED,
            justify="left",
            anchor="w",
            wraplength=820,
        ).pack(fill="x", padx=16, pady=(0, 10))

        for key, label, hint in NOTIFY_SWITCHES:
            value = self.values.get(key, "0").strip().lower() in {"1", "true", "yes", "on"}
            var = tk.BooleanVar(value=value)
            self.bool_vars[key] = var
            item = ctk.CTkFrame(frame, fg_color="#f8fbfc", corner_radius=8, border_width=1, border_color="#e8eef2")
            item.pack(fill="x", padx=16, pady=(0, 10))
            item.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(item, text=label, text_color=TEXT, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
            ctk.CTkLabel(item, text=hint, text_color=MUTED, anchor="w", justify="left", wraplength=690).grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 10))
            ctk.CTkSwitch(item, text="", variable=var, progress_color=GREEN, button_color="#ffffff", button_hover_color="#f4f7f8").grid(row=0, column=1, rowspan=2, sticky="e", padx=12, pady=10)

    def add_channel_card(self, parent: tk.Widget, title: str, key: str, label: str, secret: bool, hint: str, url: str) -> None:
        frame = self.card(parent, title)
        self.add_entry_row(frame, key, label, secret, hint)
        footer = ctk.CTkFrame(frame, fg_color="transparent")
        footer.pack(fill="x", padx=16, pady=(0, 14))
        if url:
            self.ghost_button(footer, f"打开 {title}", lambda target=url: self.open_url(target)).pack(side="left")
        ctk.CTkLabel(footer, text="配置后可在“自动化”页点击“测试通知”。", text_color=MUTED, font=ctk.CTkFont(size=12)).pack(side="left", padx=(10, 0))

    def add_switch_card(self, parent: tk.Widget) -> None:
        frame = self.card(parent, "自动化开关")
        time_row = ctk.CTkFrame(frame, fg_color="#f8fbfc", corner_radius=8, border_width=1, border_color="#e8eef2")
        time_row.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(time_row, text="每日执行时间", text_color=TEXT, font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=12, pady=(12, 6))

        picker = ctk.CTkFrame(time_row, fg_color="transparent")
        picker.pack(anchor="w", padx=12, pady=(0, 12))
        hours = [f"{value:02d}" for value in range(24)]
        minutes = [f"{value:02d}" for value in range(60)]
        ctk.CTkOptionMenu(picker, values=hours, variable=self.hour_var, width=84, height=34, corner_radius=8, fg_color=GREEN, button_color=GREEN_DARK, button_hover_color="#00785f").pack(side="left")
        ctk.CTkLabel(picker, text=":", text_color=TEXT, font=ctk.CTkFont(size=17, weight="bold")).pack(side="left", padx=8)
        ctk.CTkOptionMenu(picker, values=minutes, variable=self.minute_var, width=84, height=34, corner_radius=8, fg_color=GREEN, button_color=GREEN_DARK, button_hover_color="#00785f").pack(side="left")

        self.add_schedule_switch(frame, "每日定时执行", "Windows 使用计划任务；macOS 使用 launchd。", self.daily_enabled, self.toggle_daily)
        self.add_schedule_switch(frame, "开机登录后执行一次", "登录系统后自动跑一次，用于补偿电脑关机错过的每日任务。", self.startup_enabled, self.toggle_startup)
        ctk.CTkLabel(frame, text="修改执行时间后，重新开启“每日定时执行”即可生效。", text_color=MUTED, anchor="w").pack(fill="x", padx=16, pady=(0, 14))

    def add_schedule_switch(self, parent: tk.Widget, label: str, hint: str, variable: tk.BooleanVar, command) -> None:
        row = ctk.CTkFrame(parent, fg_color="#f8fbfc", corner_radius=8, border_width=1, border_color="#e8eef2")
        row.pack(fill="x", padx=16, pady=(0, 10))
        row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(row, text=label, text_color=TEXT, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        ctk.CTkLabel(row, text=hint, text_color=MUTED, anchor="w", wraplength=680).grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 10))
        switch = ctk.CTkSwitch(row, text="", variable=variable, command=command, progress_color=GREEN, button_color="#ffffff", button_hover_color="#f4f7f8")
        switch.grid(row=0, column=1, rowspan=2, sticky="e", padx=12, pady=10)

    def add_action_card(self, parent: tk.Widget) -> None:
        frame = self.card(parent, "操作")
        grid = ctk.CTkFrame(frame, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=(0, 16))
        grid.grid_columnconfigure((0, 1), weight=1)
        self.primary_button(grid, "运行一次", lambda: self.run_python(["lynkco_auto.py"])).grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 10))
        self.secondary_button(grid, "查看状态", lambda: self.run_python(["lynkco_auto.py", "--status-only"])).grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=(0, 10))
        self.secondary_button(grid, "测试通知", self.test_notification).grid(row=1, column=0, sticky="ew", padx=(0, 6))
        self.secondary_button(grid, "打开项目目录", self.open_folder).grid(row=1, column=1, sticky="ew", padx=(6, 0))

    def add_copyright_card(self, parent: tk.Widget) -> None:
        frame = self.card(parent, "版权信息")
        items = [
            "作者：小八",
            "抖音：小八的03",
            "官网：https://xbcars.cn",
            "License：MIT",
            "本脚本仅供学习交流使用，请勿用于商业用途。",
            "使用本脚本所造成的一切后果，与作者无关。",
            "请遵守相关法律法规，不得用于非法用途。",
            "非官方项目，仅供学习研究和个人自动化使用。",
        ]
        for item in items:
            ctk.CTkLabel(frame, text=item, text_color=MUTED, anchor="w", justify="left", wraplength=820).pack(fill="x", padx=16, pady=2)
        self.secondary_button(frame, "查看赞赏码", self.show_support_dialog).pack(fill="x", padx=16, pady=(12, 16))

    def add_output(self, parent: tk.Widget) -> None:
        frame = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=8, border_width=1, border_color=BORDER)
        frame.pack(fill="both", expand=True, padx=12, pady=12)
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(top, text="运行日志", text_color=TEXT, font=ctk.CTkFont(size=15, weight="bold")).pack(side="left")
        ctk.CTkLabel(top, textvariable=self.output_var, text_color=GREEN).pack(side="right")
        self.output = ctk.CTkTextbox(
            frame,
            fg_color="#f8fbfc",
            text_color=TEXT,
            corner_radius=8,
            border_width=1,
            border_color="#e0eaee",
            wrap="word",
            font=ctk.CTkFont(size=14),
        )
        self.output.pack(fill="both", expand=True, padx=14, pady=(0, 14))

    def show_support_dialog(self) -> None:
        if not SUPPORT_QR.exists():
            return

        dialog = ctk.CTkToplevel(self.root)
        dialog.title("赞赏支持")
        dialog.configure(fg_color=SURFACE)
        dialog.resizable(False, False)
        dialog.transient(self.root)

        ctk.CTkLabel(dialog, text="感谢支持", text_color=TEXT, font=ctk.CTkFont(size=20, weight="bold")).pack(padx=22, pady=(18, 6))
        ctk.CTkLabel(dialog, text="觉得好用可以随缘支持。", text_color=MUTED, font=ctk.CTkFont(size=13)).pack(padx=22, pady=(0, 12))

        if Image is not None:
            try:
                image = Image.open(SUPPORT_QR)
                max_size = 420
                scale = min(max_size / image.width, max_size / image.height, 1)
                size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
                self.support_popup_image = ctk.CTkImage(light_image=image, dark_image=image, size=size)
                ctk.CTkLabel(dialog, text="", image=self.support_popup_image).pack(padx=22, pady=(0, 16))
            except OSError:
                ctk.CTkLabel(dialog, text="赞赏码加载失败", text_color="#ef4444").pack(padx=22, pady=20)
        else:
            ctk.CTkLabel(dialog, text="缺少 Pillow，无法显示赞赏码。", text_color="#ef4444").pack(padx=22, pady=20)

        self.primary_button(dialog, "关闭", dialog.destroy).pack(padx=22, pady=(0, 18), fill="x")
        dialog.update_idletasks()
        x = self.root.winfo_x() + max(0, (self.root.winfo_width() - dialog.winfo_width()) // 2)
        y = self.root.winfo_y() + max(0, (self.root.winfo_height() - dialog.winfo_height()) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()

    @staticmethod
    def time_parts(value: str) -> tuple[str, str]:
        match = re.fullmatch(r"\s*([01]?\d|2[0-3]):([0-5]\d)\s*", value or "")
        if not match:
            return "10", "00"
        return f"{int(match.group(1)):02d}", f"{int(match.group(2)):02d}"

    def selected_time(self) -> str:
        hour, minute = self.time_parts(f"{self.hour_var.get()}:{self.minute_var.get()}")
        self.hour_var.set(hour)
        self.minute_var.set(minute)
        return f"{hour}:{minute}"

    def collect_values(self) -> dict[str, str]:
        values = dict(self.values)
        for key, entry in self.entries.items():
            values[key] = entry.get().strip()
        for key, var in self.bool_vars.items():
            values[key] = "1" if var.get() else "0"
        values.setdefault("LYNKCO_LATEST_ARTICLE", "1")
        values.setdefault("LYNKCO_LATEST_ARTICLE_LIMIT", "0")
        values["LYNKCO_SCHEDULE_TIME"] = self.selected_time()
        values.setdefault("LYNKCO_HITOKOTO_URL", "https://v1.hitokoto.cn/?encode=json&charset=utf-8")
        values.setdefault("LYNKCO_HITOKOTO_TIMEOUT", "2")
        values.setdefault("LYNKCO_AUTO_TIMEOUT", "180")
        return values

    def save_config(self) -> None:
        values = self.collect_values()
        lines = [
            "# 领克每日任务配置。不要提交这个文件。",
            "",
            "# 基础配置",
        ]
        for key, *_ in BASIC_FIELDS:
            lines.append(f"{key}={values.get(key, '')}")
        lines.extend(
            [
                "",
                "# 默认任务",
                "LYNKCO_LATEST_ARTICLE=1",
                "LYNKCO_LATEST_ARTICLE_LIMIT=0",
                f"LYNKCO_SCHEDULE_TIME={values['LYNKCO_SCHEDULE_TIME']}",
                "",
                "# 通知开关",
            ]
        )
        for key, *_ in NOTIFY_SWITCHES:
            lines.append(f"{key}={values.get(key, '0')}")
        lines.extend(["", "# 通知标题"])
        for key, *_ in NOTIFY_GENERAL_FIELDS:
            lines.append(f"{key}={values.get(key, '')}")
        lines.extend(["", "# 通知渠道。任选一个即可。"])
        for _, key, *_ in NOTIFY_CHANNELS:
            lines.append(f"{key}={values.get(key, '')}")
        lines.extend(["", "# 高级配置"])
        for key, *_ in ADVANCED_FIELDS:
            lines.append(f"{key}={values.get(key, '')}")
        for key, value in sorted(values.items()):
            if key not in MANAGED_KEYS and value:
                lines.append(f"{key}={value}")
        ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.values = values
        self.output_var.set("配置已保存")

    def toggle_secret(self) -> None:
        self.secret_visible.set(not self.secret_visible.get())
        for key, entry in self.entries.items():
            if key in SECRET_KEYS:
                entry.configure(show="" if self.secret_visible.get() else "*")
        if self.secret_button is not None:
            self.secret_button.configure(text="隐藏密钥" if self.secret_visible.get() else "显示密钥")

    def python_executable(self) -> str:
        return self.values.get("PYTHON_EXE") or sys.executable

    def append_output(self, text: str) -> None:
        if self.output is None:
            return
        self.output.insert("end", redact(text))
        self.output.see("end")

    def run_command(self, command: list[str]) -> None:
        self.save_config()
        if hasattr(self, "tabs"):
            self.tabs.set(self.log_page_name)
        if self.output is not None:
            self.output.delete("1.0", "end")
        self.output_var.set("运行中")

        def worker() -> None:
            try:
                proc = subprocess.run(
                    command,
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=int(self.values.get("LYNKCO_AUTO_TIMEOUT") or "180"),
                )
                output = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
                self.root.after(0, self.append_output, output)
                self.root.after(0, self.output_var.set, "成功" if proc.returncode == 0 else f"失败：{proc.returncode}")
            except Exception as exc:
                self.root.after(0, self.append_output, str(exc))
                self.root.after(0, self.output_var.set, "执行失败")

        threading.Thread(target=worker, daemon=True).start()

    def run_python(self, args: list[str]) -> None:
        self.run_command([self.python_executable(), *[str(ROOT / arg) if arg.endswith(".py") else arg for arg in args]])

    def test_notification(self) -> None:
        self.run_python(["lynkco_auto.py", "--notify-test"])

    def task_run_command(self) -> str:
        python = self.collect_values().get("PYTHON_EXE") or sys.executable
        return f'"{python}" "{ROOT / "lynkco_auto.py"}"'

    def toggle_daily(self) -> None:
        if not (is_windows() or is_macos()):
            messagebox.showerror("不支持", "当前系统只支持 Windows 和 macOS。")
            return
        run_time = self.selected_time()
        if self.daily_enabled.get():
            if is_windows():
                self.run_command(
                    [
                        "schtasks",
                        "/Create",
                        "/TN",
                        WINDOWS_DAILY_TASK,
                        "/TR",
                        self.task_run_command(),
                        "/SC",
                        "DAILY",
                        "/ST",
                        run_time,
                        "/F",
                    ]
                )
            else:
                hour, minute = self.time_parts(run_time)
                self.create_macos_job(MACOS_DAILY_LABEL, {"Hour": int(hour), "Minute": int(minute)}, run_at_load=False)
        else:
            if is_windows():
                self.run_command(["schtasks", "/Delete", "/TN", WINDOWS_DAILY_TASK, "/F"])
            else:
                self.remove_macos_job(MACOS_DAILY_LABEL)

    def toggle_startup(self) -> None:
        if not (is_windows() or is_macos()):
            messagebox.showerror("不支持", "当前系统只支持 Windows 和 macOS。")
            return
        if self.startup_enabled.get():
            if is_windows():
                self.run_command(
                    [
                        "schtasks",
                        "/Create",
                        "/TN",
                        WINDOWS_STARTUP_TASK,
                        "/TR",
                        self.task_run_command(),
                        "/SC",
                        "ONLOGON",
                        "/F",
                    ]
                )
            else:
                self.create_macos_job(MACOS_STARTUP_LABEL, None, run_at_load=True)
        else:
            if is_windows():
                self.run_command(["schtasks", "/Delete", "/TN", WINDOWS_STARTUP_TASK, "/F"])
            else:
                self.remove_macos_job(MACOS_STARTUP_LABEL)

    def macos_plist_path(self, label: str) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"

    def create_macos_job(self, label: str, schedule: dict[str, int] | None, run_at_load: bool) -> None:
        def action() -> tuple[int, str]:
            plist_path = self.macos_plist_path(label)
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            logs_dir = ROOT / "logs"
            logs_dir.mkdir(exist_ok=True)
            plist: dict[str, Any] = {
                "Label": label,
                "ProgramArguments": [self.collect_values().get("PYTHON_EXE") or sys.executable, str(ROOT / "lynkco_auto.py")],
                "WorkingDirectory": str(ROOT),
                "StandardOutPath": str(logs_dir / f"{label}.out.log"),
                "StandardErrorPath": str(logs_dir / f"{label}.err.log"),
                "EnvironmentVariables": {"PYTHONIOENCODING": "utf-8"},
            }
            if schedule is not None:
                plist["StartCalendarInterval"] = schedule
            if run_at_load:
                plist["RunAtLoad"] = True
            with plist_path.open("wb") as file:
                plistlib.dump(plist, file, sort_keys=False)

            uid = str(os.getuid())
            self.command_ok(["launchctl", "bootout", f"gui/{uid}/{label}"])
            proc = subprocess.run(
                ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            output = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
            if proc.returncode == 0:
                output = output or f"已启用 macOS 任务：{label}\n"
            return proc.returncode, output

        self.run_action(action)

    def remove_macos_job(self, label: str) -> None:
        def action() -> tuple[int, str]:
            uid = str(os.getuid())
            self.command_ok(["launchctl", "bootout", f"gui/{uid}/{label}"])
            self.macos_plist_path(label).unlink(missing_ok=True)
            return 0, f"已关闭 macOS 任务：{label}\n"

        self.run_action(action)

    def run_action(self, action) -> None:
        self.save_config()
        if hasattr(self, "tabs"):
            self.tabs.set(self.log_page_name)
        if self.output is not None:
            self.output.delete("1.0", "end")
        self.output_var.set("运行中")

        def worker() -> None:
            try:
                code, output = action()
                self.root.after(0, self.append_output, output)
                self.root.after(0, self.output_var.set, "成功" if code == 0 else f"失败：{code}")
            except Exception as exc:
                self.root.after(0, self.append_output, str(exc))
                self.root.after(0, self.output_var.set, "执行失败")

        threading.Thread(target=worker, daemon=True).start()

    def command_ok(self, command: list[str]) -> bool:
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=8)
            return proc.returncode == 0
        except OSError:
            return False

    def refresh_switches(self) -> None:
        if is_windows():
            self.daily_enabled.set(self.command_ok(["schtasks", "/Query", "/TN", WINDOWS_DAILY_TASK]))
            self.startup_enabled.set(self.command_ok(["schtasks", "/Query", "/TN", WINDOWS_STARTUP_TASK]))
        elif is_macos():
            uid = str(os.getuid())
            self.daily_enabled.set(self.command_ok(["launchctl", "print", f"gui/{uid}/{MACOS_DAILY_LABEL}"]))
            self.startup_enabled.set(self.command_ok(["launchctl", "print", f"gui/{uid}/{MACOS_STARTUP_LABEL}"]))

    def open_url(self, url: str) -> None:
        webbrowser.open(url)

    def open_folder(self) -> None:
        if is_windows():
            os.startfile(ROOT)  # type: ignore[attr-defined]
        elif is_macos():
            subprocess.Popen(["open", str(ROOT)])
        else:
            subprocess.Popen(["xdg-open", str(ROOT)])


def main() -> int:
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("green")
    root = ctk.CTk()
    LynkcoGui(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
