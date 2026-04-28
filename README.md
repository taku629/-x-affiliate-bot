# X Affiliate Bot 🤖

**Googleトレンドを監視して、AIが投稿文＋画像を自動生成し、アフィリエイトリンク付きでXに投稿するbot**

```
Google Trends RSS (JP)
        │ トレンドワード取得
        ▼
Gemini API
        │ 日本語投稿文 + 画像プロンプト + カテゴリ生成
        ▼
HuggingFace (FLUX.1-schnell)
        │ 画像生成 → X v1.1 API でアップロード
        ▼
アフィリエイトリンク取得（楽天）
        │
        ▼
X API v2 で投稿
```

GitHub Actions で毎日3回（JST 8:00 / 12:00 / 19:00）自動実行。月間コスト **¥0**。

---

## 最速マネタイズ チェックリスト

### 1. APIキー取得（所要時間目安）

| キー | 取得先 | 時間 | 無料枠 |
|---|---|---|---|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/app/apikey) | **5分** | 1,500 req/day |
| `RAKUTEN_AFFILIATE_ID` | [楽天アフィリエイト](https://affiliate.rakuten.co.jp/) | **10分** | 無料（審査なし） |
| `X_API_KEY` 等 | [X Developer Portal](https://developer.twitter.com/en/portal/dashboard) | **15分** | 50ツイート/24h |
| `HF_API_TOKEN` | [HuggingFace Settings](https://huggingface.co/settings/tokens) | **3分** | レート制限あり |

### 2. 楽天アフィリエイトリンクの発行

1. [楽天アフィリエイト管理画面](https://affiliate.rakuten.co.jp/) にログイン
2. 「ツールボックス」→「テキストリンク」→ 各カテゴリのリンクを発行
3. `src/affiliate.py` の `AFFILIATE_LINKS` 辞書に貼り付け（`REPLACE_ME` を置き換え）

または GitHub Secrets で環境変数として設定（コードを書き換えずに済む）:
```
AFFILIATE_URL_SPORTS=https://hb.afl.rakuten.co.jp/...
AFFILIATE_URL_TECH=https://hb.afl.rakuten.co.jp/...
AFFILIATE_URL_FASHION=https://hb.afl.rakuten.co.jp/...
AFFILIATE_URL_FOOD=https://hb.afl.rakuten.co.jp/...
AFFILIATE_URL_TRAVEL=https://hb.afl.rakuten.co.jp/...
AFFILIATE_URL_HEALTH=https://hb.afl.rakuten.co.jp/...
AFFILIATE_URL_BOOKS=https://hb.afl.rakuten.co.jp/...
AFFILIATE_URL_ENTERTAINMENT=https://hb.afl.rakuten.co.jp/...
AFFILIATE_URL_OTHER=https://hb.afl.rakuten.co.jp/...
```

### 3. GitHub Secrets に設定

`Settings > Secrets and variables > Actions > New repository secret` で以下を設定:

```
X_API_KEY
X_API_SECRET
X_ACCESS_TOKEN
X_ACCESS_TOKEN_SECRET
X_BEARER_TOKEN
GEMINI_API_KEY
HF_API_TOKEN
RAKUTEN_AFFILIATE_ID

# アフィリエイトURLを環境変数で管理する場合（任意）
AFFILIATE_URL_SPORTS
AFFILIATE_URL_TECH
...
```

### 4. 動作確認（dry-run）

GitHub Actions の手動実行（`Actions > X Affiliate Bot > Run workflow`）で  
`dry_run: true` を選んで投稿内容を確認してから本番稼働させてください。

---

## セットアップ（ローカル実行）

```bash
git clone https://github.com/taku629/x-affiliate-bot.git
cd x-affiliate-bot

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env を編集してAPIキーを設定
```

### ローカル実行コマンド

```bash
# 内容確認のみ（Xへの投稿なし・APIキー不要）
python src/main.py --dry-run --no-image

# 画像なしで投稿（HFトークン不要）
python src/main.py --no-image

# 通常実行（1件投稿）
python src/main.py

# 1回の実行で3件投稿
python src/main.py --posts 3
```

---

## アーキテクチャ

```
src/
├── main.py            # エントリーポイント・パイプライン制御
├── trend_collector.py # Google Trends RSS 取得・安全フィルタ
├── ai_generator.py    # Gemini API 投稿文生成
├── affiliate.py       # アフィリエイトリンク管理（環境変数上書き対応）
├── image_generator.py # HuggingFace 画像生成 + X アップロード
└── x_poster.py        # X API v2 投稿

.github/workflows/
└── bot.yml            # GitHub Actions 自動実行（JST 8:00 / 12:00 / 19:00）
```

---

## コスト

| サービス | 月間コスト |
|---|---|
| X API（Free枠） | 無料（50ツイート/24h） |
| Gemini API | 無料（1,500 req/day まで） |
| HuggingFace | 無料（レート制限あり） |
| GitHub Actions | 無料（public repo は無制限） |
| **合計** | **¥0** |
