"""カテゴリに応じたアフィリエイトリンクを返す。

使い方:
  1. 下記 AFFILIATE_LINKS の各 URL を実際のアフィリエイトURLに書き換えてください。
  2. 楽天アフィリエイトの場合は .env の RAKUTEN_AFFILIATE_ID も設定してください。
"""

import os

# カテゴリ → アフィリエイトURL のマッピング
# REPLACE_ME を実際のアフィリエイトURLで置き換えてください
AFFILIATE_LINKS: dict[str, str] = {
    "sports":    "https://REPLACE_ME/sports",
    "tech":      "https://REPLACE_ME/tech",
    "beauty":    "https://REPLACE_ME/beauty",
    "food":      "https://REPLACE_ME/food",
    "fashion":   "https://REPLACE_ME/fashion",
    "travel":    "https://REPLACE_ME/travel",
    "lifestyle": "https://REPLACE_ME/lifestyle",
    "other":     "https://REPLACE_ME/other",
}

_FALLBACK_URL = "https://REPLACE_ME"


def get_link(category: str) -> str:
    """カテゴリに対応するアフィリエイトURLを返す。未設定カテゴリはフォールバックURLを返す。"""
    rakuten_id = os.getenv("RAKUTEN_AFFILIATE_ID", "")
    url = AFFILIATE_LINKS.get(category, _FALLBACK_URL)

    # 楽天IDが設定されていれば query param として付与
    if rakuten_id and "REPLACE_ME" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}aid={rakuten_id}"

    return url


def is_configured(category: str) -> bool:
    """指定カテゴリのURLが実際に設定済みか確認する。"""
    url = AFFILIATE_LINKS.get(category, _FALLBACK_URL)
    return "REPLACE_ME" not in url
