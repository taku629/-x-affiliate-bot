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
from dataclasses import dataclass
from typing import Optional

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

AFFILIATE_LINKS: dict[str, str] = {
    # ▼▼▼ 楽天アフィリエイト管理画面で発行したURLに差し替えてください ▼▼▼
    # https://affiliate.rakuten.co.jp/ → ツールボックス → テキストリンク
    "sports":        "https://hb.afl.rakuten.co.jp/ichiba/REPLACE_ME/?pc=https%3A%2F%2Fsearch.rakuten.co.jp%2Fsearch%2Fmall%2F%E3%82%B9%E3%83%9D%E3%83%BC%E3%83%84%2F",
    "entertainment": "https://hb.afl.rakuten.co.jp/ichiba/REPLACE_ME/?pc=https%3A%2F%2Fsearch.rakuten.co.jp%2Fsearch%2Fmall%2F%E3%82%A8%E3%83%B3%E3%82%BF%E3%83%A1%2F",
    "tech":          "https://hb.afl.rakuten.co.jp/ichiba/REPLACE_ME/?pc=https%3A%2F%2Fsearch.rakuten.co.jp%2Fsearch%2Fmall%2F%E3%82%AC%E3%82%B8%E3%82%A7%E3%83%83%E3%83%88%2F",
    "fashion":       "https://hb.afl.rakuten.co.jp/ichiba/REPLACE_ME/?pc=https%3A%2F%2Fsearch.rakuten.co.jp%2Fsearch%2Fmall%2F%E3%83%95%E3%82%A1%E3%83%83%E3%82%B7%E3%83%A7%E3%83%B3%2F",
    "food":          "https://hb.afl.rakuten.co.jp/ichiba/REPLACE_ME/?pc=https%3A%2F%2Fsearch.rakuten.co.jp%2Fsearch%2Fmall%2F%E3%82%B0%E3%83%AB%E3%83%A1%2F",
    "travel":        "https://hb.afl.rakuten.co.jp/ichiba/REPLACE_ME/?pc=https%3A%2F%2Ftravel.rakuten.co.jp%2F",
    "health":        "https://hb.afl.rakuten.co.jp/ichiba/REPLACE_ME/?pc=https%3A%2F%2Fsearch.rakuten.co.jp%2Fsearch%2Fmall%2F%E5%81%A5%E5%BA%B7%2F",
    "books":         "https://hb.afl.rakuten.co.jp/ichiba/REPLACE_ME/?pc=https%3A%2F%2Fbooks.rakuten.co.jp%2F",
    "other":         "https://hb.afl.rakuten.co.jp/ichiba/REPLACE_ME/?pc=https%3A%2F%2Fwww.rakuten.co.jp%2F",
    # ▲▲▲ ここまで ▲▲▲
}

# 環境変数で上書き可能（Secrets で管理する場合）
# 例: AFFILIATE_URL_TECH=https://hb.afl.rakuten.co.jp/... を設定すると
#     AFFILIATE_LINKS["tech"] をその値で上書きする。
def _override_from_env() -> None:
    for cat in list(AFFILIATE_LINKS.keys()):
        env_key = f"AFFILIATE_URL_{cat.upper()}"
        val = os.environ.get(env_key, "")
        if val:
            AFFILIATE_LINKS[cat] = val

_override_from_env()

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
    # カテゴリが辞書にない場合は "other" にフォールバック
    normalized = category.lower().strip()
    if normalized not in AFFILIATE_LINKS:
        logger.warning(
            "Unknown affiliate category '%s'. Falling back to 'other'.", category
        )
        normalized = "other"

    base_url = AFFILIATE_LINKS[normalized]
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
