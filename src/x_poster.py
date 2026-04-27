"""
x_poster.py
-----------
X API v2 (tweepy.Client.create_tweet) でツイートを投稿するモジュール。

投稿フォーマット:
  {post_text（ハッシュタグ含む・116字以内）}
  {affiliate_url}

  → 合計で140字以内に収まる設計（URLはt.co短縮で23字固定）
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import tweepy
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from ai_generator import GeneratedContent
from affiliate import AffiliateLink

logger = logging.getLogger(__name__)

# =====================================================================
# 定数
# =====================================================================

# X 無料枠: 50ツイート/24時間
# GitHub Actions で1日3回実行する場合 1回あたり POSTS_PER_RUN=1 を推奨
DEFAULT_POSTS_PER_RUN = int(os.environ.get("POSTS_PER_RUN", "1"))

# =====================================================================
# データクラス
# =====================================================================

@dataclass
class PostResult:
    tweet_id: str
    tweet_url: str
    full_text: str          # 実際に投稿したテキスト全文
    media_id: Optional[str]
    affiliate_url: str
    char_count: int


# =====================================================================
# ツイート本文の構築
# =====================================================================

def build_tweet_text(
    content: GeneratedContent,
    affiliate_link: AffiliateLink,
) -> str:
    """
    投稿テキストを組み立てる。

    フォーマット:
      {post_text}
      {affiliate_url}

    post_text は ai_generator で 116字制限済み。
    改行 + URL で +24字 → 合計 140字以内。
    """
    return f"{content.post_text}\n{affiliate_link.url}"


def _validate_tweet_length(text: str, max_chars: int = 140) -> bool:
    """
    X の文字数カウント基準で制限内か確認する。
    URLは23字固定でカウントするため、URL部分を23字に置き換えて評価。
    """
    import re
    # URL を 23字のプレースホルダに置換して計算
    url_pattern = r"https?://\S+"
    counted_text = re.sub(url_pattern, "x" * 23, text)
    char_count = len(counted_text)
    if char_count > max_chars:
        logger.warning(
            "Tweet length %d > %d. Text may be truncated by X.",
            char_count, max_chars,
        )
        return False
    return True


# =====================================================================
# tweepy Client (v2) の初期化
# =====================================================================

def _build_tweepy_v2_client(
    api_key: str,
    api_secret: str,
    access_token: str,
    access_token_secret: str,
    bearer_token: Optional[str] = None,
) -> tweepy.Client:
    """
    OAuth 1.0a 認証済みの tweepy.Client (v2) を返す。
    user_auth=True にするため consumer_key/secret + access_token が必要。
    """
    return tweepy.Client(
        bearer_token=bearer_token,
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
        wait_on_rate_limit=True,
    )


def _load_x_credentials() -> dict[str, str]:
    """環境変数から X 認証情報を読み込む。不足があれば EnvironmentError。"""
    keys = {
        "api_key":              "X_API_KEY",
        "api_secret":           "X_API_SECRET",
        "access_token":         "X_ACCESS_TOKEN",
        "access_token_secret":  "X_ACCESS_TOKEN_SECRET",
        "bearer_token":         "X_BEARER_TOKEN",
    }
    creds: dict[str, str] = {}
    missing: list[str] = []

    for param, env_var in keys.items():
        val = os.environ.get(env_var, "")
        if not val and param != "bearer_token":   # bearer_token はオプション
            missing.append(env_var)
        creds[param] = val

    if missing:
        raise EnvironmentError(
            f"X API 認証情報が不足: {missing}\n"
            ".env または GitHub Secrets に設定してください。"
        )
    return creds


# =====================================================================
# 投稿処理
# =====================================================================

@retry(
    # 429 (Too Many Requests) と 503 は自動リトライ
    retry=retry_if_exception_type(tweepy.errors.TweepyException),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=10, max=60),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def _create_tweet(
    client: tweepy.Client,
    text: str,
    media_ids: Optional[list[str]] = None,
) -> tweepy.Response:
    """
    X API v2 の create_tweet を呼び出す。
    TweepyException はリトライ対象。
    403 (Forbidden) はリトライしても無駄なので上位で除外する。
    """
    kwargs: dict = {
        "text": text,
        "user_auth": True,   # OAuth 1.0a を使うために必須
    }
    if media_ids:
        kwargs["media_ids"] = media_ids

    logger.info("Calling X API v2 create_tweet (media_ids=%s)...", media_ids)
    response = client.create_tweet(**kwargs)
    return response


def post_to_x(
    content: GeneratedContent,
    affiliate_link: AffiliateLink,
    media_id: Optional[str] = None,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    access_token: Optional[str] = None,
    access_token_secret: Optional[str] = None,
    bearer_token: Optional[str] = None,
    dry_run: bool = False,
) -> PostResult:
    """
    コンテンツとアフィリエイトリンクを組み合わせてXに投稿する。

    Parameters
    ----------
    content           : GeneratedContent (text, hashtags, category)
    affiliate_link    : AffiliateLink
    media_id          : X v1.1 でアップロード済みの media_id_string
    api_key/secret/.. : 認証情報（省略時は環境変数から取得）
    dry_run           : True のとき実際に投稿せずテキストだけ返す

    Returns
    -------
    PostResult
    """
    # ---- 認証情報の解決 ----
    creds = {
        "api_key":             api_key             or os.environ.get("X_API_KEY", ""),
        "api_secret":          api_secret          or os.environ.get("X_API_SECRET", ""),
        "access_token":        access_token        or os.environ.get("X_ACCESS_TOKEN", ""),
        "access_token_secret": access_token_secret or os.environ.get("X_ACCESS_TOKEN_SECRET", ""),
        "bearer_token":        bearer_token        or os.environ.get("X_BEARER_TOKEN", ""),
    }
    required = ["api_key", "api_secret", "access_token", "access_token_secret"]
    missing = [k for k in required if not creds[k]]
    if missing and not dry_run:
        raise EnvironmentError(f"X 認証情報が不足: {missing}")

    # ---- ツイート本文の構築 ----
    tweet_text = build_tweet_text(content, affiliate_link)
    _validate_tweet_length(tweet_text)

    logger.info("=== 投稿内容プレビュー ===")
    logger.info("文字数  : %d字（URL23字固定換算）", len(tweet_text.replace(affiliate_link.url, "x" * 23)))
    logger.info("本文    :\n%s", tweet_text)
    logger.info("media_id: %s", media_id or "(なし)")

    if dry_run:
        logger.info("[DRY RUN] 実際の投稿はスキップしました。")
        return PostResult(
            tweet_id="dry_run_id",
            tweet_url="https://x.com/dry_run",
            full_text=tweet_text,
            media_id=media_id,
            affiliate_url=affiliate_link.url,
            char_count=len(tweet_text),
        )

    # ---- 実際の投稿 ----
    client = _build_tweepy_v2_client(**creds)

    try:
        response = _create_tweet(
            client=client,
            text=tweet_text,
            media_ids=[media_id] if media_id else None,
        )
    except tweepy.errors.Forbidden as e:
        # 403: アプリ権限不足・重複ツイート等は即失敗（リトライ不要）
        logger.error(
            "403 Forbidden: %s\n"
            "確認事項: X Developer Portal でアプリの Read+Write 権限が有効か確認してください。",
            e,
        )
        raise

    tweet_id  = response.data["id"]
    tweet_url = f"https://x.com/i/web/status/{tweet_id}"

    logger.info("投稿成功: tweet_id=%s url=%s", tweet_id, tweet_url)

    return PostResult(
        tweet_id=tweet_id,
        tweet_url=tweet_url,
        full_text=tweet_text,
        media_id=media_id,
        affiliate_url=affiliate_link.url,
        char_count=len(tweet_text),
    )
