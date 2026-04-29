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
import random
import re
from dataclasses import dataclass, field
from typing import Literal, Optional

# 投稿種別: "normal"=テック情報のみ / "affiliate"=アフィリリンク付き
PostMode = Literal["normal", "affiliate"]

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

# viral hook フレームワーク一覧
VALID_HOOK_TYPES = {
    "curiosity",    # 好奇心: 「〜って知ってた？」「実は〜」
    "urgency",      # 緊急性: 「今すぐ〜」「期間限定〜」
    "social_proof", # 社会的証明: 「〜万人が注目」「話題の〜」
    "fomo",         # FOMO: 「見逃すな」「〜だけが知っている」
    "authority",    # 権威: 「専門家が認めた」「〜が証明」
    "emotion",      # 感情: 感動・共感・笑いに訴える
    "tips_hack",    # 実用的なコツ・裏技: 「〜するだけ」「知らないと損」
}

# 実際に使用する hook タイプ（HOOK_TYPES 環境変数でカンマ区切り指定。デフォルト: tips_hack,fomo）
_raw_hook_types = os.environ.get("HOOK_TYPES", "tips_hack,fomo")
ACTIVE_HOOK_TYPES: list[str] = [
    h.strip() for h in _raw_hook_types.split(",") if h.strip() in VALID_HOOK_TYPES
] or ["tips_hack", "fomo"]

# アフィリエイト投稿に使う固定CTAテンプレート（ランダムに1つ選択）
CTA_TEMPLATES: list[str] = [
    "失敗したくない人はこれ見て",
    "在宅・大学・外出先の作業なら相性いい",
    "詳細はリンクで確認",
]

_CLAUDE_MODEL = "claude-haiku-4-5"


@dataclass
class GeneratedContent:
    post_text: str
    image_prompt: str
    hashtags: list[str]
    affiliate_category: str
    hook_type: str = "emotion"
    cta_used: str = ""       # 実際に注入した CTA テンプレート（固定モード時のみ）
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


def _validate_and_fix(data: dict, keyword: str, fallback_hook: str = "emotion") -> dict:
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
    hook_type = data.get("hook_type", fallback_hook)
    if not isinstance(hook_type, str) or hook_type.lower() not in VALID_HOOK_TYPES:
        hook_type = fallback_hook
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


def _ensure_pr_label(post_text: str) -> str:
    """
    affiliate 投稿に「#PR」表記を保証する（景表法・ASP 規約対応）。

    - すでに含まれていれば何もしない
    - 追加しても POST_BODY_LIMIT 以内なら末尾に付加
    - 収まらない場合は本文をトリムして付加
    """
    if "#PR" in post_text:
        return post_text
    suffix = " #PR"
    if _count_x_chars(post_text + suffix) <= POST_BODY_LIMIT:
        return post_text + suffix
    # POST_BODY_LIMIT - len(" #PR") - 1("…") = 111 chars for body
    budget = POST_BODY_LIMIT - _count_x_chars(suffix) - 1
    trimmed = ""
    for ch in post_text:
        if _count_x_chars(trimmed + ch) > budget:
            break
        trimmed += ch
    return trimmed.rstrip() + "…" + suffix


def _build_prompt_affiliate(
    trend: TrendItem,
    product_theme: Optional[str] = None,
    forced_hook: Optional[str] = None,
    forced_cta: Optional[str] = None,
) -> str:
    """アフィリエイトリンク付き投稿用プロンプト。購入・CTA を促すトーン。"""
    if product_theme:
        topic_line = (
            f"投稿テーマ（固定）: {product_theme}\n"
            f"参考トレンド: {trend.keyword}（検索量: {trend.approx_traffic}）"
        )
        news_section = ""
    else:
        topic_line = f"トレンドキーワード: {trend.keyword}\n検索量: {trend.approx_traffic}"
        news_lines = "\n".join(
            f"  - [{n.source}] {n.title}" for n in trend.news_items[:3]
        )
        news_section = f"\n関連ニュース:\n{news_lines}" if news_lines else ""

    _hook_desc = (
        "- curiosity  : 好奇心を刺激 (「〜って知ってた？」「実は〜」)\n"
        "- urgency    : 緊急性・限定感 (「今すぐ〜」「期間限定〜」)\n"
        "- social_proof: 社会的証明 (「〜万人が注目」「話題の〜」)\n"
        "- fomo       : 機会損失への恐れ (「見逃すな」「〜だけが知っている」)\n"
        "- authority  : 権威・専門性 (「専門家が認めた」「〜が証明」)\n"
        "- emotion    : 感情に訴える (感動・共感・ユーモアなど)\n"
        "- tips_hack  : 実用的なコツ・裏技 (「〜するだけ」「知らないと損」「実は〜が正解」)"
    )
    if forced_hook:
        hook_section = f'hook_type は必ず "{forced_hook}" を使ってください。他のhookタイプは使わないこと。'
    else:
        hook_section = f"以下の7つのviral hookフレームワークのいずれかを選んでください:\n{_hook_desc}"

    cta_section = ""
    if forced_cta:
        cta_section = (
            f"\n投稿本文に必ず以下のCTAフレーズを自然に組み込んでください（言い回しは多少変えてもOK）:\n"
            f"「{forced_cta}」"
        )

    hook_type_hint = (
        f'"{forced_hook}"  ← この値を必ず使うこと'
        if forced_hook
        else '"curiosity|urgency|social_proof|fomo|authority|emotion|tips_hack のいずれか"'
    )

    return f"""あなたはXアフィリエイトマーケターです。
以下のテーマについて、Xへの投稿テキストと画像プロンプトを生成してください。

{topic_line}{news_section}

{hook_section}{cta_section}

以下のJSONを生成してください（マークダウンコードブロックなし・生JSONのみ）:
{{
  "post_text": "投稿本文（ハッシュタグを含む・{POST_BODY_LIMIT}字以内）",
  "image_prompt": "英語の画像生成プロンプト（Photorealistic/8k等のキーワード含む）",
  "hashtags": ["#タグ1", "#タグ2", "#タグ3"],
  "affiliate_category": "sports|entertainment|tech|fashion|food|travel|health|books|other のいずれか",
  "hook_type": {hook_type_hint},
  "thread_tweet": "スレッド2ツイート目の文章（省略可・空文字OK）"
}}

制約:
- post_text は {POST_BODY_LIMIT} 字以内（ハッシュタグを含む）
- hashtags は 2〜5個、必ず「#PR」を含めること（景表法・ASP規約上の広告表記義務）
- affiliate_category はテーマに最も近いカテゴリを選ぶ
- hook_type は選んだフレームワーク名を正確に記入する
- 炎上リスクの高い内容（政治・訃報・事件）は避ける
- 読者の関心を引くトーンで、自然な日本語で書く"""


def _build_prompt_normal(
    trend: TrendItem,
    product_theme: Optional[str] = None,
    forced_hook: Optional[str] = None,
) -> str:
    """通常投稿用プロンプト。情報提供・学びを促すトーン。商品誘導は含めない。"""
    if product_theme:
        topic_line = (
            f"投稿テーマ（固定）: {product_theme}\n"
            f"参考トレンド: {trend.keyword}（検索量: {trend.approx_traffic}）"
        )
        news_section = ""
    else:
        topic_line = f"トレンドキーワード: {trend.keyword}\n検索量: {trend.approx_traffic}"
        news_lines = "\n".join(
            f"  - [{n.source}] {n.title}" for n in trend.news_items[:3]
        )
        news_section = f"\n関連ニュース:\n{news_lines}" if news_lines else ""

    _hook_desc = (
        "- curiosity  : 好奇心を刺激 (「〜って知ってた？」「実は〜」)\n"
        "- urgency    : 緊急性・限定感 (「今すぐ〜」「期間限定〜」)\n"
        "- social_proof: 社会的証明 (「〜万人が注目」「話題の〜」)\n"
        "- fomo       : 機会損失への恐れ (「見逃すな」「〜だけが知っている」)\n"
        "- authority  : 権威・専門性 (「専門家が認めた」「〜が証明」)\n"
        "- emotion    : 感情に訴える (感動・共感・ユーモアなど)\n"
        "- tips_hack  : 実用的なコツ・裏技 (「〜するだけ」「知らないと損」「実は〜が正解」)"
    )
    if forced_hook:
        hook_section = f'hook_type は必ず "{forced_hook}" を使ってください。他のhookタイプは使わないこと。'
    else:
        hook_section = f"以下の7つのviral hookフレームワークのいずれかを選んでください:\n{_hook_desc}"

    hook_type_hint = (
        f'"{forced_hook}"  ← この値を必ず使うこと'
        if forced_hook
        else '"curiosity|urgency|social_proof|fomo|authority|emotion|tips_hack のいずれか"'
    )

    return f"""あなたはテック系の情報を発信するライターです。
以下のテーマについて、Xへの投稿テキストと画像プロンプトを生成してください。
商品リンクやアフィリエイトは含めず、純粋に情報・学びとして役立つ内容にしてください。

{topic_line}{news_section}

{hook_section}

以下のJSONを生成してください（マークダウンコードブロックなし・生JSONのみ）:
{{
  "post_text": "投稿本文（ハッシュタグを含む・{POST_BODY_LIMIT}字以内）",
  "image_prompt": "英語の画像生成プロンプト（Photorealistic/8k等のキーワード含む）",
  "hashtags": ["#タグ1", "#タグ2", "#タグ3"],
  "affiliate_category": "sports|entertainment|tech|fashion|food|travel|health|books|other のいずれか",
  "hook_type": {hook_type_hint},
  "thread_tweet": "スレッド2ツイート目の文章（省略可・空文字OK）"
}}

制約:
- post_text は {POST_BODY_LIMIT} 字以内（ハッシュタグを含む）
- hashtags は 2〜5個
- affiliate_category はカテゴリ分類のみに使用（リンク生成には使わない）
- hook_type は選んだフレームワーク名を正確に記入する
- 炎上リスクの高い内容（政治・訃報・事件）は避ける
- 商品購入への誘導フレーズ（「購入はこちら」「チェック」等）は書かない
- 読者が「なるほど」「ためになった」と感じる情報提供型の文体で書く"""


def generate_post_content(
    trend: TrendItem,
    api_key: Optional[str] = None,
    post_mode: PostMode = "affiliate",
    product_theme: Optional[str] = None,
) -> GeneratedContent:
    """
    Anthropic Claude API を呼び出してトレンドから投稿コンテンツを生成する。

    Parameters
    ----------
    trend         : TrendItem（キーワード・ニュース情報）
    api_key       : Anthropic API キー（省略時は環境変数 ANTHROPIC_API_KEY）
    post_mode     : "affiliate"=アフィリリンク付き投稿用 / "normal"=情報提供型投稿用
    product_theme : 商品テーマを固定する場合に指定（例: "USB-C充電器"）。
                    指定するとトレンドキーワードの代わりにこのテーマで投稿文を生成する。

    Returns
    -------
    GeneratedContent
    """
    if anthropic_sdk is None:
        raise ImportError("anthropic がインストールされていません: pip install anthropic")

    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY が設定されていません")

    # ACTIVE_HOOK_TYPES からフックを選択（常に制限リストを使う）
    forced_hook: Optional[str] = random.choice(ACTIVE_HOOK_TYPES) if ACTIVE_HOOK_TYPES else None
    # アフィリエイト投稿にのみ CTA テンプレートを注入する
    forced_cta: Optional[str] = (
        random.choice(CTA_TEMPLATES) if (post_mode == "affiliate" and CTA_TEMPLATES) else None
    )

    client = anthropic_sdk.Anthropic(api_key=key)
    if post_mode == "affiliate":
        prompt = _build_prompt_affiliate(trend, product_theme, forced_hook, forced_cta)
    else:
        prompt = _build_prompt_normal(trend, product_theme, forced_hook)
    logger.info(
        "Anthropic API 呼び出し: model=%s keyword=%s mode=%s hook=%s theme=%s",
        _CLAUDE_MODEL, trend.keyword, post_mode, forced_hook, product_theme or "-",
    )

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

    fixed = _validate_and_fix(data, trend.keyword, fallback_hook=forced_hook or "emotion")

    # タグが post_text に含まれていなければ結合
    post_text = fixed["post_text"]
    hashtags  = fixed["hashtags"]
    if not any(h in post_text for h in hashtags):
        post_text = _trim_to_limit(post_text, hashtags)
    else:
        if _count_x_chars(post_text) > POST_BODY_LIMIT:
            post_text = _trim_to_limit(post_text, [])

    # アフィリ投稿のみ CTA 品質チェック＋ #PR 保証
    if post_mode == "affiliate":
        _CTA_KEYWORDS = ["リンク", "チェック", "詳しくは", "購入", "はこちら", "もっと", "今すぐ", "試して", "おすすめ", "必見"]
        if not any(kw in post_text for kw in _CTA_KEYWORDS):
            logger.warning("CTA が弱い可能性があります。post_text にクリック誘導フレーズが含まれていません。")
        # 景表法・ASP 規約対応: #PR をコードレベルで保証
        before = post_text
        post_text = _ensure_pr_label(post_text)
        if post_text != before:
            logger.info("[#PR 挿入] affiliate 投稿に #PR を自動付加しました")

    logger.info(
        "生成完了: %d字 category=%s hook=%s mode=%s",
        _count_x_chars(post_text), fixed["affiliate_category"], fixed["hook_type"], post_mode,
    )

    return GeneratedContent(
        post_text=post_text,
        image_prompt=fixed["image_prompt"],
        hashtags=hashtags,
        affiliate_category=fixed["affiliate_category"],
        hook_type=fixed["hook_type"],
        cta_used=forced_cta or "",
        thread_tweet=fixed["thread_tweet"],
        raw_json=fixed,
    )
