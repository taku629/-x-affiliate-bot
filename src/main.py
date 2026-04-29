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
import random
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
from ai_generator import ACTIVE_HOOK_TYPES, GeneratedContent, PostMode, generate_post_content
from image_generator import UploadResult, generate_and_upload
from affiliate import AffiliateLink, get_affiliate_link
from x_poster import PostResult, post_to_x
from result_logger import (
    build_post_record, save_post_result,
    load_recent_posts, is_duplicate_trend, count_today_posts,
)

# カテゴリ許可リスト（カンマ区切り環境変数。未設定なら全カテゴリ許可）
# 例: ALLOWED_CATEGORIES="entertainment,tech,food,health,fashion"
_raw_allowed = os.environ.get("ALLOWED_CATEGORIES", "")
ALLOWED_CATEGORIES: Optional[set] = (
    {c.strip().lower() for c in _raw_allowed.split(",") if c.strip()}
    if _raw_allowed else None
)

# アフィリエイト投稿の割合（0.0〜1.0）。残りは通常投稿になる。
_raw_ratio = os.environ.get("AFFILIATE_RATIO", "0.2")
try:
    AFFILIATE_RATIO: float = max(0.0, min(1.0, float(_raw_ratio)))
except ValueError:
    AFFILIATE_RATIO = 0.2
    logger.warning("AFFILIATE_RATIO の値が不正です: '%s'. デフォルト値 0.2 を使用します", _raw_ratio)

# 投稿テーマを固定する場合に指定（例: "USB-C充電器"）。空ならトレンド依存。
_raw_product_theme = os.environ.get("PRODUCT_THEME", "").strip()
PRODUCT_THEME: Optional[str] = _raw_product_theme if _raw_product_theme else None

# 1日（24時間）の最大投稿件数。X Free枠（50件/24h）の誤設定ガード。
_raw_daily_max = os.environ.get("DAILY_MAX_POSTS", "10")
try:
    DAILY_MAX_POSTS: int = int(_raw_daily_max)
    if DAILY_MAX_POSTS <= 0:
        raise ValueError("0 以下は無効")
except ValueError:
    DAILY_MAX_POSTS = 10
    logger.warning("DAILY_MAX_POSTS の値が不正です: '%s'. デフォルト値 10 を使用します", _raw_daily_max)


def _validate_required_env(dry_run: bool = False) -> list[str]:
    """
    起動時に必須環境変数の存在を確認し、未設定のキー名リストを返す。

    dry_run=True のときは X API キーのチェックをスキップする
    （投稿しないのでクレデンシャルが不要なため）。
    """
    always_required = {
        "ANTHROPIC_API_KEY": "テキスト生成 (Claude API)",
    }
    post_required = {
        "X_API_KEY":             "X への投稿",
        "X_API_SECRET":          "X への投稿",
        "X_ACCESS_TOKEN":        "X への投稿",
        "X_ACCESS_TOKEN_SECRET": "X への投稿",
    }
    checks = dict(always_required)
    if not dry_run:
        checks.update(post_required)
    return [
        f"{k}  ({desc})"
        for k, desc in checks.items()
        if not os.environ.get(k)
    ]


def decide_post_mode(ratio: Optional[float] = None) -> PostMode:
    """
    アフィリエイト投稿か通常投稿かを確率で決定する。

    Parameters
    ----------
    ratio : アフィリエイト投稿にする確率（省略時は AFFILIATE_RATIO 環境変数）
    """
    r = ratio if ratio is not None else AFFILIATE_RATIO
    return "affiliate" if random.random() < r else "normal"


class _CategorySkipped(Exception):
    """カテゴリ許可リスト外のためスキップ（失敗カウントしない）。"""


# =====================================================================
# 実行結果のサマリー
# =====================================================================

@dataclass
class RunSummary:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    category_skipped: int = 0      # ALLOWED_CATEGORIES でスキップされた件数
    daily_limit_skipped: int = 0   # DAILY_MAX_POSTS 超過でスキップされた件数
    duplicate_skipped: int = 0     # 過去24時間の重複キーワードでスキップされた件数
    trends_fetched: int = 0        # get_trends() で取得できたトレンド数
    results: list[PostResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    post_details: list[dict] = field(default_factory=list)  # per-post 詳細情報

    def add_success(self, result: PostResult, detail: Optional[dict] = None) -> None:
        self.total += 1
        self.succeeded += 1
        self.results.append(result)
        if detail is not None:
            self.post_details.append({**detail, "tweet_url": result.tweet_url})

    def add_failure(self, error: str) -> None:
        self.total += 1
        self.failed += 1
        self.errors.append(error)

    def log(self) -> None:
        logger.info("=" * 50)
        logger.info("実行サマリー: %d件中 %d件成功 / %d件失敗",
                    self.total, self.succeeded, self.failed)
        logger.info("  取得トレンド数      = %d件", self.trends_fetched)
        logger.info("  カテゴリスキップ    = %d件", self.category_skipped)
        logger.info("  日次上限スキップ    = %d件", self.daily_limit_skipped)
        logger.info("  重複スキップ        = %d件", self.duplicate_skipped)
        for r in self.results:
            logger.info("  ✓ %s", r.tweet_url)
        for e in self.errors:
            logger.error("  ✗ %s", e)
        for d in self.post_details:
            logger.info(
                "  detail: theme=%s hook=%s category=%s cta=%s",
                d.get("product_theme", "-"),
                d.get("hook_type", "-"),
                d.get("category", "-"),
                d.get("cta_used", "-"),
            )
        logger.info("=" * 50)

        # GitHub Actions Step Summary への書き出し
        ghs = os.environ.get("GITHUB_STEP_SUMMARY")
        if ghs:
            with open(ghs, "a", encoding="utf-8") as f:
                f.write("\n### 投稿結果\n\n")
                f.write(f"| | 件数 |\n|---|---|\n")
                f.write(f"| ✅ 成功 | {self.succeeded} |\n")
                f.write(f"| ❌ 失敗 | {self.failed} |\n")
                f.write(f"| ⏭ カテゴリスキップ | {self.category_skipped} |\n")
                f.write(f"| ⛔ 日次上限スキップ | {self.daily_limit_skipped} |\n")
                f.write(f"| 🔁 重複スキップ | {self.duplicate_skipped} |\n")
                f.write(f"| 📥 取得トレンド数 | {self.trends_fetched} |\n")
                if self.post_details:
                    f.write("\n#### 投稿詳細\n\n")
                    f.write("| # | product_theme | hook_type | category | CTA | affiliate_url | tweet |\n")
                    f.write("|---|---|---|---|---|---|---|\n")
                    for i, d in enumerate(self.post_details, 1):
                        aff_url = d.get("affiliate_url", "")
                        aff_cell = f"[link]({aff_url})" if aff_url else "-"
                        tw_url = d.get("tweet_url", "")
                        tw_cell = f"[link]({tw_url})" if tw_url and tw_url != "https://x.com/dry_run" else "DRY RUN"
                        f.write(
                            f"| {i} | {d.get('product_theme','-')} "
                            f"| {d.get('hook_type','-')} "
                            f"| {d.get('category','-')} "
                            f"| {d.get('cta_used','-')} "
                            f"| {aff_cell} "
                            f"| {tw_cell} |\n"
                        )
                for e in self.errors:
                    f.write(f"\n- ❌ `{e}`\n")


# =====================================================================
# パイプライン: 1件のトレンドを処理
# =====================================================================

def process_one_trend(
    trend: TrendItem,
    *,
    dry_run: bool = False,
    with_image: bool = True,
    use_placeholder_on_image_failure: bool = True,
    allowed_categories: Optional[set] = None,
    post_mode: PostMode = "affiliate",
    product_theme: Optional[str] = None,
) -> tuple[PostResult, dict]:
    """
    トレンド1件に対してテキスト生成→画像→投稿までを実行し (PostResult, detail) を返す。
    各ステップでエラーが起きても詳細なログを出力してから再 raise する。
    allowed_categories が指定されたカテゴリ外なら _CategorySkipped を raise する。
    post_mode が "normal" のときはアフィリエイトリンク取得をスキップする。
    product_theme が指定されたときはカテゴリフィルタをバイパスし、
    テーマ固定で投稿文を生成する。
    """
    step = "初期化"
    try:
        # --------------------------------------------------------
        # STEP A: テキスト生成（Claude）
        # --------------------------------------------------------
        step = "テキスト生成 (Claude)"
        logger.info(
            "[%s] 開始: 「%s」 (mode=%s theme=%s)",
            step, trend.keyword, post_mode, product_theme or "-",
        )
        content: GeneratedContent = generate_post_content(
            trend, post_mode=post_mode, product_theme=product_theme,
        )
        logger.info(
            "[%s] 完了: %d字 / カテゴリ=%s hook=%s cta=%s",
            step, content.post_char_count, content.affiliate_category,
            content.hook_type, content.cta_used or "-",
        )

        # カテゴリ許可リストチェック（product_theme 固定時はバイパス）
        if allowed_categories and not product_theme and content.affiliate_category not in allowed_categories:
            logger.info(
                "[カテゴリスキップ] '%s' は許可リスト外のためスキップします (許可: %s)",
                content.affiliate_category, sorted(allowed_categories),
            )
            raise _CategorySkipped(content.affiliate_category)

        # --------------------------------------------------------
        # STEP B: 画像生成＆アップロード（HuggingFace → X v1.1）
        # --------------------------------------------------------
        media_id: Optional[str] = None
        if with_image and not dry_run:
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
            reason = "dry_run モード" if dry_run else "--no-image フラグ"
            logger.info("[画像生成] %s のためスキップ", reason)

        # --------------------------------------------------------
        # STEP C: アフィリエイトリンク取得（affiliate モードのみ）
        # --------------------------------------------------------
        # effective_mode: is_dummy フォールバック後の実際のモード。
        # affiliate を選んでもリンク未設定カテゴリなら normal に下げて確実に投稿する。
        effective_mode: PostMode = post_mode
        affiliate: Optional[AffiliateLink] = None
        if post_mode == "affiliate":
            step = "アフィリエイトリンク取得"
            affiliate = get_affiliate_link(content.affiliate_category)
            logger.info(
                "[%s] category=%s is_dummy=%s",
                step, affiliate.category, affiliate.is_dummy,
            )
            if affiliate.is_dummy:
                # リンク未設定カテゴリ → normal にダウングレードして投稿を確実に実行する。
                # tech 以外のカテゴリで affiliate が選ばれても投稿0件にならない。
                logger.warning(
                    "[アフィリフォールバック] category='%s' のリンクが未設定（REPLACE_ME）のため"
                    " normal モードで投稿します。"
                    " src/affiliate.py の REPLACE_ME を実URLに差し替えると affiliate 投稿になります。",
                    affiliate.category,
                )
                effective_mode = "normal"
                affiliate = None
        else:
            logger.info("[アフィリエイトリンク取得] normal モードのためスキップ")

        # --------------------------------------------------------
        # STEP D: X への投稿 (v2)
        # --------------------------------------------------------
        step = "X投稿 (v2)"
        logger.info("[%s] 開始 (dry_run=%s mode=%s)", step, dry_run, effective_mode)
        result: PostResult = post_to_x(
            content=content,
            affiliate_link=affiliate,
            media_id=media_id,
            post_mode=effective_mode,
            dry_run=dry_run,
        )
        logger.info("[%s] 完了: %s", step, result.tweet_url)

        # 投稿結果を JSONL に保存
        save_post_result(build_post_record(
            trend_name=trend.keyword,
            category=content.affiliate_category,
            affiliate_url=affiliate.url if affiliate else "",
            post_text=result.full_text,
            tweet_id=result.tweet_id,
            tweet_url=result.tweet_url,
            dry_run=dry_run,
            with_image=with_image,
            media_id=result.media_id,
            hook_type=getattr(content, "hook_type", None),
            post_mode=effective_mode,
        ))

        detail = {
            "product_theme": product_theme or trend.keyword,
            "hook_type": content.hook_type,
            "category": content.affiliate_category,
            "cta_used": content.cta_used,
            "affiliate_url": affiliate.url if affiliate else "",
        }
        return result, detail

    except _CategorySkipped:
        raise  # エラーログなしで上位に伝える

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
    logger.info("  posts_per_run      = %d", posts_per_run)
    logger.info("  dry_run            = %s", dry_run)
    logger.info("  with_image         = %s", with_image)
    logger.info("  affiliate_ratio    = %.0f%%", AFFILIATE_RATIO * 100)
    logger.info("  daily_max_posts    = %d", DAILY_MAX_POSTS)
    logger.info("  allowed_categories = %s", sorted(ALLOWED_CATEGORIES) if ALLOWED_CATEGORIES else "全カテゴリ")
    logger.info("  product_theme      = %s", PRODUCT_THEME or "(トレンド依存)")
    logger.info("  active_hook_types  = %s", ACTIVE_HOOK_TYPES)
    logger.info("=" * 50)

    # --------------------------------------------------------
    # 起動時の必須環境変数チェック
    # --------------------------------------------------------
    missing_env = _validate_required_env(dry_run=dry_run)
    if missing_env:
        for var in missing_env:
            logger.error("[環境変数未設定] %s", var)
        logger.error(
            "上記 %d 件の環境変数を .env または GitHub Secrets に設定してください。",
            len(missing_env),
        )
        summary.add_failure(f"必須環境変数が未設定: {len(missing_env)} 件")
        summary.log()
        return summary

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
    summary.trends_fetched = len(trends)
    for t in trends:
        logger.info("  → %s", t)

    # --------------------------------------------------------
    # 重複チェック用: 直近24時間の投稿記録を読み込む
    # --------------------------------------------------------
    recent_posts = load_recent_posts()
    if recent_posts:
        logger.info("[重複チェック] 過去24時間の投稿: %d件", len(recent_posts))

    # --------------------------------------------------------
    # STEP 2〜5: 各トレンドを処理
    # --------------------------------------------------------
    for i, trend in enumerate(trends):
        # 1日の投稿上限チェック（dry_run 分は除外してカウント）
        if not dry_run:
            today_count = count_today_posts()
            if today_count >= DAILY_MAX_POSTS:
                logger.warning(
                    "[投稿上限] 直近24時間の投稿が %d 件に達しました（上限: DAILY_MAX_POSTS=%d）。"
                    "残りの投稿をスキップします。",
                    today_count, DAILY_MAX_POSTS,
                )
                summary.daily_limit_skipped = len(trends) - i
                break

        # 重複スキップ
        if is_duplicate_trend(trend.keyword, recent_posts):
            logger.warning(
                "[重複スキップ] 「%s」は過去24時間に投稿済みです", trend.keyword
            )
            summary.duplicate_skipped += 1
            continue

        if i > 0:
            logger.info("次の投稿まで %.1f秒 待機...", interval_between_posts)
            time.sleep(interval_between_posts)

        mode = decide_post_mode()
        logger.info("--- [%d/%d] キーワード: 「%s」 mode=%s ---", i + 1, len(trends), trend.keyword, mode)

        try:
            result, detail = process_one_trend(
                trend,
                dry_run=dry_run,
                with_image=with_image,
                allowed_categories=ALLOWED_CATEGORIES,
                post_mode=mode,
                product_theme=PRODUCT_THEME,
            )
            summary.add_success(result, detail)
            # 同一ランでの重複を防ぐためにメモリ上のリストにも追加
            recent_posts.append({
                "trend_name": trend.keyword,
                "posted_at": datetime.now(timezone.utc).isoformat(),
            })
        except _CategorySkipped as e:
            logger.info("[カテゴリスキップ] 「%s」: %s", trend.keyword, e)
            summary.category_skipped += 1
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

    # dry_run でないのに 1件も投稿されなかった場合は exit 2 で失敗扱いにする。
    # カテゴリスキップや日次上限が原因で success のまま 0 投稿になるのを防ぐ。
    if not args.dry_run and summary.succeeded == 0:
        logger.error(
            "[0件警告] 1件も投稿されませんでした。exit code 2 で終了します。\n"
            "  取得トレンド数      = %d件\n"
            "  重複スキップ        = %d件  (直近24hに同キーワードを投稿済み)\n"
            "  カテゴリスキップ    = %d件  (ALLOWED_CATEGORIES=%s)\n"
            "  日次上限スキップ    = %d件  (DAILY_MAX_POSTS=%d)\n"
            "  失敗                = %d件\n"
            "対処: 重複が多い場合はキャッシュクリア or トレンド取得数を増やす。\n"
            "      ALLOWED_CATEGORIES / DAILY_MAX_POSTS も確認してください。",
            summary.trends_fetched,
            summary.duplicate_skipped,
            summary.category_skipped,
            sorted(ALLOWED_CATEGORIES) if ALLOWED_CATEGORIES else "全カテゴリ",
            summary.daily_limit_skipped,
            DAILY_MAX_POSTS,
            summary.failed,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
