"""
ai_generator.py
---------------
Anthropic Claude API を使って、トレンドワードから X投稿コンテンツを生成する。

モデル: claude-haiku-4-5 — 低レイテンシ・低コスト、SNS文生成に十分な品質
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

try:
    import anthropic as anthropic_sdk
except ImportError:
    anthropic_sdk = None  # type: ignore

from trend_collector import TrendItem

logger = logging.getLogger(__name__)

# X 文字数制限
X_MAX_CHARS     = 140
X_URL_COST      = 23   # t.co 短縮URL 固定コスト
X_NEWLINE_COST  = 1
POST_BODY_LIMIT = X_MAX_CHARS - X_URL_COST - X_NEWLINE_COST  # = 116

VALID_CATEGORIES = {
    "sports", "entertainment", "tech", "fashion",
    "food", "travel", "health", "books", "other",
}

# 6つの viral hook フレームワーク
VALID_HOOK_TYPES = {
    "curiosity",    # 好奇心: 「〜って知ってた？」「実は〜」
    "urgency",      # 緊急性: 「今すぐ〜」「期間限定〜」
    "social_proof", # 社会的証明: 「〜万人が注目」「話題の〜」
    "fomo",         # FOMO: 「見逃すな」「〜だけが知っている」
    "authority",    # 権威: 「専門家が認めた」「〜が証明」
    "emotion",      # 感情: 感動・共感・笑いに訴える
}

_CLAUDE_MODEL = "claude-haiku-4-5"


@dataclass
class GeneratedContent:
    post_text: str
    image_prompt: str
    hashtags: list[str]
    affiliate_category: str
    hook_type: str = "emotion"
    thread_tweet: str = ""
    raw_json: dict = field(default_factory=dict)

    @property
    def post_char_count(self) -> int:
        return _count_x_chars(self.post_text)

    def is_within_limit(self) -> bool:
        return self.post_char_count <= POST_BODY_LIMIT


def _count_x_chars(text: str) -> int:
    """X の文字数カウント: URL は 23 字固定として計算する。"""
    counted = re.sub(r"https?://\S+", "x" * 23, text)
    return len(counted)


def _trim_to_limit(body: str, tags: list[str]) -> str:
    """
    body + "\n" + " ".join(tags) が POST_BODY_LIMIT 以内に収まるよう
    body をトリムして返す。
    """
    tag_str = " ".join(tags)
    tag_cost = (1 + len(tag_str)) if tag_str else 0  # 改行 + タグ

    max_body = POST_BODY_LIMIT - tag_cost

    if _count_x_chars(body) <= max_body:
        return f"{body}\n{tag_str}" if tag_str else body

    trimmed = ""
    budget = max_body - 1  # "…" 分を引く
    for ch in body:
        if _count_x_chars(trimmed + ch) > budget:
            break
        trimmed += ch
    trimmed = trimmed.rstrip() + "…"

    return f"{trimmed}\n{tag_str}" if tag_str else trimmed


def _validate_and_fix(data: dict, keyword: str) -> dict:
    """JSON レスポンスを検証し、不正な値をフォールバック値で補正する。"""
    # post_text
    post_text = data.get("post_text", "")
    if not post_text or not isinstance(post_text, str):
        post_text = f"「{keyword}」が話題です！詳しくはこちら👇"
    post_text = post_text.strip()

    # hashtags
    hashtags = data.get("hashtags", [])
    if not isinstance(hashtags, list) or not hashtags:
        hashtags = [f"#{keyword.replace(' ', '')}"]
    hashtags = [h if h.startswith("#") else f"#{h}" for h in hashtags if h]

    # affiliate_category
    category = data.get("affiliate_category", "other")
    if not isinstance(category, str) or category.lower() not in VALID_CATEGORIES:
        category = "other"
    else:
        category = category.lower()

    # image_prompt
    image_prompt = data.get("image_prompt", "")
    if not image_prompt or not isinstance(image_prompt, str):
        image_prompt = f"Trending topic in Japan: {keyword}, photorealistic, 8k"

    # hook_type
    hook_type = data.get("hook_type", "emotion")
    if not isinstance(hook_type, str) or hook_type.lower() not in VALID_HOOK_TYPES:
        hook_type = "emotion"
    else:
        hook_type = hook_type.lower()

    # thread_tweet (optional)
    thread_tweet = data.get("thread_tweet", "")
    if not isinstance(thread_tweet, str):
        thread_tweet = ""

    return {
        "post_text":          post_text,
        "image_prompt":       image_prompt,
        "hashtags":           hashtags,
        "affiliate_category": category,
        "hook_type":          hook_type,
        "thread_tweet":       thread_tweet,
    }


def _build_prompt(trend: TrendItem) -> str:
    news_lines = "\n".join(
        f"  - [{n.source}] {n.title}" for n in trend.news_items[:3]
    )
    news_section = f"\n関連ニュース:\n{news_lines}" if news_lines else ""

    return f"""あなたはXアフィリエイトマーケターです。
以下のトレンドについて、Xへの投稿テキストと画像プロンプトを生成してください。

トレンドキーワード: {trend.keyword}
検索量: {trend.approx_traffic}{news_section}

以下の6つのviral hookフレームワークのいずれかを選び、そのフックを使った投稿を作成してください:
- curiosity  : 好奇心を刺激 (「〜って知ってた？」「実は〜」)
- urgency    : 緊急性・限定感 (「今すぐ〜」「期間限定〜」)
- social_proof: 社会的証明 (「〜万人が注目」「話題の〜」)
- fomo       : 機会損失への恐れ (「見逃すな」「〜だけが知っている」)
- authority  : 権威・専門性 (「専門家が認めた」「〜が証明」)
- emotion    : 感情に訴える (感動・共感・ユーモアなど)

以下のJSONを生成してください（マークダウンコードブロックなし・生JSONのみ）:
{{
  "post_text": "投稿本文（ハッシュタグを含む・{POST_BODY_LIMIT}字以内）",
  "image_prompt": "英語の画像生成プロンプト（Photorealistic/8k等のキーワード含む）",
  "hashtags": ["#タグ1", "#タグ2", "#タグ3"],
  "affiliate_category": "sports|entertainment|tech|fashion|food|travel|health|books|other のいずれか",
  "hook_type": "curiosity|urgency|social_proof|fomo|authority|emotion のいずれか",
  "thread_tweet": "スレッド2ツイート目の文章（省略可・空文字OK）"
}}

制約:
- post_text は {POST_BODY_LIMIT} 字以内（ハッシュタグを含む）
- hashtags は 2〜5個
- affiliate_category はトレンドに最も近いカテゴリを選ぶ
- hook_type は選んだフレームワーク名を正確に記入する
- 炎上リスクの高い内容（政治・訃報・事件）は避ける
- 読者の関心を引くトーンで、自然な日本語で書く"""


def generate_post_content(
    trend: TrendItem,
    api_key: Optional[str] = None,
) -> GeneratedContent:
    """
    Anthropic Claude API を呼び出してトレンドから投稿コンテンツを生成する。

    Parameters
    ----------
    trend   : TrendItem（キーワード・ニュース情報）
    api_key : Anthropic API キー（省略時は環境変数 ANTHROPIC_API_KEY）

    Returns
    -------
    GeneratedContent
    """
    if anthropic_sdk is None:
        raise ImportError("anthropic がインストールされていません: pip install anthropic")

    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY が設定されていません")

    client = anthropic_sdk.Anthropic(api_key=key)
    prompt = _build_prompt(trend)
    logger.info("Anthropic API 呼び出し: model=%s keyword=%s", _CLAUDE_MODEL, trend.keyword)

    try:
        response = client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic_sdk.RateLimitError as e:
        retry_after = e.response.headers.get("retry-after", "?") if e.response else "?"
        logger.error("Anthropic API error (rate limit): retry-after=%s %s", retry_after, e)
        raise RuntimeError(
            f"Anthropic API レート制限超過。{retry_after}秒後に再試行してください。"
        ) from e
    except anthropic_sdk.AuthenticationError as e:
        logger.error("Anthropic API error (authentication): %s", e)
        raise RuntimeError("Anthropic API 認証エラー: ANTHROPIC_API_KEY を確認してください。") from e
    except anthropic_sdk.APIStatusError as e:
        logger.error("Anthropic API error (status=%s): %s", e.status_code, e.message)
        raise RuntimeError(
            f"Anthropic API エラー (HTTP {e.status_code}): {e.message}"
        ) from e
    except anthropic_sdk.APIConnectionError as e:
        logger.error("Anthropic API connection error: %s", e)
        raise RuntimeError(f"Anthropic API 接続エラー: {e}") from e

    raw_text = next(
        (block.text for block in response.content if block.type == "text"), ""
    ).strip()

    # コードブロック除去
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
    raw_text = re.sub(r"\s*```$", "", raw_text)

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.warning("JSONパース失敗 (%s): %s", e, raw_text[:200])
        data = {}

    fixed = _validate_and_fix(data, trend.keyword)

    # タグが post_text に含まれていなければ結合
    post_text = fixed["post_text"]
    hashtags  = fixed["hashtags"]
    if not any(h in post_text for h in hashtags):
        post_text = _trim_to_limit(post_text, hashtags)
    else:
        if _count_x_chars(post_text) > POST_BODY_LIMIT:
            post_text = _trim_to_limit(post_text, [])

    # CTA 品質チェック
    _CTA_KEYWORDS = ["リンク", "チェック", "詳しくは", "購入", "はこちら", "もっと", "今すぐ", "試して", "おすすめ", "必見"]
    if not any(kw in post_text for kw in _CTA_KEYWORDS):
        logger.warning("CTA が弱い可能性があります。post_text にクリック誘導フレーズが含まれていません。")

    logger.info(
        "生成完了: %d字 category=%s hook=%s",
        _count_x_chars(post_text), fixed["affiliate_category"], fixed["hook_type"],
    )

    return GeneratedContent(
        post_text=post_text,
        image_prompt=fixed["image_prompt"],
        hashtags=hashtags,
        affiliate_category=fixed["affiliate_category"],
        hook_type=fixed["hook_type"],
        thread_tweet=fixed["thread_tweet"],
        raw_json=fixed,
    )
