"""
trend_collector.py
------------------
Google Trends RSS (JP) からトレンドワードを取得する。

データソース: https://trends.google.com/trends/trendingsearches/daily/rss?geo=JP
"""
from __future__ import annotations

import logging
import random
import re
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

TRENDS_RSS_URL = "https://trends.google.com/trending/rss?geo=JP"

# 炎上リスクが高いキーワードパターン（safe_only=True 時に除外）
_UNSAFE_PATTERNS = [
    r"死亡", r"死去", r"訃報", r"逝去", r"遺体", r"遺族",
    r"事故", r"事件", r"殺人", r"殺害", r"暴行", r"逮捕",
    r"政治", r"選挙", r"政党", r"首相", r"大臣", r"国会",
    r"戦争", r"紛争", r"テロ", r"爆発", r"爆弾",
    r"自殺", r"自死", r"過労死",
    r"地震", r"津波", r"台風", r"洪水", r"土砂崩れ",
    r"差別", r"ハラスメント", r"炎上",
]
_UNSAFE_RE = re.compile("|".join(_UNSAFE_PATTERNS))


@dataclass
class NewsItem:
    title: str
    url: str
    source: str


@dataclass
class TrendItem:
    keyword: str
    approx_traffic: str
    news_items: list[NewsItem] = field(default_factory=list)
    picture_url: Optional[str] = None

    def __str__(self) -> str:
        return f"TrendItem(keyword={self.keyword!r}, traffic={self.approx_traffic})"

    def is_safe(self) -> bool:
        text = self.keyword
        if self.news_items:
            text += " " + " ".join(n.title for n in self.news_items)
        return not bool(_UNSAFE_RE.search(text))


def _fetch_rss(url: str, timeout: int = 10) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; XAffiliateBot/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse_rss(xml_bytes: bytes) -> list[TrendItem]:
    root = ET.fromstring(xml_bytes)
    ns = {"ht": "https://trends.google.com/trending/rss"}
    items: list[TrendItem] = []

    for item in root.findall(".//item"):
        keyword_el = item.find("title")
        traffic_el = item.find("ht:approx_traffic", ns)
        picture_el = item.find("ht:picture", ns)

        if keyword_el is None or not keyword_el.text:
            continue

        keyword = keyword_el.text.strip()
        approx_traffic = traffic_el.text.strip() if traffic_el is not None and traffic_el.text else "N/A"
        picture_url = picture_el.text.strip() if picture_el is not None and picture_el.text else None

        news_items: list[NewsItem] = []
        for news_el in item.findall("ht:news_item", ns):
            title_el = news_el.find("ht:news_item_title", ns)
            url_el = news_el.find("ht:news_item_url", ns)
            source_el = news_el.find("ht:news_item_source", ns)
            news_items.append(NewsItem(
                title=title_el.text.strip() if title_el is not None and title_el.text else "",
                url=url_el.text.strip() if url_el is not None and url_el.text else "",
                source=source_el.text.strip() if source_el is not None and source_el.text else "",
            ))

        items.append(TrendItem(
            keyword=keyword,
            approx_traffic=approx_traffic,
            news_items=news_items,
            picture_url=picture_url,
        ))

    return items


def get_trends(
    top_n: int = 5,
    safe_only: bool = True,
    shuffle: bool = False,
    timeout: int = 10,
) -> list[TrendItem]:
    """
    Google Trends RSS からトレンドを取得して返す。

    Parameters
    ----------
    top_n     : 返す件数の上限
    safe_only : True のとき炎上リスクの高いトピックを除外する
    shuffle   : True のときランダムな順序で返す（同じトレンドの繰り返しを防ぐ）
    timeout   : HTTP タイムアウト秒数
    """
    try:
        xml_bytes = _fetch_rss(TRENDS_RSS_URL, timeout=timeout)
    except urllib.error.URLError as e:
        raise RuntimeError(f"Google Trends RSS の取得に失敗しました: {e}") from e

    trends = _parse_rss(xml_bytes)
    logger.info("RSS取得: %d件のトレンドを取得", len(trends))

    if safe_only:
        before = len(trends)
        trends = [t for t in trends if t.is_safe()]
        logger.info("安全フィルタ: %d件 → %d件", before, len(trends))

    if shuffle:
        random.shuffle(trends)

    return trends[:top_n]


def pick_best_trend(safe_only: bool = True, timeout: int = 10) -> TrendItem:
    """
    最もトラフィックが多いトレンドを1件返す。

    Raises
    ------
    RuntimeError : 有効なトレンドが0件の場合
    """
    trends = get_trends(top_n=20, safe_only=safe_only, shuffle=False, timeout=timeout)
    if not trends:
        raise RuntimeError("有効なトレンドが見つかりませんでした")

    def _traffic_value(t: TrendItem) -> int:
        raw = re.sub(r"[^\d]", "", t.approx_traffic)
        return int(raw) if raw else 0

    return max(trends, key=_traffic_value)
