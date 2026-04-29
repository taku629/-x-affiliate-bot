"""
tests/check_credentials.py
--------------------------
ローカルの .env に入っている X API 認証情報の
「長さ・先頭6文字」を表示する診断スクリプト。

GitHub Actions の Verify X API credentials ステップが出力する
credential診断と同じフォーマットで表示するので、
2つを並べて見れば値のズレをすぐ特定できます。

使い方:
  python tests/check_credentials.py
"""

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[INFO] .env 読み込み: {env_path}\n")
    else:
        print("[WARN] .env が見つかりません\n")
except ImportError:
    print("[WARN] python-dotenv 未インストール\n")

VARS = [
    "X_API_KEY",
    "X_API_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
]

print("--- ローカル .env の credential診断 ---")
missing = []
for name in VARS:
    val = os.environ.get(name, "")
    if not val:
        print(f"  {name}: (未設定) ❌")
        missing.append(name)
    else:
        prefix = val[:6] if len(val) >= 6 else val
        print(f"  {name}: len={len(val)}  prefix={prefix}...")
print("---")

if missing:
    print(f"\n❌ 未設定の変数があります: {missing}")
    sys.exit(1)
else:
    print("\n✅ 4つの変数が揃っています。")
    print("GitHub Actions の credential診断出力と len/prefix を1行ずつ比較してください。")
    print("どれか1行でも異なれば、その Secrets の値が間違っています。")
