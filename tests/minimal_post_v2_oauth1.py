"""
tests/minimal_post_v2_oauth1.py
--------------------------------
X API v2 への OAuth 1.0a 接続を、tweepy と raw HTTP の両方で検証する最小スクリプト。

「tweepy が 401 だが raw HTTP は通る」場合 → tweepy バージョン問題
「raw HTTP も 401」の場合             → X API / アプリ設定の問題

使い方:
  python tests/minimal_post_v2_oauth1.py           # get_me のみ
  python tests/minimal_post_v2_oauth1.py --tweet   # get_me + 1件投稿
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path

# .env の自動読み込み
try:
    from dotenv import load_dotenv
    _env = Path(__file__).parent.parent / ".env"
    if _env.exists():
        load_dotenv(_env)
        print(f"[INFO] .env 読み込み: {_env}")
except ImportError:
    print("[WARN] python-dotenv 未インストール")

import tweepy
import requests
from requests_oauthlib import OAuth1Session

# =====================================================================
# 認証情報の読み込みと確認
# =====================================================================

VARS = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]
creds = {v: os.environ.get(v, "") for v in VARS}

print("\n=== credential診断 ===")
missing = [k for k, v in creds.items() if not v]
for name, val in creds.items():
    if val:
        print(f"  {name}: len={len(val)}  prefix={val[:6]}...")
    else:
        print(f"  {name}: (未設定) ❌")

if missing:
    print(f"\n[ERROR] 未設定: {missing}")
    sys.exit(1)

API_KEY    = creds["X_API_KEY"]
API_SECRET = creds["X_API_SECRET"]
AT         = creds["X_ACCESS_TOKEN"]
ATS        = creds["X_ACCESS_TOKEN_SECRET"]

# バージョン表示（診断に有用）
print(f"\n  tweepy   : {tweepy.__version__}")
print(f"  requests : {requests.__version__}")

# =====================================================================
# STEP 1: raw HTTP (requests_oauthlib) で GET /2/users/me
# =====================================================================

print("\n=== [raw HTTP] GET /2/users/me ===")
oauth_session = OAuth1Session(API_KEY, API_SECRET, AT, ATS)
r = oauth_session.get("https://api.twitter.com/2/users/me")
print(f"  HTTP {r.status_code}")

if r.ok:
    username = r.json()["data"]["username"]
    print(f"  ✅ raw HTTP 認証成功: @{username}")
    raw_ok = True
else:
    print(f"  ❌ raw HTTP 認証失敗: {r.text}")
    raw_ok = False

# =====================================================================
# STEP 2: tweepy.Client で get_me(user_auth=True)
# =====================================================================

print("\n=== [tweepy] get_me(user_auth=True) ===")
client = tweepy.Client(
    consumer_key=API_KEY,
    consumer_secret=API_SECRET,
    access_token=AT,
    access_token_secret=ATS,
)
tweepy_ok = False
try:
    me = client.get_me(user_auth=True)
    print(f"  ✅ tweepy 認証成功: @{me.data.username}")
    tweepy_ok = True
except tweepy.errors.Unauthorized as e:
    print(f"  ❌ 401 Unauthorized: {e}")
except tweepy.errors.Forbidden as e:
    print(f"  ❌ 403 Forbidden: {e}")
except Exception as e:
    print(f"  ❌ {type(e).__name__}: {e}")

# =====================================================================
# 診断サマリー（どこで詰まっているかを明示）
# =====================================================================

print("\n=== 診断サマリー ===")
if raw_ok and tweepy_ok:
    print("  ✅ raw HTTP: OK  /  tweepy: OK  → 認証は完全に正常")
elif raw_ok and not tweepy_ok:
    print("  ✅ raw HTTP: OK  /  ❌ tweepy: NG")
    print("  → tweepy のバージョン or 内部 OAuth1 実装の問題と推定")
    print(f"  → tweepy {tweepy.__version__} を使用中。pip install 'tweepy==4.14.0' を試してください。")
elif not raw_ok and tweepy_ok:
    print("  ❌ raw HTTP: NG  /  ✅ tweepy: OK  → 通常あり得ない組み合わせ")
else:
    print("  ❌ raw HTTP: NG  /  ❌ tweepy: NG")
    print("  → 両方失敗。Secrets の値か X App 設定を再確認してください。")

# =====================================================================
# STEP 3（オプション）: raw HTTP + tweepy 両方で create_tweet
# =====================================================================

parser = argparse.ArgumentParser()
parser.add_argument("--tweet", action="store_true", help="1件テスト投稿する")
args = parser.parse_args()

if not args.tweet:
    print("\n--tweet なし。投稿はスキップします。")
    print("投稿もテストしたい場合: python tests/minimal_post_v2_oauth1.py --tweet")
    sys.exit(0 if (raw_ok and tweepy_ok) else 1)

ts = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
test_text = f"[X Affiliate Bot minimal test] {ts}"
print(f"\n=== テスト投稿 ===\n  text: {test_text!r}")

# raw HTTP で投稿
print("\n--- [raw HTTP] POST /2/tweets ---")
r = oauth_session.post(
    "https://api.twitter.com/2/tweets",
    json={"text": test_text},
)
print(f"  HTTP {r.status_code}  body: {r.json()}")
if r.ok:
    tweet_id = r.json()["data"]["id"]
    print(f"  ✅ raw HTTP 投稿成功: https://x.com/i/web/status/{tweet_id}")
else:
    print(f"  ❌ raw HTTP 投稿失敗")

# tweepy で投稿（raw HTTP が成功した場合のみ、重複投稿を避けるため少し違うテキスト）
if raw_ok:
    print("\n--- [tweepy] create_tweet ---")
    tweepy_text = f"[X Affiliate Bot tweepy test] {ts}"
    try:
        resp = client.create_tweet(text=tweepy_text, user_auth=True)
        tid = resp.data["id"]
        print(f"  ✅ tweepy 投稿成功: https://x.com/i/web/status/{tid}")
    except tweepy.errors.Unauthorized as e:
        print(f"  ❌ 401 Unauthorized: {e}")
        print("  → tweepy バージョン問題と確定。x_poster.py を requests_oauthlib に切り替えます。")
    except Exception as e:
        print(f"  ❌ {type(e).__name__}: {e}")
