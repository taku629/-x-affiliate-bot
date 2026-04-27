"""
STEP 3 動作確認スクリプト

APIキーあり: 実際のGemini APIを呼び出す
APIキーなし: モック応答でロジック（文字数チェック・バリデーション）だけを確認
"""
import logging
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

from trend_collector import TrendItem, NewsItem
from ai_generator import (
    GeneratedContent,
    _trim_to_limit,
    _validate_and_fix,
    _count_x_chars,
    POST_BODY_LIMIT,
    generate_post_content,
)

print("=" * 60)
print("STEP 3 テスト: AI生成モジュール")
print(f"  POST_BODY_LIMIT = {POST_BODY_LIMIT} 文字")
print("=" * 60)

# =====================================================================
# TEST 1: 文字数カウントとトリミングロジック
# =====================================================================
print("\n[TEST 1] 文字数カウントとトリミングロジック")

cases = [
    ("短い本文", "今日の話題はこれだ！詳しくはリンクへ👇", ["#テスト"], True),
    ("ちょうど116文字",
     "あ" * 113 + "👇",  # 113 + 1絵文字(1) + 改行後タグ
     ["#テ"],            # 2文字 → total = 115 + 1(\n) + 2 = 118 → トリム発生
     False),
    ("長すぎる本文（トリム必要）",
     "今日のトレンドは非常に興味深いです。" * 5,
     ["#トレンド", "#日本"],
     False),
]

for name, body, tags, expected_ok in cases:
    result = _trim_to_limit(body, tags)
    char_count = _count_x_chars(result)
    ok = char_count <= POST_BODY_LIMIT
    status = "OK" if ok else "OVER"
    print(f"  {name}: {char_count}文字 [{status}]")
    print(f"    → {result[:60]}{'...' if len(result)>60 else ''}")

# =====================================================================
# TEST 2: バリデーション・フォールバック
# =====================================================================
print("\n[TEST 2] バリデーション・フォールバック")

bad_cases = [
    ("post_textが空", {"post_text": "", "image_prompt": "x", "hashtags": ["#a"], "affiliate_category": "tech"}),
    ("hashtagsが空", {"post_text": "テスト投稿", "image_prompt": "x", "hashtags": [], "affiliate_category": "sports"}),
    ("categoryが不正", {"post_text": "テスト", "image_prompt": "x", "hashtags": ["#t"], "affiliate_category": "invalid_cat"}),
    ("全フィールド欠損", {}),
]

for name, data in bad_cases:
    result = _validate_and_fix(data, "テストキーワード")
    print(f"  {name}:")
    print(f"    post_text        : {result.get('post_text','')[:40]}")
    print(f"    affiliate_category: {result.get('affiliate_category')}")
    print(f"    hashtags         : {result.get('hashtags')}")

# =====================================================================
# TEST 3: モック応答でフル生成フローを確認
# =====================================================================
print("\n[TEST 3] モック応答でフル生成フローを確認")

MOCK_RESPONSE_JSON = """{
  "post_text": "三浦龍司が国内初戦に登場！5000mで36位という結果に本人も「悪い意味で手応えある」と苦笑。次戦への巻き返しに注目👀",
  "image_prompt": "Photorealistic 8k image of a Japanese male long distance runner competing on an athletics track, stadium lights, crowd cheering, vibrant colors, motion blur on legs, sports photography style, high quality",
  "hashtags": ["#三浦龍司", "#陸上", "#金栗記念"],
  "affiliate_category": "sports"
}"""

dummy_trend = TrendItem(
    keyword="三浦龍司",
    approx_traffic="500+",
    news_items=[
        NewsItem(
            title="三浦龍司が国内初戦で男子5000mに出場し、まさかの36位",
            url="https://example.com/news1",
            source="スポーツ報知",
        )
    ],
)

# Gemini APIをモック
mock_response = MagicMock()
mock_response.text = MOCK_RESPONSE_JSON

mock_model = MagicMock()
mock_model.generate_content.return_value = mock_response

with patch("ai_generator.genai.configure"), \
     patch("ai_generator.genai.GenerativeModel", return_value=mock_model):
    content = generate_post_content(dummy_trend, api_key="mock_key")

print(f"  post_text        : {content.post_text}")
print(f"  文字数           : {content.post_char_count} / {POST_BODY_LIMIT}")
print(f"  制限内           : {content.is_within_limit()}")
print(f"  image_prompt     : {content.image_prompt[:60]}...")
print(f"  hashtags         : {content.hashtags}")
print(f"  affiliate_category: {content.affiliate_category}")

# =====================================================================
# TEST 4: 実際のGemini API呼び出し（APIキーがある場合のみ）
# =====================================================================
print("\n[TEST 4] 実際のGemini API呼び出し")
api_key = os.environ.get("GEMINI_API_KEY")

if not api_key:
    print("  GEMINI_API_KEY が未設定のためスキップ。")
    print("  実行方法: GEMINI_API_KEY=your_key python test_step3.py")
else:
    print(f"  APIキー検出: {api_key[:8]}...")
    try:
        content = generate_post_content(dummy_trend, api_key=api_key)
        print(f"  post_text        : {content.post_text}")
        print(f"  文字数           : {content.post_char_count} / {POST_BODY_LIMIT}")
        print(f"  制限内           : {content.is_within_limit()}")
        print(f"  image_prompt     : {content.image_prompt[:80]}...")
        print(f"  hashtags         : {content.hashtags}")
        print(f"  affiliate_category: {content.affiliate_category}")
        print("  [OK] 実APIテスト成功")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")

print("\n[OK] STEP 3 テスト完了")
