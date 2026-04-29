# X Affiliate Bot 🤖

**Googleトレンドを監視して、AIが投稿文＋画像を自動生成し、Xに投稿するbot。通常投稿とアフィリエイト投稿を自動で配分する。**

```
Google Trends RSS (JP)
        │ トレンドワード取得
        ▼
Claude API (Anthropic)
        │ 日本語投稿文 + 画像プロンプト + カテゴリ生成
        ▼
HuggingFace (FLUX.1-schnell)
        │ 画像生成 → X v1.1 API でアップロード（任意）
        ▼
モード判定: normal（情報提供） / affiliate（アフィリリンク付き）
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
- **2種類の投稿モード**: 情報提供型の通常投稿 と アフィリエイトリンク付き投稿を自動で配分
- **アフィリエイト対応**: カテゴリ別に楽天/Amazonリンクを自動付与、`AFFILIATE_ASP` 環境変数で切り替え可
- **ドライラン**: `--dry-run` で投稿せずに内容確認
- **コスト最小**: Claude Haiku無料枠 + HuggingFace無料枠で運用可能

---

## 必要なAPIキー

| キー | 用途 | 取得先 | 備考 |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | 投稿文生成 | [Anthropic Console](https://console.anthropic.com/) | 従量課金（Haiku は安価） |
| `X_API_KEY` / `X_API_SECRET` | X への投稿 | [X Developer Portal](https://developer.twitter.com/en/portal/dashboard) | Free プラン: 50ツイート/24h |
| `X_ACCESS_TOKEN` / `X_ACCESS_TOKEN_SECRET` | X OAuth 認証 | 同上 | Read+Write 権限が必要 |
| `X_BEARER_TOKEN` | X API 初期化 | 同上 | オプション（なくても動作可） |
| `HF_API_TOKEN` | 画像生成 | [HuggingFace Settings](https://huggingface.co/settings/tokens) | `--no-image` なら不要 |
| `RAKUTEN_AFFILIATE_ID` | 楽天リンク追跡 | [楽天アフィリエイト](https://affiliate.rakuten.co.jp/) | `AFFILIATE_ASP=rakuten` 時のみ |

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

`src/affiliate.py` の `AFFILIATE_LINKS`（楽天）または `AFFILIATE_LINKS_AMAZON`（Amazon）辞書内の `REPLACE_ME` を実際のURLに書き換えてください。

```python
AFFILIATE_LINKS = {
    "tech": ["https://楽天アフィリエイトのURL1", "https://楽天アフィリエイトのURL2"],
    # ...
}
```

使用する ASP は `.env` で切り替えられます：

```
AFFILIATE_ASP=rakuten   # 楽天（デフォルト）
AFFILIATE_ASP=amazon    # Amazon アソシエイト
```

---

### 投稿モードの設定

ボットは各投稿を自動で **通常投稿** と **アフィリエイト投稿** に振り分けます。

| モード | 内容 |
|---|---|
| `normal` | テック系ニュース・学びを情報提供型で投稿。リンクなし |
| `affiliate` | 同上の内容にアフィリエイトリンクを付与して投稿 |

割合は `.env` の `AFFILIATE_RATIO` で制御します：

```
AFFILIATE_RATIO=0.2   # 20%がアフィリ投稿（デフォルト）
AFFILIATE_RATIO=0.0   # 常に通常投稿
AFFILIATE_RATIO=1.0   # 常にアフィリ投稿
```

---

## 初回本番 Run の推奨設定

本番環境で初めて動かすときは、段階的に確認しながら進めてください。

### Step 1 — dry-run で内容確認（Xに投稿しない）

```bash
AFFILIATE_RATIO=0.0 python src/main.py --dry-run --no-image
```

生成された投稿文がコンソールに出力されます。問題なければ Step 2 へ。

### Step 2 — 1本だけ本番投稿（アフィリなし・画像なし）

```bash
AFFILIATE_RATIO=0.0 POSTS_PER_RUN=1 python src/main.py --no-image
```

- `AFFILIATE_RATIO=0.0` で全件を通常投稿にし、アフィリリンクを含めない
- `--no-image` で画像生成をスキップし、HF_API_TOKEN が不要
- X のタイムラインで実際の投稿を目視確認する

### Step 3 — アフィリ比率を上げて安定確認後に通常運用へ

問題がなければ `.env` を更新し、GitHub Actions に Secrets を設定して自動実行に移行します。

```
# 推奨初期値（全体の10%をアフィリ投稿）
AFFILIATE_RATIO=0.1
POSTS_PER_RUN=1
DAILY_MAX_POSTS=5   # 1日の投稿上限（X Free枠は50件/24h）
```

> **注意**: `AFFILIATE_RATIO > 0` の場合、affiliate 投稿には法令上の広告表記 `#PR` が自動付与されます。

---

## 初回〜1ヶ月目のおすすめ設定（最速マネタイズ向け）

投稿本数とアフィリ比率を段階的に上げていくことで、アカウントの健全性を保ちながら最短でマネタイズの母数を作れます。

| 期間 | `AFFILIATE_RATIO` | `POSTS_PER_RUN` | `DAILY_MAX_POSTS` | `ALLOWED_CATEGORIES` |
|---|---|---|---|---|
| **1〜3日目**（動作確認） | `0.0` | `1` | `3` | 空（全カテゴリ） |
| **4日目〜2週間**（通常投稿で実績作り） | `0.0` | `1` | `5` | 空（全カテゴリ） |
| **2〜4週間目**（アフィリを少しずつ混ぜる） | `0.1` | `1` | `5` | 空（全カテゴリ） |
| **1ヶ月以降**（安定運用） | `0.2` | `1〜2` | `8` | 空（全カテゴリ） |

### 設定変更の判断基準

- **`AFFILIATE_RATIO` を上げるタイミング**: 通常投稿が複数日連続で成功し、インプレッションが安定してきたら `0.1` に上げる。その後 1〜2 週間様子を見て `0.2` へ。
- **`POSTS_PER_RUN=2` にするタイミング**: 1ヶ月間エラーなく安定したら。X Free枠（50件/24h）と `DAILY_MAX_POSTS` で二重にガードされているので急激に増えることはない。
- **`ALLOWED_CATEGORIES` は当面空のまま推奨**: 日本の Google トレンドはエンタメ・スポーツ・芸能が多く、`tech` に絞ると投稿0件になりやすい。カテゴリを絞りたい場合は `ALLOWED_CATEGORIES=tech,sports,entertainment` から試す。

### GitHub Variables への設定方法

`Settings → Secrets and variables → Actions → Variables タブ` で以下を追加します（Secrets ではなく Variables）。

```
AFFILIATE_RATIO   = 0.0
POSTS_PER_RUN     = 1
DAILY_MAX_POSTS   = 3
ALLOWED_CATEGORIES=          ← 空のまま（全カテゴリ許可）
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

`Settings > Secrets and variables > Actions` で以下の Secrets を設定してください。

**必須**（未設定だと起動時エラーで停止）

```
ANTHROPIC_API_KEY
X_API_KEY
X_API_SECRET
X_ACCESS_TOKEN
X_ACCESS_TOKEN_SECRET
```

**任意**（用途に応じて追加）

```
X_BEARER_TOKEN        # X API 初期化（省略可）
HF_API_TOKEN          # 画像生成（--no-image 運用なら不要）
RAKUTEN_AFFILIATE_ID  # 楽天アフィリエイトID（トラッキング追加に使用）
```

**Variables**（Secrets ではなく Variables に設定する環境変数）

```
AFFILIATE_RATIO=0.1   # アフィリ投稿の割合
AFFILIATE_ASP=rakuten # 使用するASP（rakuten / amazon）
POSTS_PER_RUN=1       # 1回の実行あたりの投稿数
DAILY_MAX_POSTS=5     # 1日の最大投稿件数（X Free枠は50件/24h）
```

設定後、`.github/workflows/bot.yml` が毎日3回自動実行されます。

手動実行は `Actions > X Affiliate Bot > Run workflow` から可能。

---

## アーキテクチャ

```
src/
├── main.py            # エントリーポイント・パイプライン制御・モード決定
├── trend_collector.py # Google Trends RSS 取得・安全フィルタ
├── ai_generator.py    # Claude API 投稿文生成（normal / affiliate モード対応）
├── affiliate.py       # アフィリエイトリンク管理（楽天 / Amazon 切り替え）
├── image_generator.py # HuggingFace 画像生成 + X v1.1 アップロード
├── x_poster.py        # X API v2 投稿・リトライ制御
└── result_logger.py   # 投稿記録 JSONL 保存・重複チェック・上限集計
```

---

## コスト

| サービス | 月間コスト目安 | 備考 |
|---|---|---|
| X API | 無料 | Free プラン: 50ツイート/24h |
| Claude API (Haiku) | ～¥100 以下 | 1投稿あたり約 $0.0003（入力1M tokens $0.80） |
| HuggingFace | 無料 | レート制限あり。`--no-image` なら完全無料 |
| GitHub Actions | 無料 | public repo は無制限 |
| **合計** | **¥100 以下/月** | 画像あり・3投稿/日の場合の目安 |

Claude Haiku は非常に安価なため、アフィリエイト収益が数百円でも十分黒字になる構成です。
