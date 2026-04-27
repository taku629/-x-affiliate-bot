"""
main.py
-------
X アフィリエイトボット エントリーポイント。

実行フロー:
  1. 環境変数の読み込み（.env）
  2. Google Trends RSS からトレンドを取得
  3. Gemini API で投稿テキスト＆画像プロンプトを生成
  4. Hugging Face で画像を生成 → X v1.1 にアップロード → media_id 取得
  5. アフィリエイトリンクを取得
  6. X API v2 で投稿

コマンド例:
  python src/main.py                    # 通常実行
  python src/main.py --dry-run          # 投稿せずに内容だけ確認
  python src/main.py --no-image         # 画像なしで投稿（HFトークン不要）
  python src/main.py --posts 3          # 1回の実行で3件投稿
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# .env の読み込み（python-dotenv）
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
        print(f"[INFO] .env を読み込みました: {_env_path}")
except ImportError:
    pass  # dotenv なしでも環境変数が直接設定されていれば動く

# ロガーの設定（環境変数 LOG_LEVEL で変更可、デフォルト INFO）
_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("bot.main")

# srcディレクトリをパスに追加（スクリプトとして直接実行する場合）
sys.path.insert(0, str(Path(__file__).parent))

from trend_collector import TrendItem, get_trends, pick_best_trend
from ai_generator import GeneratedContent, generate_post_content
from image_generator import UploadResult, generate_and_upload
from affiliate import AffiliateLink, get_affiliate_link
from x_poster import PostResult, post_to_x


# =====================================================================
# 実行結果のサマリー
# =====================================================================

@dataclass
class RunSummary:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    results: list[PostResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add_success(self, result: PostResult) -> None:
        self.total += 1
        self.succeeded += 1
        self.results.append(result)

    def add_failure(self, error: str) -> None:
        self.total += 1
        self.failed += 1
        self.errors.append(error)

    def log(self) -> None:
        logger.info("=" * 50)
        logger.info("実行サマリー: %d件中 %d件成功 / %d件失敗",
                    self.total, self.succeeded, self.failed)
        for r in self.results:
            logger.info("  ✓ %s", r.tweet_url)
        for e in self.errors:
            logger.error("  ✗ %s", e)
        logger.info("=" * 50)


# =====================================================================
# パイプライン: 1件のトレンドを処理
# =====================================================================

def process_one_trend(
    trend: TrendItem,
    *,
    dry_run: bool = False,
    with_image: bool = True,
    use_placeholder_on_image_failure: bool = True,
) -> PostResult:
    """
    トレンド1件に対してテキスト生成→画像→投稿までを実行し PostResult を返す。
    各ステップでエラーが起きても詳細なログを出力してから再 raise する。
    """
    step = "初期化"
    try:
        # --------------------------------------------------------
        # STEP A: テキスト生成（Gemini）
        # --------------------------------------------------------
        step = "テキスト生成 (Gemini)"
        logger.info("[%s] 開始: 「%s」", step, trend.keyword)
        content: GeneratedContent = generate_post_content(trend)
        logger.info(
            "[%s] 完了: %d字 / カテゴリ=%s",
            step, content.post_char_count, content.affiliate_category,
        )

        # --------------------------------------------------------
        # STEP B: 画像生成＆アップロード（HuggingFace → X v1.1）
        # --------------------------------------------------------
        media_id: Optional[str] = None
        if with_image:
            step = "画像生成 (HuggingFace)"
            logger.info("[%s] 開始: prompt=%s...", step, content.image_prompt[:60])
            upload: UploadResult = generate_and_upload(
                prompt=content.image_prompt,
                use_placeholder_on_failure=use_placeholder_on_image_failure,
            )
            media_id = upload.media_id
            logger.info(
                "[%s] 完了: model=%s size=%d bytes media_id=%s",
                step, upload.model_used, upload.size_bytes, media_id,
            )
        else:
            logger.info("[画像生成] --no-image フラグのためスキップ")

        # --------------------------------------------------------
        # STEP C: アフィリエイトリンク取得
        # --------------------------------------------------------
        step = "アフィリエイトリンク取得"
        affiliate: AffiliateLink = get_affiliate_link(content.affiliate_category)
        logger.info(
            "[%s] category=%s is_dummy=%s",
            step, affiliate.category, affiliate.is_dummy,
        )

        # --------------------------------------------------------
        # STEP D: X への投稿 (v2)
        # --------------------------------------------------------
        step = "X投稿 (v2)"
        logger.info("[%s] 開始 (dry_run=%s)", step, dry_run)
        result: PostResult = post_to_x(
            content=content,
            affiliate_link=affiliate,
            media_id=media_id,
            dry_run=dry_run,
        )
        logger.info("[%s] 完了: %s", step, result.tweet_url)
        return result

    except Exception as e:
        logger.error(
            "[%s] エラー発生 (keyword=%s): %s\n%s",
            step, trend.keyword, e, traceback.format_exc(),
        )
        raise


# =====================================================================
# メインエントリーポイント
# =====================================================================

def run(
    posts_per_run: int = 1,
    dry_run: bool = False,
    with_image: bool = True,
    interval_between_posts: float = 5.0,
) -> RunSummary:
    """
    ボットのメイン処理。

    Parameters
    ----------
    posts_per_run           : 1回の実行で投稿する件数
    dry_run                 : True のとき投稿せずに内容確認のみ
    with_image              : False のとき画像生成をスキップ
    interval_between_posts  : 複数件投稿時の間隔（秒）
    """
    summary = RunSummary()
    logger.info("=" * 50)
    logger.info("X アフィリエイトボット 起動")
    logger.info("  posts_per_run  = %d", posts_per_run)
    logger.info("  dry_run        = %s", dry_run)
    logger.info("  with_image     = %s", with_image)
    logger.info("=" * 50)

    # --------------------------------------------------------
    # STEP 1: トレンド取得
    # --------------------------------------------------------
    logger.info("[トレンド取得] 開始")
    try:
        trends = get_trends(
            top_n=posts_per_run,
            safe_only=True,
            shuffle=True,
        )
    except Exception as e:
        logger.error("[トレンド取得] 致命的エラー: %s", e)
        summary.add_failure(f"トレンド取得失敗: {e}")
        summary.log()
        return summary

    if not trends:
        logger.error("[トレンド取得] 有効なトレンドが0件でした。処理を終了します。")
        summary.add_failure("有効トレンドなし")
        summary.log()
        return summary

    logger.info("[トレンド取得] 完了: %d件取得", len(trends))
    for t in trends:
        logger.info("  → %s", t)

    # --------------------------------------------------------
    # STEP 2〜5: 各トレンドを処理
    # --------------------------------------------------------
    for i, trend in enumerate(trends):
        if i > 0:
            logger.info("次の投稿まで %.1f秒 待機...", interval_between_posts)
            time.sleep(interval_between_posts)

        logger.info("--- [%d/%d] キーワード: 「%s」 ---", i + 1, len(trends), trend.keyword)

        try:
            result = process_one_trend(
                trend,
                dry_run=dry_run,
                with_image=with_image,
            )
            summary.add_success(result)
        except Exception as e:
            summary.add_failure(f"「{trend.keyword}」: {e}")

    summary.log()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="X アフィリエイトボット",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="投稿せずに生成内容だけ確認する",
    )
    parser.add_argument(
        "--no-image", action="store_true",
        help="画像生成をスキップして文字のみ投稿する",
    )
    parser.add_argument(
        "--posts", type=int,
        default=int(os.environ.get("POSTS_PER_RUN", "1")),
        help="1回の実行で投稿する件数 (デフォルト: POSTS_PER_RUN 環境変数 or 1)",
    )
    args = parser.parse_args()

    summary = run(
        posts_per_run=args.posts,
        dry_run=args.dry_run,
        with_image=not args.no_image,
    )

    # 1件でも失敗があれば終了コード1（GitHub Actions でエラーを検知できるように）
    if summary.failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
