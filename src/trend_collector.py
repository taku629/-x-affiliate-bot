"""
trend_collector.py
------------------
Google Trends RSS (JP) からトレンドワードを取得する。

データソース: https://trends.google.com/trends/trendingsearches/daily/rss?geo=JP

バイラルスコアリング:
  - トラフィック量（絶対値）
  - ニュース記事数（文脈が豊富なほどAI生成が高品質になる）
  - カテゴリ係数（エンタメ・スポーツはバズりやすい）
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

# カテゴリキーワード → バイラル係数（エンタメ・スポーツはバズりやすい）
_VIRAL_CATEGORY_BOOST: list[tuple[re.Pattern, float]] = [
    (re.compile(r"映画|ドラマ|アニメ|ゲーム|音楽|アーティスト|俳優|女優|歌手"), 1.4),
    (re.compile(r"スポーツ|野球|サッカー|テニス|ゴルフ|バスケ|格闘技|五輪|W杯"), 1.3),
    (re.compile(r"グルメ|料理|レシピ|スイーツ|カフェ|ラーメン|寿司"), 1.2),
    (re.compile(r"ファッション|コスメ|美容|スキンケア|ダイエット"), 1.2),
    (re.compile(r"旅行|観光|ホテル|温泉|絶景"), 1.15),
    (re.compile(r"AI|ChatGPT|スマホ|iPhone|アプリ|ガジェット"), 1.1),
]


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
        return (
            f"TrendItem(keyword={self.keyword!r}, "
            f"traffic={self.approx_traffic}, "
            f"viral_score={self.viral_score():.2f})"
        )

    def is_safe(self) -> bool:
        text = self.keyword
        if self.news_items:
            text += " " + " ".join(n.title for n in self.news_items)
        return not bool(_UNSAFE_RE.search(text))

    def _traffic_value(self) -> int:
        raw = re.sub(r"[^\d]", "", self.approx_traffic)
        return int(raw) if raw else 0

    def viral_score(self) -> float:
        """
        バイラル潜在力スコア（0.0〜1.0+）を返す。
        選定の優先度付けに使用する。

        計算式:
          base  = traffic / 1,000,000（上限なし: 100万超で1.0超え）
          news  = min(len(news_items) * 0.08, 0.3)  # 最大 0.3 加算
          boost = カテゴリ係数（エンタメ等は最大 1.4 倍）
        """
        traffic = self._traffic_value()
        base = traffic / 1_000_000

        news_bonus = min(len(self.news_items) * 0.08, 0.3)

        category_multiplier = 1.0
        text = self.keyword + " ".join(n.title for n in self.news_items)
        for pattern, mult in _VIRAL_CATEGORY_BOOST:
            if pattern.search(text):
                category_multiplier = max(category_multiplier, mult)

        return (base + news_bonus) * category_multiplier


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
    sort_by_viral: bool = True,
    timeout: int = 10,
) -> list[TrendItem]:
    """
    Google Trends RSS からトレンドを取得して返す。

    Parameters
    ----------
    top_n          : 返す件数の上限
    safe_only      : True のとき炎上リスクの高いトピックを除外する
    shuffle        : True のときランダムな順序で返す（sort_by_viral が False のときのみ有効）
    sort_by_viral  : True のときバイラルスコアで降順ソートする（デフォルト True）
    timeout        : HTTP タイムアウト秒数
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

    if sort_by_viral:
        trends.sort(key=lambda t: t.viral_score(), reverse=True)
        logger.info(
            "バイラルスコア順ソート完了: top=%s (score=%.2f)",
            trends[0].keyword if trends else "N/A",
            trends[0].viral_score() if trends else 0.0,
        )
    elif shuffle:
        random.shuffle(trends)

    return trends[:top_n]


def pick_best_trend(safe_only: bool = True, timeout: int = 10) -> TrendItem:
    """
    バイラルスコアが最も高いトレンドを1件返す。

    Raises
    ------
    RuntimeError : 有効なトレンドが0件の場合
    """
    trends = get_trends(
        top_n=20,
        safe_only=safe_only,
        sort_by_viral=True,
        timeout=timeout,
    )
    if not trends:
        raise RuntimeError("有効なトレンドが見つかりませんでした")
    return trends[0]
