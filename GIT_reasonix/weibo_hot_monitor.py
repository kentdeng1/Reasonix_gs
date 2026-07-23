#!/usr/bin/env python3
"""
微博热搜监控桌面应用
—— 定时采集 · 关键字提醒 · 现代化圆角 UI ——

依赖: pip install customtkinter requests Pillow
打包: pyinstaller --onefile --windowed --name 微博热搜监控 weibo_hot_monitor.py
"""

import csv
import json
import os
import threading
import time
from datetime import datetime, timedelta
from tkinter import messagebox
from typing import Callable, Dict, List, Optional

import customtkinter as ctk
import requests

# ── 全局配置 ──────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

HOT_SEARCH_URL = "https://weibo.com/ajax/side/hotSearch"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://weibo.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
CSV_FILE = "weibo_hot_search.csv"

# ── 颜色常量 ──────────────────────────────────────────
COLORS = {
    "bg": ("#f0f2f5", "#1a1a2e"),
    "card": ("#ffffff", "#16213e"),
    "accent": "#3b82f6",
    "hot_red": "#ef4444",
    "hot_orange": "#f97316",
    "text_primary": ("#1f2937", "#f1f5f9"),
    "text_secondary": ("#6b7280", "#94a3b8"),
}

# ══════════════════════════════════════════════════════
#  数据层
# ══════════════════════════════════════════════════════


class HotSearchFetcher:
    """微博热搜数据抓取器"""

    @staticmethod
    def fetch() -> List[Dict[str, str]]:
        """返回 [{"rank": 1, "title": "...", "hot": "新 123456"}, ...]"""
        resp = requests.get(HOT_SEARCH_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        realtime = data.get("data", {}).get("realtime", [])
        if not realtime:
            raise ValueError("未获取到热搜数据，接口可能已变更")

        results: List[Dict[str, str]] = []
        for i, item in enumerate(realtime, 1):
            title = item.get("word", "").strip()
            if not title:
                continue
            raw_hot = item.get("raw_hot") or item.get("num") or 0
            hot_label = item.get("label_name", "")
            hot_str = str(raw_hot)
            if hot_label:
                hot_str = f"{hot_label} {hot_str}"
            results.append({"rank": str(i), "title": title, "hot": hot_str})
        return results

    @staticmethod
    def check_keywords(
        items: List[Dict[str, str]], keywords: List[str]
    ) -> List[Dict[str, str]]:
        """返回 items 中标题包含任一关键字的热搜条目"""
        if not keywords:
            return []
        matched: List[Dict[str, str]] = []
        for item in items:
            for kw in keywords:
                if kw and kw.strip() and kw.strip() in item["title"]:
                    matched.append(item)
                    break
        return matched


# ══════════════════════════════════════════════════════
#  自定义组件
# ══════════════════════════════════════════════════════


class KeywordTag(ctk.CTkFrame):
    """关键字标签（带删除按钮）"""

    def __init__(
        self, master, text: str, on_delete: Callable[[str], None], **kwargs
    ):
        super().__init__(master, **kwargs)
        self._text = text
        self._on_delete = on_delete

        self.configure(
            fg_color=("#dbeafe", "#1e3a5f"),
            corner_radius=12,
            height=30,
        )
        self.pack_propagate(False)

        # 关键字文本
        self.label = ctk.CTkLabel(
            self,
            text=f"  {text}  ",
            font=ctk.CTkFont(size=12),
            text_color=("#2563eb", "#93c5fd"),
        )
        self.label.pack(side="left", padx=(8, 2), pady=2)

        # 删除按钮
        self.btn_del = ctk.CTkButton(
            self,
            text="×",
            width=20,
            height=20,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="transparent",
            hover_color=("#fecaca", "#7f1d1d"),
            text_color=("#64748b", "#94a3b8"),
            corner_radius=10,
            command=self._delete,
        )
        self.btn_del.pack(side="right", padx=(0, 4))

    def _delete(self) -> None:
        self._on_delete(self._text)


class HotSearchRow(ctk.CTkFrame):
    """热搜列表单行"""

    def __init__(self, master, rank: str, title: str, hot: str, **kwargs):
        super().__init__(master, corner_radius=8, height=36, **kwargs)
        self.pack_propagate(False)

        # 交替背景色
        row_num = int(rank) if rank.isdigit() else 0
        if row_num % 2 == 0:
            self.configure(fg_color=("gray90", "gray20"))

        # 排名（前3名特殊高亮）
        rank_color = COLORS["hot_red"] if row_num <= 3 else COLORS["text_secondary"]
        rank_font = ctk.CTkFont(
            size=13, weight="bold" if row_num <= 3 else "normal"
        )
        lbl_rank = ctk.CTkLabel(
            self,
            text=f"  {rank}",
            width=45,
            anchor="w",
            font=rank_font,
            text_color=rank_color,
        )
        lbl_rank.pack(side="left", padx=(4, 0))

        # 标题
        lbl_title = ctk.CTkLabel(
            self,
            text=title,
            anchor="w",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_primary"],
        )
        lbl_title.pack(side="left", fill="x", expand=True, padx=8)

        # 热度
        hot_color = COLORS["hot_red"] if hot.startswith("爆") else COLORS["text_secondary"]
        lbl_hot = ctk.CTkLabel(
            self,
            text=hot,
            width=110,
            anchor="e",
            font=ctk.CTkFont(size=12),
            text_color=hot_color,
        )
        lbl_hot.pack(side="right", padx=(0, 12))


# ══════════════════════════════════════════════════════
#  提醒弹窗
# ══════════════════════════════════════════════════════


class ReminderDialog(ctk.CTkToplevel):
    """关键字匹配提醒弹窗"""

    def __init__(
        self,
        parent,
        matched_items: List[Dict[str, str]],
        keyword: Optional[str] = None,
    ):
        super().__init__(parent)
        self.title("🔔 关键字提醒")
        self.geometry("520x400")
        self.resizable(False, False)
        self.attributes("-topmost", True)

        # 窗口居中
        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_x(), parent.winfo_y()
        cx, cy = px + pw // 2, py + ph // 2
        w, h = 520, 400
        self.geometry(f"{w}x{h}+{cx-w//2}+{cy-h//2}")

        # 标题区域
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=20, pady=(20, 10))

        ctk.CTkLabel(
            header_frame,
            text="🔔 关键字提醒",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["accent"],
        ).pack(anchor="w")

        if keyword:
            ctk.CTkLabel(
                header_frame,
                text=f"检测到关键字「{keyword}」相关热搜：",
                font=ctk.CTkFont(size=13),
                text_color=COLORS["text_secondary"],
            ).pack(anchor="w", pady=(4, 0))

        # 匹配列表
        scroll = ctk.CTkScrollableFrame(
            self, corner_radius=12, fg_color=COLORS["card"]
        )
        scroll.pack(fill="both", expand=True, padx=20, pady=10)

        for item in matched_items:
            card = ctk.CTkFrame(
                scroll,
                corner_radius=8,
                fg_color=("#f0fdf4", "#0f2e1a"),
                height=44,
            )
            card.pack(fill="x", pady=3)
            card.pack_propagate(False)

            ctk.CTkLabel(
                card,
                text=f"  #{item['rank']}",
                width=40,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=COLORS["accent"],
            ).pack(side="left")

            ctk.CTkLabel(
                card,
                text=item["title"],
                font=ctk.CTkFont(size=13),
                text_color=COLORS["text_primary"],
            ).pack(side="left", fill="x", expand=True, padx=6)

            ctk.CTkLabel(
                card,
                text=item["hot"],
                width=90,
                anchor="e",
                font=ctk.CTkFont(size=12),
                text_color=COLORS["text_secondary"],
            ).pack(side="right", padx=(0, 10))

        # 关闭按钮
        ctk.CTkButton(
            self,
            text="知道了",
            command=self.destroy,
            fg_color=COLORS["accent"],
            hover_color="#2563eb",
            corner_radius=10,
            height=36,
            font=ctk.CTkFont(size=14),
        ).pack(pady=(5, 18))


# ══════════════════════════════════════════════════════
#  主应用
# ══════════════════════════════════════════════════════


class App(ctk.CTk):
    """微博热搜监控主应用"""

    # ── 初始化 ────────────────────────────────────────

    def __init__(self):
        super().__init__()

        # ─ 窗口属性 ─
        self.title("🔥 微博热搜监控")
        self.geometry("860x720")
        self.minsize(720, 560)
        self.resizable(True, True)

        # 窗口居中
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w, h = 860, 720
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        # ─ 状态变量 ─
        self._running = False          # 定时器是否运行
        self._keywords: List[str] = []  # 关键字列表
        self._last_data: List[Dict[str, str]] = []  # 最近一次抓取的数据
        self._timer: Optional[threading.Timer] = None
        self._fetch_count = 0
        self._last_fetch_time: Optional[str] = None
        self._next_fetch_time: Optional[str] = None
        self._current_interval = 5  # 默认5分钟

        # ─ 构建 UI ─
        self._build_ui()

        # ─ 绑定窗口关闭 ─
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI 构建 ───────────────────────────────────────

    def _build_ui(self) -> None:
        """构建完整界面"""
        # 主容器（带内边距）
        main = ctk.CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        main.pack(fill="both", expand=True, padx=0, pady=0)

        # ─ 标题栏 ─
        self._build_header(main)
        # ─ 采集控制 ─
        self._build_control(main)
        # ─ 关键字管理 ─
        self._build_keywords(main)
        # ─ 热搜列表 ─
        self._build_list(main)
        # ─ 状态栏 ─
        self._build_statusbar(main)

    def _build_header(self, parent) -> None:
        """标题栏"""
        header = ctk.CTkFrame(parent, fg_color=COLORS["card"], corner_radius=0)
        header.pack(fill="x")

        inner = ctk.CTkFrame(header, fg_color="transparent")
        inner.pack(fill="x", padx=24, pady=(14, 10))

        ctk.CTkLabel(
            inner,
            text="🔥 微博热搜监控",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        ctk.CTkLabel(
            inner,
            text="实时采集 · 关键字提醒",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
        ).pack(side="left", padx=(12, 0), pady=(4, 0))

        # 分隔线
        ctk.CTkFrame(header, height=1, fg_color=("gray85", "gray30")).pack(
            fill="x", padx=20
        )

    def _build_control(self, parent) -> None:
        """采集控制区"""
        card = ctk.CTkFrame(parent, fg_color=COLORS["card"], corner_radius=12)
        card.pack(fill="x", padx=16, pady=(12, 0))

        # 标题行
        ctk.CTkLabel(
            card,
            text="⏱ 采集控制",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(anchor="w", padx=16, pady=(12, 6))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 14))

        # 间隔选择
        ctk.CTkLabel(
            row,
            text="采集间隔",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"],
        ).pack(side="left")

        self._interval_var = ctk.StringVar(value="5")
        self._interval_combo = ctk.CTkOptionMenu(
            row,
            variable=self._interval_var,
            values=["1", "2", "3", "5", "10", "15", "30", "60"],
            width=60,
            corner_radius=8,
            font=ctk.CTkFont(size=13),
            dropdown_font=ctk.CTkFont(size=12),
        )
        self._interval_combo.pack(side="left", padx=(6, 4))

        ctk.CTkLabel(
            row,
            text="分钟",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"],
        ).pack(side="left", padx=(0, 16))

        # 开始/停止 按钮
        self._btn_start = ctk.CTkButton(
            row,
            text="▶ 开始采集",
            command=self._start_collecting,
            fg_color="#16a34a",
            hover_color="#15803d",
            corner_radius=10,
            height=34,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self._btn_start.pack(side="left", padx=4)

        self._btn_stop = ctk.CTkButton(
            row,
            text="⏹ 停止",
            command=self._stop_collecting,
            fg_color="#64748b",
            hover_color="#475569",
            corner_radius=10,
            height=34,
            font=ctk.CTkFont(size=13, weight="bold"),
            state="disabled",
        )
        self._btn_stop.pack(side="left", padx=4)

        # 立即采集
        self._btn_fetch_now = ctk.CTkButton(
            row,
            text="🔄 立即采集",
            command=self._fetch_now,
            fg_color=COLORS["accent"],
            hover_color="#2563eb",
            corner_radius=10,
            height=34,
            font=ctk.CTkFont(size=13),
        )
        self._btn_fetch_now.pack(side="left", padx=4)

        # 导出 CSV
        self._btn_export = ctk.CTkButton(
            row,
            text="📥 导出 CSV",
            command=self._export_csv,
            fg_color="transparent",
            border_width=1.5,
            border_color=COLORS["accent"],
            text_color=COLORS["accent"],
            hover_color=("#dbeafe", "#1e3a5f"),
            corner_radius=10,
            height=34,
            font=ctk.CTkFont(size=13),
        )
        self._btn_export.pack(side="left", padx=4)

        # 时间信息（右对齐）
        time_frame = ctk.CTkFrame(row, fg_color="transparent")
        time_frame.pack(side="right")

        self._label_last = ctk.CTkLabel(
            time_frame,
            text="上次采集: --",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
        )
        self._label_last.pack(anchor="e")

        self._label_next = ctk.CTkLabel(
            time_frame,
            text="下次采集: --",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
        )
        self._label_next.pack(anchor="e")

    def _build_keywords(self, parent) -> None:
        """关键字管理区"""
        card = ctk.CTkFrame(parent, fg_color=COLORS["card"], corner_radius=12)
        card.pack(fill="x", padx=16, pady=(8, 0))

        ctk.CTkLabel(
            card,
            text="🔑 关键字提醒",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(anchor="w", padx=16, pady=(12, 4))

        # 输入行
        input_row = ctk.CTkFrame(card, fg_color="transparent")
        input_row.pack(fill="x", padx=16, pady=(0, 6))

        self._kw_entry = ctk.CTkEntry(
            input_row,
            placeholder_text="输入要监控的关键字…",
            corner_radius=10,
            height=34,
            font=ctk.CTkFont(size=13),
        )
        self._kw_entry.pack(side="left", fill="x", expand=True)
        self._kw_entry.bind("<Return>", lambda e: self._add_keyword())

        self._btn_add_kw = ctk.CTkButton(
            input_row,
            text="➕ 添加",
            command=self._add_keyword,
            fg_color=COLORS["accent"],
            hover_color="#2563eb",
            corner_radius=10,
            height=34,
            font=ctk.CTkFont(size=13),
            width=80,
        )
        self._btn_add_kw.pack(side="left", padx=(8, 0))

        # 关键字标签容器
        self._kw_container = ctk.CTkFrame(card, fg_color="transparent")
        self._kw_container.pack(fill="x", padx=16, pady=(0, 12))

        # 占位提示
        self._kw_placeholder = ctk.CTkLabel(
            self._kw_container,
            text="（暂无关键字，添加后将自动监控匹配）",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
        )
        self._kw_placeholder.pack(anchor="w")

    def _build_list(self, parent) -> None:
        """热搜列表区"""
        card = ctk.CTkFrame(parent, fg_color=COLORS["card"], corner_radius=12)
        card.pack(fill="both", expand=True, padx=16, pady=(8, 4))

        # 标题行
        header_row = ctk.CTkFrame(card, fg_color="transparent")
        header_row.pack(fill="x", padx=16, pady=(10, 4))

        ctk.CTkLabel(
            header_row,
            text="📋 实时热搜榜",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        self._label_count = ctk.CTkLabel(
            header_row,
            text="共 0 条",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
        )
        self._label_count.pack(side="right")

        # 表头
        header_bar = ctk.CTkFrame(card, fg_color=("gray200", "gray25"), corner_radius=6)
        header_bar.pack(fill="x", padx=16, pady=(0, 2))

        ctk.CTkLabel(
            header_bar, text="  #", width=45, anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"],
        ).pack(side="left", padx=(4, 0))
        ctk.CTkLabel(
            header_bar, text="热搜标题", anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"],
        ).pack(side="left", fill="x", expand=True, padx=8)
        ctk.CTkLabel(
            header_bar, text="热度", width=110, anchor="e",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"],
        ).pack(side="right", padx=(0, 12))

        # 可滚动列表
        self._list_container = ctk.CTkScrollableFrame(
            card, corner_radius=8, fg_color="transparent"
        )
        self._list_container.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _build_statusbar(self, parent) -> None:
        """底部状态栏"""
        bar = ctk.CTkFrame(parent, fg_color=COLORS["card"], corner_radius=0, height=32)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        self._status_label = ctk.CTkLabel(
            bar,
            text="💤 就绪",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
        )
        self._status_label.pack(side="left", padx=16)

    # ── 核心功能 ──────────────────────────────────────

    def _fetch_now(self) -> None:
        """立即采集一次（后台线程）"""
        if hasattr(self, "_fetching") and self._fetching:
            return
        self._fetching = True
        self._set_status("🔄 正在采集…")
        self._btn_fetch_now.configure(state="disabled")

        thread = threading.Thread(target=self._do_fetch, daemon=True)
        thread.start()

    def _do_fetch(self) -> None:
        """在后台线程执行采集"""
        try:
            data = HotSearchFetcher.fetch()
            self.after(0, self._on_fetch_done, data)
        except requests.RequestException as e:
            self.after(0, self._on_fetch_error, f"网络错误: {e}")
        except (ValueError, json.JSONDecodeError, KeyError) as e:
            self.after(0, self._on_fetch_error, f"解析错误: {e}")
        except Exception as e:
            self.after(0, self._on_fetch_error, f"未知错误: {e}")

    def _on_fetch_done(self, data: List[Dict[str, str]]) -> None:
        """采集完成（主线程）"""
        self._fetching = False
        self._last_data = data
        self._fetch_count += 1
        now = datetime.now()
        self._last_fetch_time = now.strftime("%H:%M:%S")
        self._label_last.configure(text=f"上次采集: {self._last_fetch_time}")

        # 更新下次采集时间
        interval = int(self._interval_var.get())
        self._current_interval = interval
        next_time = now + timedelta(minutes=interval)
        self._next_fetch_time = next_time.strftime("%H:%M:%S")
        self._label_next.configure(text=f"下次采集: {self._next_fetch_time}")

        # 刷新列表
        self._refresh_list(data)

        # 关键字检查 & 提醒
        matched = HotSearchFetcher.check_keywords(data, self._keywords)
        if matched:
            keywords_str = "、".join(self._keywords)
            self.after(100, lambda: self._show_reminder(matched, keywords_str))

        self._set_status(
            f"✅ 采集成功 ({self._last_fetch_time})  |  共 {len(data)} 条热搜"
        )
        self._btn_fetch_now.configure(state="normal")

    def _on_fetch_error(self, msg: str) -> None:
        """采集失败（主线程）"""
        self._fetching = False
        self._set_status(f"❌ {msg}")
        self._btn_fetch_now.configure(state="normal")

    # ── 定时采集 ──────────────────────────────────────

    def _start_collecting(self) -> None:
        """开始定时采集"""
        if self._running:
            return
        self._running = True
        self._btn_start.configure(state="disabled")
        self._btn_stop.configure(state="normal")
        self._interval_combo.configure(state="disabled")
        self._set_status("▶ 定时采集中…")

        # 立即执行第一次
        self._fetch_now()
        # 启动循环
        self._schedule_next()

    def _stop_collecting(self) -> None:
        """停止定时采集"""
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        self._btn_start.configure(state="normal")
        self._btn_stop.configure(state="disabled")
        self._interval_combo.configure(state="normal")
        self._label_next.configure(text="下次采集: --")
        self._set_status("⏹ 已停止")

    def _schedule_next(self) -> None:
        """调度下一次采集"""
        if not self._running:
            return

        interval = int(self._interval_var.get()) * 60  # 秒
        self._timer = threading.Timer(interval, self._on_timer_tick)
        self._timer.daemon = True
        self._timer.start()

    def _on_timer_tick(self) -> None:
        """定时器触发"""
        if not self._running:
            return
        # 执行采集（在后台线程中 already）
        self._do_fetch()
        # 调度下一次
        self.after(0, self._schedule_next)

    # ── 关键字管理 ─────────────────────────────────────

    def _add_keyword(self) -> None:
        """添加关键字"""
        kw = self._kw_entry.get().strip()
        if not kw:
            return
        if kw in self._keywords:
            messagebox.showinfo("提示", f"关键字「{kw}」已存在")
            return
        self._keywords.append(kw)
        self._kw_entry.delete(0, "end")
        self._refresh_keyword_tags()

    def _remove_keyword(self, kw: str) -> None:
        """删除关键字"""
        if kw in self._keywords:
            self._keywords.remove(kw)
            self._refresh_keyword_tags()

    def _refresh_keyword_tags(self) -> None:
        """刷新关键字标签显示"""
        for w in self._kw_container.winfo_children():
            w.destroy()

        if not self._keywords:
            self._kw_placeholder = ctk.CTkLabel(
                self._kw_container,
                text="（暂无关键字，添加后将自动监控匹配）",
                font=ctk.CTkFont(size=12),
                text_color=COLORS["text_secondary"],
            )
            self._kw_placeholder.pack(anchor="w")
            return

        tags_frame = ctk.CTkFrame(self._kw_container, fg_color="transparent")
        tags_frame.pack(fill="x")

        for kw in self._keywords:
            tag = KeywordTag(tags_frame, kw, self._remove_keyword)
            tag.pack(side="left", padx=(0, 6), pady=3)

    # ── 列表刷新 ──────────────────────────────────────

    def _refresh_list(self, data: List[Dict[str, str]]) -> None:
        """刷新热搜列表显示"""
        for w in self._list_container.winfo_children():
            w.destroy()

        for item in data:
            row = HotSearchRow(
                self._list_container,
                rank=item["rank"],
                title=item["title"],
                hot=item["hot"],
            )
            row.pack(fill="x", pady=1)

        self._label_count.configure(text=f"共 {len(data)} 条")

    # ── 关键字提醒弹窗 ────────────────────────────────

    def _show_reminder(
        self, matched: List[Dict[str, str]], keyword_str: str
    ) -> None:
        """弹出关键字匹配提醒"""
        ReminderDialog(self, matched, keyword_str)

    # ── 导出 CSV ──────────────────────────────────────

    def _export_csv(self) -> None:
        """导出当前数据到 CSV"""
        if not self._last_data:
            messagebox.showwarning("提示", "暂无数据，请先采集")
            return
        try:
            filepath = CSV_FILE
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["rank", "title", "hot"])
                writer.writeheader()
                writer.writerows(self._last_data)
            self._set_status(f"📥 已导出 {len(self._last_data)} 条 → {filepath}")
            messagebox.showinfo("导出成功", f"已保存到:\n{os.path.abspath(filepath)}")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))

    # ── 辅助方法 ──────────────────────────────────────

    def _set_status(self, text: str) -> None:
        """设置状态栏文字"""
        self._status_label.configure(text=text)

    def _on_close(self) -> None:
        """窗口关闭清理"""
        self._running = False
        if self._timer:
            self._timer.cancel()
        self.destroy()

    # ── 入口 ──────────────────────────────────────────

    def run(self) -> None:
        """启动主循环"""
        self.mainloop()


# ══════════════════════════════════════════════════════
#  程序入口
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    app = App()
    app.run()
