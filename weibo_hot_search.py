#!/usr/bin/env python3
"""
新浪微博热搜榜爬虫
抓取实时热搜标题与热度，导出 CSV 文件
"""

import csv
import json
import time
from datetime import datetime

import requests

# ── 配置 ──────────────────────────────────────────────
URL = "https://weibo.com/ajax/side/hotSearch"
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
OUTPUT_FILE = "weibo_hot_search.csv"


def fetch_hot_search() -> list[dict]:
    """请求微博热搜 API，返回 [{"title": ..., "hot": ...}, ...]"""
    resp = requests.get(URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    realtime = data.get("data", {}).get("realtime", [])
    if not realtime:
        # 兜底：尝试热门话题接口
        raise ValueError("未获取到热搜数据，接口可能已变更")

    results = []
    for item in realtime:
        title = item.get("word", "").strip()
        # raw_hot 为热度数值（可能为 0 或不存在时回退到 label_name / num）
        raw_hot = item.get("raw_hot") or item.get("num") or 0
        hot_label = item.get("label_name", "")  # "爆" / "沸" / "新" 等标记
        if not title:
            continue

        # 热度展示：数字 + 标记（如有）
        hot_str = str(raw_hot)
        if hot_label:
            hot_str = f"{hot_label} {hot_str}"

        results.append({"title": title, "hot": hot_str})

    return results


def save_csv(items: list[dict], filepath: str) -> None:
    """将热搜数据写入 CSV"""
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["title", "hot"])
        writer.writeheader()
        writer.writerows(items)

    print(f"[OK] 已导出 {len(items)} 条热搜 -> {filepath}")


def print_table(items: list[dict]) -> None:
    """终端打印预览"""
    print(f"\n{'='*60}")
    print(f"  微博热搜榜  ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print(f"{'='*60}")
    for i, item in enumerate(items, 1):
        print(f"  {i:>2}. {item['title']}  [{item['hot']}]")
    print(f"{'='*60}\n")


def main() -> None:
    try:
        items = fetch_hot_search()
        print_table(items)
        save_csv(items, OUTPUT_FILE)
    except requests.RequestException as e:
        print(f"[ERROR] 网络请求失败: {e}")
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        print(f"[ERROR] 数据解析失败: {e}")
        print("提示：微博接口可能需要有效的 Cookie，请登录微博后复制 Cookie 添加到 HEADERS。")


if __name__ == "__main__":
    main()
