"""
STEP 5 動作確認スクリプト

TEST 1: アフィリエイトリンク（全カテゴリ・楽天ID付加・フォールバック）
TEST 2: ツイート本文の組み立て＆文字数バリデーション
TEST 3: モックによる post_to_x フロー（dry_run + 実投稿モック）
TEST 4: モックによるフルパイプライン run() 統合テスト
TEST 5: --dry-run オプションで main.py を実行（実API不要）
"""

import io
import logging
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

from affiliate import get_affiliate_link, list_categories, AFFILIATE_LINKS
from ai_generator import GeneratedContent
from x_poster import build_tweet_text, _validate_tweet_length, post_to_x
from trend_collector import TrendItem, NewsItem
from main import process_one_trend, run, RunSummary


print("=" * 60)
print("STEP 5 テスト: アフィリエイト・投稿・統合フロー")
print("=" * 60)

# =====================================================================
# TEST 1: アフィリエイトリンク
# =====================================================================
print("\n[TEST 1] アフィリエイトリンク")

print(f"  登録カテゴリ: {list_categories()}")

# 全カテゴリ確認
for cat in list_categories():
    link = get_affiliate_link(cat)
    status = "DUMMY" if link.is_dummy else "LIVE"
    print(f"  [{status}] {cat:<15} → {link.url[:55]}...")

# 楽天アフィリエイトID付加
link_with_id = get_affiliate_link("sports", rakuten_affiliate_id="test_id_123")
# ダミーURLの場合はIDが付加されないことを確認
if link_with_id.is_dummy:
    print(f"\n  楽天ID付加スキップ (ダミーURL): {link_with_id.url[:60]}...")
else:
    print(f"\n  楽天ID付加後: {link_with_id.url[:80]}...")

# 未知カテゴリのフォールバック
unknown = get_affiliate_link("unknown_xyz")
assert unknown.category == "other", "未知カテゴリは 'other' にフォールバックすべき"
print(f"  未知カテゴリ→フォールバック: category={unknown.category}")
print("  [OK] アフィリエイトリンクテスト完了")

# =====================================================================
# TEST 2: ツイート本文の組み立てと文字数チェック
# =====================================================================
print("\n[TEST 2] ツイート本文の組み立てと文字数チェック")

test_cases = [
    # (post_text, category, description)
    (
        "三浦龍司が国内初戦に登場！5000mで36位という結果に本人も「悪い意味で手応えある」と苦笑。次戦への巻き返しに注目👀\n#三浦龍司 #陸上 #金栗記念",
        "sports",
        "正常ケース（75字）",
    ),
    (
        "あ" * 116,   # ギリギリ116字
        "other",
        "ギリギリ116字",
    ),
]

for post_text, category, desc in test_cases:
    content = GeneratedContent(
        post_text=post_text,
        image_prompt="test prompt",
        hashtags=[],
        affiliate_category=category,
    )
    affiliate = get_affiliate_link(category)
    full_text = build_tweet_text(content, affiliate)
    is_ok = _validate_tweet_length(full_text)

    # URL部分を23字換算した実際の文字数
    import re
    counted = len(re.sub(r"https?://\S+", "x" * 23, full_text))
    print(f"  {desc}: {counted}字/140字 → {'OK' if is_ok else 'OVER'}")
    print(f"    本文: {full_text[:80].replace(chr(10), '↵')}...")

# =====================================================================
# TEST 3: post_to_x のモックテスト
# =====================================================================
print("\n[TEST 3] post_to_x モックテスト")

dummy_content = GeneratedContent(
    post_text="三浦龍司が国内初戦に登場！5000mで36位👀\n#三浦龍司 #陸上",
    image_prompt="Japanese runner on a track",
    hashtags=["#三浦龍司", "#陸上"],
    affiliate_category="sports",
)
dummy_affiliate = get_affiliate_link("sports")

# dry_run テスト（API呼び出しなし）
print("  [3a] dry_run=True:")
result_dry = post_to_x(
    content=dummy_content,
    affiliate_link=dummy_affiliate,
    media_id="1234567890",
    dry_run=True,
)
print(f"    tweet_id  : {result_dry.tweet_id}")
print(f"    tweet_url : {result_dry.tweet_url}")
print(f"    full_text :\n      {result_dry.full_text.replace(chr(10), chr(10)+'      ')}")
assert result_dry.tweet_id == "dry_run_id"
print("    [OK] dry_run成功")

# 実投稿モック
print("  [3b] mock投稿:")
mock_tweet_response = MagicMock()
mock_tweet_response.data = {"id": "9999999999999999999"}

mock_client = MagicMock()
mock_client.create_tweet.return_value = mock_tweet_response

with patch("x_poster._build_tweepy_v2_client", return_value=mock_client), \
     patch.dict(os.environ, {
         "X_API_KEY": "k", "X_API_SECRET": "s",
         "X_ACCESS_TOKEN": "t", "X_ACCESS_TOKEN_SECRET": "ts",
         "X_BEARER_TOKEN": "b",
     }):
    result_mock = post_to_x(
        content=dummy_content,
        affiliate_link=dummy_affiliate,
        media_id="1234567890",
        dry_run=False,
    )

print(f"    tweet_id  : {result_mock.tweet_id}")
print(f"    tweet_url : {result_mock.tweet_url}")
assert result_mock.tweet_id == "9999999999999999999"
# media_ids が正しく渡されているか確認
call_kwargs = mock_client.create_tweet.call_args
assert call_kwargs.kwargs.get("media_ids") == ["1234567890"]
print(f"    media_ids : {call_kwargs.kwargs.get('media_ids')}")
print("    [OK] mock投稿成功")

# =====================================================================
# TEST 4: フルパイプライン run() 統合モックテスト
# =====================================================================
print("\n[TEST 4] フルパイプライン run() 統合モックテスト")

# 各モジュールをまとめてモック
mock_trend = TrendItem(
    keyword="三浦龍司",
    approx_traffic="500+",
    news_items=[NewsItem(title="三浦龍司が36位", url="", source="")],
)

mock_generated = GeneratedContent(
    post_text="三浦龍司が国内初戦！5000mで36位👀 次戦に期待\n#三浦龍司 #陸上",
    image_prompt="Japanese runner on athletics track, 8k",
    hashtags=["#三浦龍司", "#陸上"],
    affiliate_category="sports",
)

from image_generator import UploadResult as UR
mock_upload = UR(
    media_id="9876543210",
    image_bytes=b"\x89PNG",
    model_used="black-forest-labs/FLUX.1-schnell",
    size_bytes=204800,
)

mock_post_result = MagicMock()
mock_post_result.tweet_id = "1111111111111111111"
mock_post_result.tweet_url = "https://x.com/i/web/status/1111111111111111111"

with patch("main.get_trends", return_value=[mock_trend]), \
     patch("main.generate_post_content", return_value=mock_generated), \
     patch("main.generate_and_upload", return_value=mock_upload), \
     patch("main.post_to_x", return_value=mock_post_result):

    summary = run(posts_per_run=1, dry_run=False, with_image=True)

print(f"  succeeded : {summary.succeeded}")
print(f"  failed    : {summary.failed}")
print(f"  tweet_url : {summary.results[0].tweet_url}")
assert summary.succeeded == 1
assert summary.failed == 0
print("  [OK] フルパイプライン統合テスト成功")

# =====================================================================
# TEST 4b: トレンド取得失敗時のグレースフルエラー
# =====================================================================
print("\n[TEST 4b] トレンド取得失敗時のグレースフルエラー")

with patch("main.get_trends", side_effect=RuntimeError("RSS接続タイムアウト")):
    summary_err = run(posts_per_run=1)

assert summary_err.failed == 1
assert summary_err.succeeded == 0
print(f"  error msg : {summary_err.errors[0]}")
print("  [OK] エラーハンドリング正常動作")

# =====================================================================
# TEST 5: main.py を --dry-run で実行（API不要の実トレンド取得→生成スキップ）
# =====================================================================
print("\n[TEST 5] main.py --dry-run（Gemini/X はモック）")

with patch("main.generate_post_content", return_value=mock_generated), \
     patch("main.generate_and_upload", return_value=mock_upload), \
     patch("main.post_to_x", return_value=mock_post_result):

    # 実際にトレンドを取得し、それ以降のAPIはモック
    summary_dr = run(posts_per_run=1, dry_run=True, with_image=False)

print(f"  succeeded : {summary_dr.succeeded}")
print(f"  tweet_url : {summary_dr.results[0].tweet_url}")
assert summary_dr.succeeded == 1
print("  [OK] --dry-run フロー成功")

print("\n" + "=" * 60)
print("[ALL OK] STEP 5 テスト完了")
print("=" * 60)
