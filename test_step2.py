"""STEP 2 動作確認スクリプト"""
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

from trend_collector import get_trends, pick_best_trend

print("=" * 60)
print("STEP 2 テスト: Google Trends RSS 取得")
print("=" * 60)

# --- テスト1: top 5 トレンド取得 ---
print("\n[TEST 1] top_n=5 でトレンドを取得")
trends = get_trends(top_n=5, safe_only=True, shuffle=False)
for i, t in enumerate(trends, 1):
    print(f"  {i}. キーワード : {t.keyword}")
    print(f"     検索量     : {t.approx_traffic}")
    print(f"     関連ニュース: {len(t.news_items)} 件")
    if t.news_items:
        print(f"     先頭ニュース: {t.news_items[0].title[:60]}...")
    if t.picture_url:
        print(f"     画像URL     : {t.picture_url[:60]}...")
    print()

# --- テスト2: pick_best_trend ---
print("[TEST 2] pick_best_trend() で1件取得")
best = pick_best_trend(safe_only=True)
print(f"  ベストトレンド: 「{best.keyword}」({best.approx_traffic})")
print(f"  ニュース数    : {len(best.news_items)}")

print("\n[OK] STEP 2 テスト完了")
