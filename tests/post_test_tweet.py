"""
tests/post_test_tweet.py
------------------------
X API の認証情報を最小限で検証するスクリプト。

実行順:
  1. get_me(user_auth=True) → OAuth 1.0a の認証が通るかを確認
  2. --tweet フラグがあれば実際に 1 件テスト投稿する

使い方:
  # .env を読んで get_me だけ確認（投稿しない）
  python tests/post_test_tweet.py

  # 実際に 1 件投稿する
  python tests/post_test_tweet.py --tweet
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# プロジェクトルートの .env を自動で読み込む
try:
    from dotenv import load_dotenv
    _env = Path(__file__).parent.parent / ".env"
    if _env.exists():
        load_dotenv(_env)
        print(f"[INFO] .env 読み込み: {_env}")
    else:
        print("[INFO] .env が見つかりません。環境変数が直接設定されている前提で続行します。")
except ImportError:
    print("[WARN] python-dotenv 未インストール。環境変数が直接設定されている前提で続行します。")

import tweepy


# =====================================================================
# 1. 環境変数の確認
# =====================================================================

REQUIRED_VARS = [
    "X_API_KEY",
    "X_API_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
]

print("\n=== 環境変数チェック ===")
missing = []
for var in REQUIRED_VARS:
    val = os.environ.get(var, "")
    if val:
        print(f"  {var}: {'*' * 6}{val[-4:]}  (末尾4文字)  ✅")
    else:
        print(f"  {var}: (未設定)  ❌")
        missing.append(var)

if missing:
    print(f"\n[ERROR] 以下の環境変数が未設定です: {missing}")
    print("  .env ファイルを確認するか、GitHub Secrets を確認してください。")
    sys.exit(1)


# =====================================================================
# 2. tweepy.Client の初期化（x_poster.py と同じ構成）
# =====================================================================

client = tweepy.Client(
    consumer_key=os.environ["X_API_KEY"],
    consumer_secret=os.environ["X_API_SECRET"],
    access_token=os.environ["X_ACCESS_TOKEN"],
    access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
)


# =====================================================================
# 3. get_me — OAuth 1.0a の認証確認（投稿しない）
# =====================================================================

print("\n=== get_me(user_auth=True) ===")
try:
    me = client.get_me(user_auth=True)
    print(f"  ✅ 認証成功: @{me.data.username}  (id={me.data.id})")
    print("  → OAuth 1.0a の consumer_key/secret + access_token/secret は有効です。")
except tweepy.errors.Unauthorized as e:
    print(f"  ❌ 401 Unauthorized: {e}")
    print("  → consumer_key/secret または access_token/secret が間違っている可能性があります。")
    print("  → Developer Portal でキーを再確認・再発行してください。")
    sys.exit(1)
except tweepy.errors.Forbidden as e:
    print(f"  ❌ 403 Forbidden: {e}")
    print("  → アプリの権限が Read only になっている可能性があります。")
    print("  → Developer Portal で App permissions を Read+Write に変更し、")
    print("     Access Token を再発行してください。")
    sys.exit(1)
except Exception as e:
    print(f"  ❌ 予期しないエラー: {type(e).__name__}: {e}")
    sys.exit(1)


# =====================================================================
# 4. オプション: 実際に 1 件投稿する（--tweet フラグ付きのみ）
# =====================================================================

parser = argparse.ArgumentParser(description="X API 動作確認スクリプト")
parser.add_argument("--tweet", action="store_true", help="テスト投稿を 1 件送信する")
args = parser.parse_args()

if not args.tweet:
    print("\n--tweet フラグなし。投稿はスキップします。")
    print("投稿テストをしたい場合: python tests/post_test_tweet.py --tweet")
    sys.exit(0)

print("\n=== テスト投稿 ===")
import datetime
test_text = f"[bot test] X API 動作確認 {datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')} #test"
print(f"  投稿内容: {test_text!r}")

try:
    resp = client.create_tweet(text=test_text, user_auth=True)
    tweet_id = resp.data["id"]
    print(f"  ✅ 投稿成功: https://x.com/i/web/status/{tweet_id}")
except tweepy.errors.Forbidden as e:
    print(f"  ❌ 403 Forbidden: {e}")
    print("  → Access Token が Read only スコープで発行されています。")
    print("  → Developer Portal で Read+Write に変更後、Access Token を再発行してください。")
    sys.exit(1)
except tweepy.errors.Unauthorized as e:
    print(f"  ❌ 401 Unauthorized: {e}")
    sys.exit(1)
except Exception as e:
    print(f"  ❌ エラー: {type(e).__name__}: {e}")
    sys.exit(1)
