"""
ai_generator.py
---------------
Google Gemini API を使って、トレンドワードから X投稿コンテンツを生成する。

無料枠: gemini-1.5-flash — 15 RPM / 1,500 RPD / 1M TPM
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

try:
    import google.generativeai as genai
except ImportError:
    genai = None  # type: ignore

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

_GEMINI_MODEL = "gemini-1.5-flash"


@dataclass
class GeneratedContent:
    post_text: str
    image_prompt: str
    hashtags: list[str]
    affiliate_category: str
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

    # body をトリム（省略記号 "…" で1字）
    trimmed = ""
    budget = max_body - 1  # "…" 分を引く
    for ch in body:
        cost = 1
        if _count_x_chars(trimmed + ch) > budget:
            break
        trimmed += ch
    trimmed = trimmed.rstrip() + "…"

    return f"{trimmed}\n{tag_str}" if tag_str else trimmed


def _validate_and_fix(data: dict, keyword: str) -> dict:
    """
    Gemini の JSON レスポンスを検証し、不正な値をフォールバック値で補正する。
    """
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

    return {
        "post_text":          post_text,
        "image_prompt":       image_prompt,
        "hashtags":           hashtags,
        "affiliate_category": category,
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

以下のJSONを生成してください（マークダウンコードブロックなし・生JSONのみ）:
{{
  "post_text": "投稿本文（ハッシュタグを含む・{POST_BODY_LIMIT}字以内）",
  "image_prompt": "英語の画像生成プロンプト（Photorealistic/8k等のキーワード含む）",
  "hashtags": ["#タグ1", "#タグ2", "#タグ3"],
  "affiliate_category": "sports|entertainment|tech|fashion|food|travel|health|books|other のいずれか"
}}

制約:
- post_text は {POST_BODY_LIMIT} 字以内（ハッシュタグを含む）
- hashtags は 2〜5個
- affiliate_category はトレンドに最も近いカテゴリを選ぶ
- 炎上リスクの高い内容（政治・訃報・事件）は避ける
- 読者の関心を引くトーンで、自然な日本語で書く"""


def generate_post_content(
    trend: TrendItem,
    api_key: Optional[str] = None,
) -> GeneratedContent:
    """
    Gemini API を呼び出してトレンドから投稿コンテンツを生成する。

    Parameters
    ----------
    trend   : TrendItem（キーワード・ニュース情報）
    api_key : Gemini API キー（省略時は環境変数 GEMINI_API_KEY）

    Returns
    -------
    GeneratedContent
    """
    key = api_key or os.environ.get("GEMINI_API_KEY", "")

    if genai is None:
        raise ImportError("google-generativeai がインストールされていません: pip install google-generativeai")

    genai.configure(api_key=key)
    model = genai.GenerativeModel(_GEMINI_MODEL)

    prompt = _build_prompt(trend)
    logger.info("Gemini API 呼び出し: keyword=%s", trend.keyword)

    response = model.generate_content(prompt)
    raw_text = response.text.strip()

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

    logger.info(
        "生成完了: %d字 category=%s", _count_x_chars(post_text), fixed["affiliate_category"]
    )

    return GeneratedContent(
        post_text=post_text,
        image_prompt=fixed["image_prompt"],
        hashtags=hashtags,
        affiliate_category=fixed["affiliate_category"],
        raw_json=fixed,
    )
