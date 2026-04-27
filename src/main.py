"""X Affiliate Bot - エントリーポイント

使い方:
  python src/main.py               # 1件投稿（通常実行）
  python src/main.py --dry-run     # 投稿内容を表示するだけ（X投稿なし）
  python src/main.py --no-image    # 画像なしで投稿
  python src/main.py --posts 3     # 1回の実行で3件投稿
"""

import argparse
import os
import sys
import time

from dotenv import load_dotenv

import trend_collector
import ai_generator
import affiliate
import image_generator
import x_poster

load_dotenv()


def run_once(dry_run: bool, no_image: bool) -> bool:
    """パイプラインを1回実行して投稿する。成功したら True を返す。"""

    # 1. トレンド取得
    print("[1/5] Googleトレンドを取得中...")
    trends = trend_collector.fetch_trends()
    if not trends:
        print("  安全なトレンドが見つかりませんでした。スキップします。")
        return False
    keyword = trend_collector.pick_trend(trends)
    print(f"  選択したトレンド: {keyword}")

    # 2. AI で投稿文生成
    print("[2/5] Gemini でツイート文を生成中...")
    try:
        generated = ai_generator.generate(keyword)
    except Exception as exc:
        print(f"  AI生成エラー: {exc}")
        return False
    tweet_text = generated["tweet"]
    image_prompt = generated["image_prompt"]
    category = generated["category"]
    print(f"  カテゴリ: {category}")
    print(f"  ツイート文: {tweet_text}")

    # 3. アフィリエイトリンク付与
    print("[3/5] アフィリエイトリンクを取得中...")
    link = affiliate.get_link(category)
    if not affiliate.is_configured(category):
        print(f"  警告: カテゴリ '{category}' のURLが未設定です（REPLACE_ME のまま）")
    full_text = f"{tweet_text}\n{link}"
    # X は URL を23字にカウントするためここで長さを考慮しない（tweepyが処理）

    # 4. 画像生成・アップロード
    media_id: str | None = None
    if not no_image:
        print("[4/5] 画像を生成中（HuggingFace）...")
        img_bytes = image_generator.generate_image(image_prompt)
        if img_bytes:
            try:
                media_id = image_generator.upload_to_x(img_bytes)
                print(f"  画像アップロード完了: media_id={media_id}")
            except Exception as exc:
                print(f"  画像アップロードエラー（テキストのみで続行）: {exc}")
        else:
            print("  画像生成に失敗しました（テキストのみで続行）")
    else:
        print("[4/5] --no-image が指定されているため画像生成をスキップ")

    # 5. X に投稿
    print("[5/5] X に投稿中...")
    print(f"  本文:\n{full_text}")
    if dry_run:
        print("  [DRY RUN] 実際の投稿はしません")
        return True

    try:
        tweet_id = x_poster.post_tweet(full_text, media_id=media_id)
        print(f"  投稿完了! tweet_id={tweet_id}")
        return True
    except Exception as exc:
        print(f"  投稿エラー: {exc}")
        return False


def main():
    parser = argparse.ArgumentParser(description="X Affiliate Bot")
    parser.add_argument("--dry-run", action="store_true", help="Xへの投稿を行わず内容だけ確認する")
    parser.add_argument("--no-image", action="store_true", help="画像生成・アップロードをスキップする")
    parser.add_argument("--posts", type=int, default=int(os.getenv("POSTS_PER_RUN", "1")),
                        help="1回の実行で投稿する件数（デフォルト: 1）")
    args = parser.parse_args()

    success_count = 0
    for i in range(args.posts):
        if args.posts > 1:
            print(f"\n=== 投稿 {i + 1}/{args.posts} ===")
        ok = run_once(dry_run=args.dry_run, no_image=args.no_image)
        if ok:
            success_count += 1
        if i < args.posts - 1:
            time.sleep(5)  # API レート制限対策

    print(f"\n完了: {success_count}/{args.posts} 件の投稿が成功しました")
    sys.exit(0 if success_count > 0 else 1)


if __name__ == "__main__":
    main()
