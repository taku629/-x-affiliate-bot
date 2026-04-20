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
アフィリエイトリンク取得（楽天/Amazon）
        │
        ▼
X API v2 で投稿
```

GitHub Actions で毎日3回（JST 8:00 / 12:00 / 19:00）自動実行。

---

## 特徴

- **完全自動**: 一度セットアップすれば毎日自動投稿
- **安全フィルタ**: 事故・訃報・政治などの炎上リスクが高いトピックを自動除外
- **画像付き投稿**: FLUX.1-schnell → SDXL → SD2.1 のフォールバックで高確率で画像生成
- **アフィリエイト対応**: カテゴリ別に楽天/Amazonリンクを自動付与
- **ドライラン**: `--dry-run` で投稿せずに内容確認
- **コスト最小**: Gemini無料枠 (1,500req/day) + HuggingFace無料枠で運用可能

---

## 必要なAPIキー

| キー | 取得先 | 無料枠 |
|---|---|---|
| `X_API_KEY` 等 | [X Developer Portal](https://developer.twitter.com/en/portal/dashboard) | Free（50ツイート/24h） |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/app/apikey) | 1,500 req/day |
| `HF_API_TOKEN` | [HuggingFace Settings](https://huggingface.co/settings/tokens) | レート制限あり |
| `RAKUTEN_AFFILIATE_ID` | [楽天アフィリエイト](https://affiliate.rakuten.co.jp/) | 無料 |

---

## セットアップ

```bash
git clone https://github.com/taku629/x-affiliate-bot.git
cd x-affiliate-bot

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env を編集してAPIキーを設定
```

### アフィリエイトリンクの差し替え

`src/affiliate.py` の `AFFILIATE_LINKS` 辞書内の `REPLACE_ME` を実際のURLに書き換えてください。

```python
AFFILIATE_LINKS = {
    "sports": "https://楽天アフィリエイトのURL",
    # ...
}
```

---

## 実行方法

```bash
# 通常実行（1件投稿）
python src/main.py

# 投稿内容だけ確認（Xへの投稿なし）
python src/main.py --dry-run

# 画像なしで投稿（HFトークン不要）
python src/main.py --no-image

# 1回の実行で3件投稿
python src/main.py --posts 3
```

---

## GitHub Actions による自動実行

`Settings > Secrets and variables > Actions` で以下のSecretsを設定：

```
X_API_KEY
X_API_SECRET
X_ACCESS_TOKEN
X_ACCESS_TOKEN_SECRET
X_BEARER_TOKEN
GEMINI_API_KEY
HF_API_TOKEN
RAKUTEN_AFFILIATE_ID
```

設定後、`.github/workflows/bot.yml` が毎日3回自動実行されます。

手動実行は `Actions > X Affiliate Bot > Run workflow` から可能。

---

## アーキテクチャ

```
src/
├── main.py            # エントリーポイント・パイプライン制御
├── trend_collector.py # Google Trends RSS 取得・安全フィルタ
├── ai_generator.py    # Gemini API 投稿文生成
├── affiliate.py       # アフィリエイトリンク管理
├── image_generator.py # HuggingFace 画像生成 + X アップロード
└── x_poster.py        # X API v2 投稿
```

---

## コスト

| サービス | 月間コスト目安 |
|---|---|
| X API（Free枠） | 無料（50ツイート/24h） |
| Gemini API | 無料（1,500req/day まで） |
| HuggingFace | 無料（レート制限あり） |
| GitHub Actions | 無料（public repo は無制限） |
| **合計** | **¥0** |

アフィリエイト収益のみで運営可能な構成です。
