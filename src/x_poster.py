"""X API v2 を使ってツイートを投稿する。"""

import os
import tweepy


def _get_client() -> tweepy.Client:
    required = {
        "X_API_KEY": os.getenv("X_API_KEY"),
        "X_API_SECRET": os.getenv("X_API_SECRET"),
        "X_ACCESS_TOKEN": os.getenv("X_ACCESS_TOKEN"),
        "X_ACCESS_TOKEN_SECRET": os.getenv("X_ACCESS_TOKEN_SECRET"),
        "X_BEARER_TOKEN": os.getenv("X_BEARER_TOKEN"),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise ValueError(f"環境変数が不足しています: {', '.join(missing)}")

    return tweepy.Client(
        bearer_token=required["X_BEARER_TOKEN"],
        consumer_key=required["X_API_KEY"],
        consumer_secret=required["X_API_SECRET"],
        access_token=required["X_ACCESS_TOKEN"],
        access_token_secret=required["X_ACCESS_TOKEN_SECRET"],
    )


def post_tweet(text: str, media_id: str | None = None) -> str:
    """ツイートを投稿して tweet_id を返す。

    Args:
        text: ツイート本文（URLを含む最終テキスト）
        media_id: X v1.1 でアップロード済みの media_id（省略可）

    Returns:
        投稿されたツイートの ID
    """
    client = _get_client()
    kwargs: dict = {"text": text}
    if media_id:
        kwargs["media_ids"] = [media_id]

    response = client.create_tweet(**kwargs)
    return str(response.data["id"])
