"""
ai_generator.py
---------------
Google Gemini API を使って、トレンドワードから X投稿コンテンツを生成する。

バイラル戦略:
  - 5種類のウイルス性テンプレートからトレンドに最適なものを自動選択
  - フック先行型ライティング（最初の8文字で勝負が決まる）
  - 感情トリガー語彙を積極使用
  - スレッド用の2枚目ツイートも同時生成

無料枠: gemini-1.5-flash — 15 RPM / 1,500 RPD / 1M TPM
"""
from __future__ import annotations

import json
import logging
import os
import random
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

VALID_HOOK_TYPES = {
    "shocking_fact", "question_hook", "tips_hack",
    "fomo", "community", "prediction",
}

_GEMINI_MODEL = "gemini-1.5-flash"

# バイラル率の高い絵文字セット（フォーマット別）
_HOOK_EMOJIS = {
    "shocking_fact": ["🚨", "😱", "⚠️", "🔥", "💥"],
    "question_hook": ["🤔", "❓", "💭", "👀", "🙋"],
    "tips_hack":     ["💡", "✅", "🎯", "📌", "⚡"],
    "fomo":          ["⏰", "🔔", "👇", "🙏", "✨"],
    "community":     ["🙌", "💬", "👥", "❤️", "🫶"],
    "prediction":    ["🔮", "📈", "🚀", "🎯", "⭐"],
}


@dataclass
class GeneratedContent:
    post_text: str
    image_prompt: str
    hashtags: list[str]
    affiliate_category: str
    hook_type: str = "shocking_fact"
    thread_tweet: Optional[str] = None   # スレッド2枚目（任意）
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
    tag_cost = (1 + len(tag_str)) if tag_str else 0

    max_body = POST_BODY_LIMIT - tag_cost

    if _count_x_chars(body) <= max_body:
        return f"{body}\n{tag_str}" if tag_str else body

    trimmed = ""
    budget = max_body - 1  # "…" 分
    for ch in body:
        if _count_x_chars(trimmed + ch) > budget:
            break
        trimmed += ch
    trimmed = trimmed.rstrip() + "…"

    return f"{trimmed}\n{tag_str}" if tag_str else trimmed


def _validate_and_fix(data: dict, keyword: str) -> dict:
    """Gemini の JSON レスポンスを検証し、不正な値をフォールバック値で補正する。"""
    post_text = data.get("post_text", "")
    if not post_text or not isinstance(post_text, str):
        post_text = f"🔥「{keyword}」が今ヤバい！詳しくはこちら👇"
    post_text = post_text.strip()

    hashtags = data.get("hashtags", [])
    if not isinstance(hashtags, list) or not hashtags:
        hashtags = [f"#{keyword.replace(' ', '')}"]
    hashtags = [h if h.startswith("#") else f"#{h}" for h in hashtags if h]

    category = data.get("affiliate_category", "other")
    if not isinstance(category, str) or category.lower() not in VALID_CATEGORIES:
        category = "other"
    else:
        category = category.lower()

    image_prompt = data.get("image_prompt", "")
    if not image_prompt or not isinstance(image_prompt, str):
        image_prompt = (
            f"Bold eye-catching social media image about '{keyword}', "
            "vivid colors, dramatic lighting, text overlay space, trending Japan, "
            "high contrast, 4k sharp"
        )

    hook_type = data.get("hook_type", "shocking_fact")
    if hook_type not in VALID_HOOK_TYPES:
        hook_type = "shocking_fact"

    thread_tweet = data.get("thread_tweet")
    if thread_tweet and not isinstance(thread_tweet, str):
        thread_tweet = None
    if thread_tweet:
        thread_tweet = thread_tweet.strip()
        if len(thread_tweet) > X_MAX_CHARS:
            thread_tweet = thread_tweet[:X_MAX_CHARS - 1] + "…"

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

    return f"""あなたは日本のXでバズらせるプロのコピーライターです。
以下のトレンドについて、エンゲージメント最大化を目的としたXポストを生成してください。

トレンドキーワード: {trend.keyword}
検索量: {trend.approx_traffic}{news_section}

## バイラルフォーマット（最も効果的なものを1つ選択）

1. **shocking_fact（衝撃系）**
   「😱 え、{trend.keyword}って実は〇〇だった件」「🚨 知らないと損する○○の真実」
   → 驚きと「え！そうなの？」という反応を狙う。最もシェアされやすい。

2. **question_hook（問いかけ系）**
   「🤔 {trend.keyword}って知ってる？実は...」「あなたは○○派？△△派？」
   → リプライとRTを同時に促す。エンゲージメント率が高い。

3. **tips_hack（裏技・ヒント系）**
   「💡 {trend.keyword}を200%活用する方法」「✅ やっている人だけが知る○○テク」
   → 保存されやすい・有益感が高い。

4. **fomo（FOMO・今すぐ感）**
   「⏰ {trend.keyword}に乗り遅れた人へ」「🔔 今だけ！○○が変わる最後のチャンス」
   → 今すぐ行動させる緊急性。CTRが高い。

5. **community（共感・コミュニティ系）**
   「○○な人RT」「{trend.keyword}好きな人と繋がりたい🙌」「わかりすぎる○○あるある」
   → RTとフォローを直接促す。拡散力が最も高い。

6. **prediction（予言・トレンド予測系）**
   「🔮 {trend.keyword}は絶対これから来る」「📈 半年後に後悔しないために今○○すべき理由」
   → 専門家感・先取り感。保存・引用RTが多い。

## 制約（必ず守ること）
- post_text の最初の8〜15文字が最重要。スクロールを止めるフックを入れる
- 感情を動かす語彙を積極使用: 衝撃・ヤバい・神・最強・完全無料・実は・知らないと損・絶対
- post_text は {POST_BODY_LIMIT} 字以内（ハッシュタグ含む）
- hashtags は 2〜4個（多すぎるとスパム判定される）
- 炎上リスクの高い内容（政治・訃報・事件）は絶対に避ける
- thread_tweet は140字以内で、main tweetの「続き」として商品価値を掘り下げる内容

## 画像プロンプト指針
- ビビッドカラー・高コントラスト・テキストオーバーレイスペースあり
- "eye-catching", "bold", "viral social media" を必ず含める
- 具体的なシーン・構図を指定する（"close-up", "dramatic", etc.）

以下のJSONを生成してください（マークダウンコードブロックなし・生JSONのみ）:
{{
  "hook_type": "上記6種類のいずれか",
  "post_text": "投稿本文（最初の15字で読者を掴む・ハッシュタグ含む・{POST_BODY_LIMIT}字以内）",
  "thread_tweet": "スレッド2枚目のテキスト（アフィリエイト商品の価値・140字以内）",
  "image_prompt": "英語の画像生成プロンプト（eye-catching/bold/viral social media必須）",
  "hashtags": ["#タグ1", "#タグ2", "#タグ3"],
  "affiliate_category": "sports|entertainment|tech|fashion|food|travel|health|books|other"
}}"""


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

    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
    raw_text = re.sub(r"\s*```$", "", raw_text)

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.warning("JSONパース失敗 (%s): %s", e, raw_text[:200])
        data = {}

    fixed = _validate_and_fix(data, trend.keyword)

    post_text = fixed["post_text"]
    hashtags  = fixed["hashtags"]
    if not any(h in post_text for h in hashtags):
        post_text = _trim_to_limit(post_text, hashtags)
    else:
        if _count_x_chars(post_text) > POST_BODY_LIMIT:
            post_text = _trim_to_limit(post_text, [])

    logger.info(
        "生成完了: %d字 hook=%s category=%s thread=%s",
        _count_x_chars(post_text),
        fixed["hook_type"],
        fixed["affiliate_category"],
        "あり" if fixed.get("thread_tweet") else "なし",
    )

    return GeneratedContent(
        post_text=post_text,
        image_prompt=fixed["image_prompt"],
        hashtags=hashtags,
        affiliate_category=fixed["affiliate_category"],
        hook_type=fixed["hook_type"],
        thread_tweet=fixed.get("thread_tweet"),
        raw_json=fixed,
    )
