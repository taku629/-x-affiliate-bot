"""
result_logger.py
----------------
投稿結果を JSONL ファイルに記録し、重複投稿チェックを提供する。

ファイル形式: logs/posts.jsonl（1行1レコード、UTF-8）
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_LOG_PATH = Path("logs/posts.jsonl")


def build_post_record(
    *,
    trend_name: str,
    category: str,
    affiliate_url: str,
    post_text: str,
    tweet_id: str,
    tweet_url: str,
    dry_run: bool,
    with_image: bool,
    media_id: Optional[str] = None,
    hook_type: Optional[str] = None,
    thread_mode: bool = False,
    post_mode: str = "affiliate",
) -> dict:
    """投稿記録 dict を作成する。post_mode でログから投稿種別を追跡できる。"""
    return {
        "posted_at":     datetime.now(timezone.utc).isoformat(),
        "dry_run":       dry_run,
        "thread_mode":   thread_mode,
        "post_mode":     post_mode,
        "trend_name":    trend_name,
        "category":      category,
        "affiliate_url": affiliate_url,
        "with_image":    with_image,
        "media_id":      media_id,
        "post_text":     post_text,
        "tweet_id":      tweet_id,
        "tweet_url":     tweet_url,
        "hook_type":     hook_type,
    }


def save_post_result(record: dict, log_path: Path = DEFAULT_LOG_PATH) -> None:
    """投稿記録を JSONL に追記する。"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info("[結果保存] %s に追記しました", log_path)


def load_recent_posts(
    log_path: Path = DEFAULT_LOG_PATH,
    hours: int = 24,
) -> list[dict]:
    """直近 N 時間の投稿記録を返す。ファイルが存在しない場合は空リスト。"""
    if not log_path.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent: list[dict] = []

    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                posted_at = datetime.fromisoformat(record["posted_at"])
                if posted_at.tzinfo is None:
                    posted_at = posted_at.replace(tzinfo=timezone.utc)
                if posted_at >= cutoff:
                    recent.append(record)
            except (json.JSONDecodeError, KeyError, ValueError):
                pass

    return recent


def count_today_posts(
    log_path: Path = DEFAULT_LOG_PATH,
    hours: int = 24,
) -> int:
    """
    直近 N 時間の実投稿件数（dry_run=False のみ）を返す。

    dry_run 実行分は件数に含めない。テスト実行が本番の投稿枠を
    消費しないようにするための設計。
    """
    return sum(
        1
        for p in load_recent_posts(log_path, hours)
        if not p.get("dry_run", False)
    )


def is_duplicate_trend(trend_name: str, recent_posts: list[dict]) -> bool:
    """同一キーワードが直近投稿済みか確認する。"""
    return any(p.get("trend_name") == trend_name for p in recent_posts)
