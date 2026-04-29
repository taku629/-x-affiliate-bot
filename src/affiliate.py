"""
affiliate.py
------------
アフィリエイトリンク管理モジュール。

カテゴリ文字列を受け取り、対応するアフィリエイトURLを返す。
URL は下記の AFFILIATE_LINKS 辞書で一元管理しているため、
本番運用時はここを書き換えるだけで全投稿のリンクが更新される。

【差し替え手順】
  1. 楽天アフィリエイト等でリンクを発行する
  2. AFFILIATE_LINKS[カテゴリ名] の URL を本物に置き換える
  3. RAKUTEN_AFFILIATE_ID を .env に設定すると楽天トラッキングが有効になる
"""

from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass
from typing import Optional, Union

logger = logging.getLogger(__name__)

# =====================================================================
# アフィリエイトリンク辞書
# =====================================================================
# ▼▼▼ ここのURLを本物に差し替えてください ▼▼▼
#
# 楽天アフィリエイトリンク発行先:
#   https://affiliate.rakuten.co.jp/
#
# Amazonアソシエイト:
#   https://affiliate.amazon.co.jp/
#
# ※ URLは短縮せずそのまま記載してください（Xが t.co で自動短縮します）

AFFILIATE_LINKS: dict[str, Union[str, list[str]]] = {
    # スポーツ用品・トレーニンググッズ
    "sports": "https://www.rakuten.co.jp/search/sports/?dummy=REPLACE_ME",

    # エンタメ（音楽・映画・ゲーム・書籍）
    "entertainment": "https://www.rakuten.co.jp/search/entertainment/?dummy=REPLACE_ME",

    # テクノロジー・ガジェット（発行済み3件からランダム選択）
    "tech": [
        "https://a.r10.to/hXU6st",
        "https://a.r10.to/h5Z2gk",
        "https://a.r10.to/hPt8hk",
    ],

    # ファッション・アパレル
    "fashion": "https://www.rakuten.co.jp/search/fashion/?dummy=REPLACE_ME",

    # グルメ・食品
    "food": "https://www.rakuten.co.jp/search/food/?dummy=REPLACE_ME",

    # 旅行・宿泊
    "travel": "https://travel.rakuten.co.jp/?dummy=REPLACE_ME",

    # 健康・美容・ダイエット
    "health": "https://www.rakuten.co.jp/search/health/?dummy=REPLACE_ME",

    # 書籍・雑誌
    "books": "https://books.rakuten.co.jp/?dummy=REPLACE_ME",

    # その他・汎用（上記に当てはまらないもの）
    "other": "https://www.rakuten.co.jp/?dummy=REPLACE_ME",
}
# ▲▲▲ 楽天リンクここまで ▲▲▲

# =====================================================================
# Amazon アソシエイトリンク辞書
# =====================================================================
# AFFILIATE_ASP=amazon のときに使用される。
# tag= の REPLACE_ME を Amazon アソシエイトのトラッキングIDに差し替えてください。
# 取得先: https://affiliate.amazon.co.jp/

AFFILIATE_LINKS_AMAZON: dict[str, Union[str, list[str]]] = {
    "sports":        "https://www.amazon.co.jp/s?k=スポーツ用品&tag=REPLACE_ME",
    "entertainment": "https://www.amazon.co.jp/s?k=エンタメ&tag=REPLACE_ME",
    "tech":          "https://www.amazon.co.jp/s?k=ガジェット&tag=REPLACE_ME",
    "fashion":       "https://www.amazon.co.jp/s?k=ファッション&tag=REPLACE_ME",
    "food":          "https://www.amazon.co.jp/s?k=食品&tag=REPLACE_ME",
    "travel":        "https://www.amazon.co.jp/s?k=旅行グッズ&tag=REPLACE_ME",
    "health":        "https://www.amazon.co.jp/s?k=健康グッズ&tag=REPLACE_ME",
    "books":         "https://www.amazon.co.jp/s?k=本&tag=REPLACE_ME",
    "other":         "https://www.amazon.co.jp/?tag=REPLACE_ME",
}


def _get_links_dict() -> dict[str, Union[str, list[str]]]:
    """環境変数 AFFILIATE_ASP に応じてリンク辞書を返す（デフォルト: rakuten）。"""
    asp = os.environ.get("AFFILIATE_ASP", "rakuten").lower().strip()
    if asp == "amazon":
        return AFFILIATE_LINKS_AMAZON
    return AFFILIATE_LINKS


# 楽天アフィリエイトIDをURLに付与する場合のパラメータキー
_RAKUTEN_AFFILIATE_PARAM = "a_id"

# =====================================================================
# データクラス
# =====================================================================

@dataclass
class AffiliateLink:
    url: str
    category: str
    is_dummy: bool          # まだ本物URLに差し替えていない場合 True
    display_label: str      # ポスト末尾に付ける日本語ラベル（任意）


# =====================================================================
# 内部ロジック
# =====================================================================

def _attach_rakuten_id(url: str, affiliate_id: str) -> str:
    """楽天アフィリエイトIDをURLクエリに付加する（既にある場合はスキップ）。"""
    if not affiliate_id or _RAKUTEN_AFFILIATE_PARAM in url:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{_RAKUTEN_AFFILIATE_PARAM}={affiliate_id}"


_CATEGORY_DISPLAY_LABELS: dict[str, str] = {
    "sports":        "🏃 スポーツ用品はこちら",
    "entertainment": "🎬 エンタメグッズはこちら",
    "tech":          "💻 最新ガジェットはこちら",
    "fashion":       "👗 ファッションはこちら",
    "food":          "🍜 グルメ・食品はこちら",
    "travel":        "✈️ 旅行・ホテルはこちら",
    "health":        "💪 健康グッズはこちら",
    "books":         "📚 関連書籍はこちら",
    "other":         "🛒 関連商品はこちら",
}

# =====================================================================
# 公開関数
# =====================================================================

def get_affiliate_link(
    category: str,
    rakuten_affiliate_id: Optional[str] = None,
) -> AffiliateLink:
    """
    カテゴリに対応するアフィリエイトリンクを返す。

    Parameters
    ----------
    category             : ai_generator が返すカテゴリ文字列
                           (sports / entertainment / tech / fashion /
                            food / travel / health / books / other)
    rakuten_affiliate_id : 楽天アフィリエイトID（省略時は環境変数 RAKUTEN_AFFILIATE_ID）

    Returns
    -------
    AffiliateLink
    """
    links = _get_links_dict()

    # カテゴリが辞書にない場合は "other" にフォールバック
    normalized = category.lower().strip()
    if normalized not in links:
        logger.warning(
            "Unknown affiliate category '%s'. Falling back to 'other'.", category
        )
        normalized = "other"

    raw = links[normalized]
    base_url = random.choice(raw) if isinstance(raw, list) else raw
    is_dummy  = "REPLACE_ME" in base_url

    if is_dummy:
        logger.warning(
            "Affiliate URL for category '%s' is still a dummy. "
            "Replace AFFILIATE_LINKS['%s'] in src/affiliate.py.",
            normalized, normalized,
        )

    # 楽天アフィリエイトIDの付加
    rakuten_id = (
        rakuten_affiliate_id
        or os.environ.get("RAKUTEN_AFFILIATE_ID", "")
    )
    if rakuten_id and not is_dummy:
        base_url = _attach_rakuten_id(base_url, rakuten_id)

    label = _CATEGORY_DISPLAY_LABELS.get(normalized, "🛒 関連商品はこちら")

    link = AffiliateLink(
        url=base_url,
        category=normalized,
        is_dummy=is_dummy,
        display_label=label,
    )
    logger.info(
        "Affiliate link resolved: category=%s is_dummy=%s url=%s",
        normalized, is_dummy, base_url[:60],
    )
    return link


def list_categories() -> list[str]:
    """設定済みカテゴリ一覧を返す（デバッグ・管理用）。"""
    return list(AFFILIATE_LINKS.keys())
