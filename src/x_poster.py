"""
x_poster.py
-----------
X API v2 (tweepy.Client.create_tweet) でツイートを投稿するモジュール。

投稿フォーマット（通常）:
  {post_text（ハッシュタグ含む・116字以内）}
  {affiliate_url}

スレッドモード（--thread）:
  Tweet 1: 上記と同じ（画像付き）
  Tweet 2: thread_tweet（アフィリエイト商品の深掘り + URL）
  → スレッドはエンゲージメントを3〜5倍に高める
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
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

DEFAULT_POSTS_PER_RUN = int(os.environ.get("POSTS_PER_RUN", "1"))

# =====================================================================
# データクラス
# =====================================================================

@dataclass
class PostResult:
    tweet_id: str
    tweet_url: str
    full_text: str
    media_id: Optional[str]
    affiliate_url: str
    char_count: int


@dataclass
class ThreadPostResult:
    """スレッド投稿の結果。main + replies の PostResult を保持する。"""
    main: PostResult
    replies: list[PostResult] = field(default_factory=list)

    @property
    def tweet_url(self) -> str:
        return self.main.tweet_url

    @property
    def all_tweet_urls(self) -> list[str]:
        return [self.main.tweet_url] + [r.tweet_url for r in self.replies]


# =====================================================================
# ツイート本文の構築
# =====================================================================

def build_tweet_text(
    content: GeneratedContent,
    affiliate_link: AffiliateLink,
) -> str:
    """
    メインツイート本文を組み立てる。

    フォーマット:
      {post_text}
      {affiliate_url}

    post_text は ai_generator で 116字制限済み。
    改行 + URL で +24字 → 合計 140字以内。
    """
    return f"{content.post_text}\n{affiliate_link.url}"


def build_thread_reply_text(
    content: GeneratedContent,
    affiliate_link: AffiliateLink,
) -> str:
    """
    スレッド2枚目テキストを組み立てる。

    thread_tweet が生成されていればそれを使い、末尾にアフィリエイトURLを追記する。
    生成されていない場合はデフォルトのCTAを使う。
    """
    body = content.thread_tweet or (
        f"👇 {affiliate_link.display_label}\n"
        f"気になった方はチェックしてみてください！"
    )

    candidate = f"{body}\n{affiliate_link.url}"
    counted = re.sub(r"https?://\S+", "x" * 23, candidate)
    if len(counted) <= 140:
        return candidate

    # URLを付けると超過する場合はbodyをトリム
    max_body = 140 - 23 - 1  # URL + 改行
    trimmed = ""
    for ch in body:
        if len(re.sub(r"https?://\S+", "x" * 23, trimmed + ch)) > max_body:
            break
        trimmed += ch
    return f"{trimmed.rstrip()}…\n{affiliate_link.url}"


def _count_x_chars(text: str) -> int:
    return len(re.sub(r"https?://\S+", "x" * 23, text))


def _validate_tweet_length(text: str, max_chars: int = 140) -> bool:
    char_count = _count_x_chars(text)
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
    return tweepy.Client(
        bearer_token=bearer_token,
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
        wait_on_rate_limit=True,
    )


def _load_x_credentials() -> dict[str, str]:
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
        if not val and param != "bearer_token":
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
    retry=retry_if_exception_type(tweepy.errors.TweepyException),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=10, max=60),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def _create_tweet(
    client: tweepy.Client,
    text: str,
    media_ids: Optional[list[str]] = None,
    reply_to_tweet_id: Optional[str] = None,
) -> tweepy.Response:
    """
    X API v2 の create_tweet を呼び出す。
    TweepyException はリトライ対象。
    reply_to_tweet_id を指定するとそのツイートへのリプライ（スレッド）になる。
    """
    kwargs: dict = {
        "text": text,
        "user_auth": True,
    }
    if media_ids:
        kwargs["media_ids"] = media_ids
    if reply_to_tweet_id:
        kwargs["in_reply_to_tweet_id"] = reply_to_tweet_id

    logger.info(
        "Calling X API v2 create_tweet (media_ids=%s reply_to=%s)...",
        media_ids, reply_to_tweet_id,
    )
    return client.create_tweet(**kwargs)


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
    コンテンツとアフィリエイトリンクを組み合わせてXに投稿する（単発ツイート）。
    """
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

    tweet_text = build_tweet_text(content, affiliate_link)
    _validate_tweet_length(tweet_text)

    logger.info("=== 投稿内容プレビュー ===")
    logger.info("hook_type: %s", content.hook_type)
    logger.info("文字数  : %d字", _count_x_chars(tweet_text))
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
            char_count=_count_x_chars(tweet_text),
        )

    client = _build_tweepy_v2_client(**creds)

    try:
        response = _create_tweet(
            client=client,
            text=tweet_text,
            media_ids=[media_id] if media_id else None,
        )
    except tweepy.errors.Forbidden as e:
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
        char_count=_count_x_chars(tweet_text),
    )


def post_thread_to_x(
    content: GeneratedContent,
    affiliate_link: AffiliateLink,
    media_id: Optional[str] = None,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    access_token: Optional[str] = None,
    access_token_secret: Optional[str] = None,
    bearer_token: Optional[str] = None,
    dry_run: bool = False,
) -> ThreadPostResult:
    """
    スレッド形式で投稿する（エンゲージメント最大化）。

    Tweet 1: メイン投稿（画像付き）+ アフィリエイトURL
    Tweet 2: thread_tweet（商品詳細・CTA）

    X の Free 枠は 50ツイート/24h なので、スレッドは2枚目まで。
    """
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

    # ---- Tweet 1: メイン ----
    main_text = build_tweet_text(content, affiliate_link)
    reply_text = build_thread_reply_text(content, affiliate_link)

    _validate_tweet_length(main_text)
    _validate_tweet_length(reply_text)

    logger.info("=== スレッド投稿プレビュー ===")
    logger.info("hook_type: %s", content.hook_type)
    logger.info("[1/2] %d字:\n%s", _count_x_chars(main_text), main_text)
    logger.info("[2/2] %d字:\n%s", _count_x_chars(reply_text), reply_text)
    logger.info("media_id: %s", media_id or "(なし)")

    if dry_run:
        logger.info("[DRY RUN] スレッド投稿をスキップしました。")
        main_result = PostResult(
            tweet_id="dry_run_main",
            tweet_url="https://x.com/dry_run/main",
            full_text=main_text,
            media_id=media_id,
            affiliate_url=affiliate_link.url,
            char_count=_count_x_chars(main_text),
        )
        reply_result = PostResult(
            tweet_id="dry_run_reply",
            tweet_url="https://x.com/dry_run/reply",
            full_text=reply_text,
            media_id=None,
            affiliate_url=affiliate_link.url,
            char_count=_count_x_chars(reply_text),
        )
        return ThreadPostResult(main=main_result, replies=[reply_result])

    client = _build_tweepy_v2_client(**creds)

    try:
        main_resp = _create_tweet(
            client=client,
            text=main_text,
            media_ids=[media_id] if media_id else None,
        )
    except tweepy.errors.Forbidden as e:
        logger.error("403 Forbidden (Tweet 1): %s", e)
        raise

    main_id  = main_resp.data["id"]
    main_url = f"https://x.com/i/web/status/{main_id}"
    logger.info("Tweet 1 投稿成功: %s", main_url)

    main_result = PostResult(
        tweet_id=main_id,
        tweet_url=main_url,
        full_text=main_text,
        media_id=media_id,
        affiliate_url=affiliate_link.url,
        char_count=_count_x_chars(main_text),
    )

    # ---- Tweet 2: リプライ（スレッド） ----
    replies: list[PostResult] = []
    try:
        reply_resp = _create_tweet(
            client=client,
            text=reply_text,
            reply_to_tweet_id=main_id,
        )
        reply_id  = reply_resp.data["id"]
        reply_url = f"https://x.com/i/web/status/{reply_id}"
        logger.info("Tweet 2 (スレッド) 投稿成功: %s", reply_url)
        replies.append(PostResult(
            tweet_id=reply_id,
            tweet_url=reply_url,
            full_text=reply_text,
            media_id=None,
            affiliate_url=affiliate_link.url,
            char_count=_count_x_chars(reply_text),
        ))
    except Exception as e:
        logger.warning("Tweet 2 (スレッド) 投稿失敗（メインツイートは成功）: %s", e)

    return ThreadPostResult(main=main_result, replies=replies)
