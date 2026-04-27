"""Gemini API を使ってトレンドワードからツイート文・画像プロンプト・カテゴリを生成する。"""

import os
import json
import re
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential

_MODEL = "gemini-1.5-flash"

_SYSTEM_PROMPT = """あなたはXのアフィリエイトマーケターです。
与えられたトレンドワードに関連する日本語の投稿を作成してください。

必ずJSON形式で返してください:
{
  "tweet": "ツイート本文（ハッシュタグ含む、140字以内）",
  "image_prompt": "画像生成用の英語プロンプト（明るくポジティブな内容）",
  "category": "sports|tech|beauty|food|fashion|travel|lifestyle|other のいずれか"
}

ルール:
- tweet は140字以内（URLは含めない。URLは後から追加）
- 明るく・役立つ内容にする
- 炎上リスクがある内容は書かない
- ハッシュタグは2〜3個
- image_prompt は英語で明るいビジュアルを描写する
"""


def _configure():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY が設定されていません")
    genai.configure(api_key=api_key)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def generate(trend_keyword: str) -> dict:
    """トレンドワードからツイート情報を生成して dict で返す。

    Returns:
        {"tweet": str, "image_prompt": str, "category": str}
    """
    _configure()
    model = genai.GenerativeModel(_MODEL)
    prompt = f"{_SYSTEM_PROMPT}\n\nトレンドワード: {trend_keyword}"
    response = model.generate_content(prompt)
    raw = response.text.strip()

    # コードブロックを除去
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    data = json.loads(raw)
    return {
        "tweet": data.get("tweet", ""),
        "image_prompt": data.get("image_prompt", ""),
        "category": data.get("category", "other"),
    }
