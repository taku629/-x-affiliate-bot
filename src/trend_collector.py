"""Google Trends RSS から日本のトレンドワードを取得し、安全フィルタを通して返す。"""

import feedparser
import random

TRENDS_RSS_URL = "https://trends.google.co.jp/trending/rss?geo=JP"

# 投稿を避けるキーワード（炎上・センシティブトピック）
_BLOCK_KEYWORDS = [
    # 事故・災害
    "死亡", "死者", "遺体", "訃報", "葬儀", "火災", "地震", "津波", "台風", "豪雨",
    "崩壊", "爆発", "事故", "衝突", "墜落", "沈没", "行方不明", "遭難",
    # 犯罪・暴力
    "殺人", "殺害", "逮捕", "容疑者", "被告", "刑事", "暴行", "傷害", "詐欺", "強盗",
    "テロ", "爆弾", "銃撃", "誘拐",
    # 政治・宗教
    "選挙", "投票", "与党", "野党", "内閣", "総理", "大臣", "議員", "政党",
    "デモ", "抗議", "集会", "宗教", "カルト",
    # 健康被害
    "感染", "コロナ", "パンデミック", "ウイルス", "菌", "中毒",
    # その他炎上リスク
    "炎上", "批判", "謝罪", "差別", "ハラスメント", "不倫", "スキャンダル",
]


def _is_safe(keyword: str) -> bool:
    lower = keyword.lower()
    return not any(block in lower for block in _BLOCK_KEYWORDS)


def fetch_trends(max_topics: int = 20) -> list[str]:
    """Googleトレンド JP RSS からトレンドワードを取得して返す。"""
    feed = feedparser.parse(TRENDS_RSS_URL)
    topics = [entry.title for entry in feed.entries if entry.title]
    safe = [t for t in topics if _is_safe(t)]
    return safe[:max_topics]


def pick_trend(trends: list[str]) -> str | None:
    """安全なトレンドからランダムに1件選ぶ。"""
    if not trends:
        return None
    return random.choice(trends)
