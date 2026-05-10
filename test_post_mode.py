"""
test_post_mode.py
-----------------
投稿モード（normal / affiliate）切り替えロジックのユニットテスト。

実行:
  pytest test_post_mode.py -v
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import tweepy

sys.path.insert(0, str(Path(__file__).parent / "src"))


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _make_content(text="テスト投稿 #Tech"):
    from ai_generator import GeneratedContent
    return GeneratedContent(
        post_text=text,
        image_prompt="test prompt",
        hashtags=["#Tech"],
        affiliate_category="tech",
        hook_type="curiosity",
    )


def _make_affiliate(url="https://example.com/affiliate"):
    from affiliate import AffiliateLink
    return AffiliateLink(
        url=url,
        category="tech",
        is_dummy=False,
        display_label="💻 最新ガジェットはこちら",
    )


# ---------------------------------------------------------------------------
# build_tweet_text のテスト
# ---------------------------------------------------------------------------

class TestBuildTweetText:
    def test_affiliate_mode_appends_url(self):
        """affiliate モードではアフィリ URL が本文末尾に付く。"""
        from x_poster import build_tweet_text
        text = build_tweet_text(_make_content(), _make_affiliate(), post_mode="affiliate")
        assert "https://example.com/affiliate" in text
        assert text.endswith("https://example.com/affiliate")

    def test_normal_mode_no_url(self):
        """normal モードではアフィリ URL が含まれない。"""
        from x_poster import build_tweet_text
        text = build_tweet_text(_make_content(), _make_affiliate(), post_mode="normal")
        assert "https://example.com/affiliate" not in text
        assert "テスト投稿" in text

    def test_none_affiliate_always_omits_url(self):
        """affiliate_link=None のときはモードに関わらず URL なし。"""
        from x_poster import build_tweet_text
        content = _make_content()
        text = build_tweet_text(content, None, post_mode="affiliate")
        assert text == content.post_text

    def test_affiliate_mode_format(self):
        """affiliate モードの本文は {post_text}\\n{url} の形式になる。"""
        from x_poster import build_tweet_text
        content = _make_content("本文テスト #Tech")
        text = build_tweet_text(content, _make_affiliate(), post_mode="affiliate")
        assert text == "本文テスト #Tech\nhttps://example.com/affiliate"


# ---------------------------------------------------------------------------
# decide_post_mode のテスト
# ---------------------------------------------------------------------------

class TestDecidePostMode:
    def test_ratio_zero_always_normal(self):
        """AFFILIATE_RATIO=0.0 のとき常に normal になる。"""
        import main
        modes = {main.decide_post_mode(ratio=0.0) for _ in range(30)}
        assert modes == {"normal"}

    def test_ratio_one_always_affiliate(self):
        """AFFILIATE_RATIO=1.0 のとき常に affiliate になる。"""
        import main
        modes = {main.decide_post_mode(ratio=1.0) for _ in range(30)}
        assert modes == {"affiliate"}

    def test_ratio_half_produces_both(self):
        """random.random の結果に応じて両モードが返る。"""
        import main
        import random as _random
        with patch.object(_random, "random", side_effect=[0.3, 0.7, 0.4, 0.6]):
            modes = [main.decide_post_mode(ratio=0.5) for _ in range(4)]
        assert "affiliate" in modes
        assert "normal" in modes

    def test_ratio_clamp_above_one(self):
        """AFFILIATE_RATIO が 1.0 超でも affiliate に固定される。"""
        import main
        modes = {main.decide_post_mode(ratio=2.0) for _ in range(20)}
        assert modes == {"affiliate"}

    def test_ratio_clamp_below_zero(self):
        """AFFILIATE_RATIO が 0.0 未満でも normal に固定される。"""
        import main
        modes = {main.decide_post_mode(ratio=-1.0) for _ in range(20)}
        assert modes == {"normal"}


# ---------------------------------------------------------------------------
# affiliate.py の ASP 切り替えテスト
# ---------------------------------------------------------------------------

class TestAffiliateLinkAsp:
    def test_default_asp_is_rakuten(self):
        """AFFILIATE_ASP 未設定のときは楽天リンクを返す。"""
        import affiliate
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("AFFILIATE_ASP", None)
            links = affiliate._get_links_dict()
        assert links is affiliate.AFFILIATE_LINKS

    def test_asp_amazon(self):
        """AFFILIATE_ASP=amazon のとき Amazon リンクを返す。"""
        import os
        import affiliate
        with patch.dict("os.environ", {"AFFILIATE_ASP": "amazon"}):
            links = affiliate._get_links_dict()
        assert links is affiliate.AFFILIATE_LINKS_AMAZON

    def test_asp_rakuten_explicit(self):
        """AFFILIATE_ASP=rakuten を明示したときも楽天リンクを返す。"""
        import os
        import affiliate
        with patch.dict("os.environ", {"AFFILIATE_ASP": "rakuten"}):
            links = affiliate._get_links_dict()
        assert links is affiliate.AFFILIATE_LINKS


# ---------------------------------------------------------------------------
# _ensure_pr_label のテスト（優先1: #PR 強制挿入）
# ---------------------------------------------------------------------------

class TestEnsurePrLabel:
    def test_pr_added_when_missing(self):
        """#PR がない投稿本文に自動付加される。"""
        from ai_generator import _ensure_pr_label
        result = _ensure_pr_label("テスト投稿 #Tech")
        assert "#PR" in result

    def test_pr_not_duplicated_when_present(self):
        """すでに #PR がある場合は重複しない。"""
        from ai_generator import _ensure_pr_label
        text = "テスト投稿 #PR #Tech"
        result = _ensure_pr_label(text)
        assert result.count("#PR") == 1

    def test_pr_added_within_post_body_limit(self):
        """付加後も POST_BODY_LIMIT 以内に収まる。"""
        from ai_generator import _ensure_pr_label, POST_BODY_LIMIT, _count_x_chars
        text = "短いテスト #Tech"
        result = _ensure_pr_label(text)
        assert "#PR" in result
        assert _count_x_chars(result) <= POST_BODY_LIMIT

    def test_pr_trims_text_at_limit(self):
        """POST_BODY_LIMIT ちょうどの本文でもトリムして #PR を収める。"""
        from ai_generator import _ensure_pr_label, POST_BODY_LIMIT, _count_x_chars
        long_text = "あ" * POST_BODY_LIMIT  # 制限ぴったり、#PR が入らない
        result = _ensure_pr_label(long_text)
        assert "#PR" in result
        assert _count_x_chars(result) <= POST_BODY_LIMIT

    def test_pr_already_present_text_unchanged(self):
        """#PR 済みのテキストは変更されない。"""
        from ai_generator import _ensure_pr_label
        text = "実は知らなかった？AIの裏側 #Tech #PR"
        assert _ensure_pr_label(text) == text


# ---------------------------------------------------------------------------
# _validate_required_env のテスト（優先2: 起動時バリデーション）
# ---------------------------------------------------------------------------

class TestValidateRequiredEnv:
    def test_all_set_returns_empty(self):
        """全必須キーが揃っているとき空リストを返す。"""
        import main
        env = {
            "ANTHROPIC_API_KEY":     "sk-test",
            "X_API_KEY":             "key",
            "X_API_SECRET":          "secret",
            "X_ACCESS_TOKEN":        "token",
            "X_ACCESS_TOKEN_SECRET": "token_secret",
        }
        with patch.dict(os.environ, env):
            result = main._validate_required_env(dry_run=False)
        assert result == []

    def test_dry_run_skips_x_keys(self):
        """dry_run=True のとき X API キーチェックをスキップする。"""
        import main
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=True):
            result = main._validate_required_env(dry_run=True)
        assert result == []

    def test_missing_anthropic_key_detected(self):
        """ANTHROPIC_API_KEY が未設定のとき検出される。"""
        import main
        with patch.dict(os.environ, {}, clear=True):
            result = main._validate_required_env(dry_run=True)
        assert any("ANTHROPIC_API_KEY" in r for r in result)

    def test_missing_x_keys_detected_in_prod(self):
        """dry_run=False で X API キーが未設定のとき検出される。"""
        import main
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=True):
            result = main._validate_required_env(dry_run=False)
        missing_keys = [r for r in result if "X_API_KEY" in r or "X_ACCESS_TOKEN" in r]
        assert len(missing_keys) >= 2

    def test_dry_run_still_requires_anthropic(self):
        """dry_run=True でも ANTHROPIC_API_KEY は必須。"""
        import main
        with patch.dict(os.environ, {}, clear=True):
            result = main._validate_required_env(dry_run=True)
        assert any("ANTHROPIC_API_KEY" in r for r in result)


# ---------------------------------------------------------------------------
# _is_retryable_x_error のテスト（優先3: 403 Forbidden リトライ除外）
# ---------------------------------------------------------------------------

class TestIsRetryableXError:
    def test_non_tweepy_exception_not_retryable(self):
        """TweepyException 以外はリトライしない。"""
        from x_poster import _is_retryable_x_error
        assert _is_retryable_x_error(ValueError("network error")) is False
        assert _is_retryable_x_error(RuntimeError("boom")) is False

    def test_generic_tweepy_exception_is_retryable(self):
        """一般的な TweepyException（429等）はリトライする。"""
        from x_poster import _is_retryable_x_error
        exc = tweepy.errors.TweepyException("too many requests")
        assert _is_retryable_x_error(exc) is True

    def test_forbidden_not_retryable(self):
        """403 Forbidden はリトライしない。"""
        from x_poster import _is_retryable_x_error

        class _Forbidden(tweepy.errors.Forbidden):
            def __init__(self):
                pass  # response 引数なしで生成するためのサブクラス

        assert _is_retryable_x_error(_Forbidden()) is False

    def test_bad_request_not_retryable(self):
        """400 BadRequest はリトライしない。"""
        from x_poster import _is_retryable_x_error

        class _BadRequest(tweepy.errors.BadRequest):
            def __init__(self):
                pass

        assert _is_retryable_x_error(_BadRequest()) is False


# ---------------------------------------------------------------------------
# count_today_posts のテスト（優先4: DAILY_MAX_POSTS 上限チェック）
# ---------------------------------------------------------------------------

class TestCountTodayPosts:
    def _make_record(self, dry_run: bool = False, hours_ago: float = 1.0) -> dict:
        """テスト用の投稿レコードを生成する。"""
        from datetime import datetime, timezone, timedelta
        posted_at = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        return {
            "posted_at":  posted_at.isoformat(),
            "dry_run":    dry_run,
            "trend_name": "テストキーワード",
            "post_mode":  "normal",
        }

    def test_counts_only_real_posts(self, tmp_path):
        """dry_run=False の投稿だけをカウントする。"""
        import json
        from result_logger import count_today_posts
        log = tmp_path / "posts.jsonl"
        records = [
            self._make_record(dry_run=False),  # カウントされる
            self._make_record(dry_run=False),  # カウントされる
            self._make_record(dry_run=True),   # dry_run なのでカウントされない
        ]
        log.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n")
        assert count_today_posts(log) == 2

    def test_excludes_old_posts(self, tmp_path):
        """24時間より古い投稿はカウントしない。"""
        import json
        from result_logger import count_today_posts
        log = tmp_path / "posts.jsonl"
        records = [
            self._make_record(dry_run=False, hours_ago=1),   # 1時間前 → カウントされる
            self._make_record(dry_run=False, hours_ago=25),  # 25時間前 → カウントされない
        ]
        log.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n")
        assert count_today_posts(log) == 1

    def test_empty_log_returns_zero(self, tmp_path):
        """ログが空なら 0 を返す。"""
        from result_logger import count_today_posts
        log = tmp_path / "posts.jsonl"
        log.write_text("")
        assert count_today_posts(log) == 0

    def test_nonexistent_log_returns_zero(self, tmp_path):
        """ログファイルが存在しない場合も 0 を返す。"""
        from result_logger import count_today_posts
        assert count_today_posts(tmp_path / "nonexistent.jsonl") == 0


# ---------------------------------------------------------------------------
# affiliate is_dummy フォールバックのテスト
# ---------------------------------------------------------------------------

def _make_fake_content(category: str = "sports") -> "GeneratedContent":
    from ai_generator import GeneratedContent
    return GeneratedContent(
        post_text="テスト投稿 #Tech #PR",
        image_prompt="test prompt",
        hashtags=["#Tech", "#PR"],
        affiliate_category=category,
        hook_type="curiosity",
    )


def _make_fake_result(url: str = "") -> "PostResult":
    from x_poster import PostResult
    return PostResult(
        tweet_id="test_id",
        tweet_url="https://x.com/dry_run",
        full_text="テスト投稿 #Tech #PR",
        media_id=None,
        affiliate_url=url,
        char_count=20,
    )


class TestAffiliateDummyFallback:
    def test_is_dummy_falls_back_to_normal(self):
        """
        affiliate モードで is_dummy=True のリンクが返ったとき、
        normal にダウングレードして post_to_x が呼ばれる。
        """
        from unittest.mock import patch
        import main
        from trend_collector import TrendItem
        from affiliate import AffiliateLink

        trend = TrendItem(keyword="テストキーワード", approx_traffic="1000+")
        dummy_link = AffiliateLink(
            url="https://www.rakuten.co.jp/search/sports/?dummy=REPLACE_ME",
            category="sports",
            is_dummy=True,
            display_label="🏃 スポーツ用品はこちら",
        )

        with patch("main.generate_post_content", return_value=_make_fake_content("sports")), \
             patch("main.get_affiliate_link", return_value=dummy_link), \
             patch("main.post_to_x", return_value=_make_fake_result()) as mock_post, \
             patch("main.save_post_result"):

            main.process_one_trend(trend, dry_run=True, with_image=False, post_mode="affiliate")

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["post_mode"] == "normal", \
            "is_dummy=True なら normal にフォールバックすべき"
        assert call_kwargs["affiliate_link"] is None, \
            "フォールバック時はリンクを渡さない"

    def test_real_link_keeps_affiliate_mode(self):
        """
        affiliate モードで is_dummy=False のリンクが返ったとき、
        affiliate モードのまま post_to_x が呼ばれる。
        """
        from unittest.mock import patch
        import main
        from trend_collector import TrendItem
        from affiliate import AffiliateLink

        trend = TrendItem(keyword="テックキーワード", approx_traffic="2000+")
        real_link = AffiliateLink(
            url="https://a.r10.to/hXU6st",
            category="tech",
            is_dummy=False,
            display_label="💻 最新ガジェットはこちら",
        )

        with patch("main.generate_post_content", return_value=_make_fake_content("tech")), \
             patch("main.get_affiliate_link", return_value=real_link), \
             patch("main.post_to_x", return_value=_make_fake_result("https://a.r10.to/hXU6st")) as mock_post, \
             patch("main.save_post_result"):

            main.process_one_trend(trend, dry_run=True, with_image=False, post_mode="affiliate")

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["post_mode"] == "affiliate", \
            "is_dummy=False なら affiliate のまま維持すべき"
        assert call_kwargs["affiliate_link"] is not None
        assert call_kwargs["affiliate_link"].url == "https://a.r10.to/hXU6st"

    def test_normal_mode_never_calls_get_affiliate_link(self):
        """
        normal モードでは get_affiliate_link が呼ばれない。
        """
        from unittest.mock import patch
        import main
        from trend_collector import TrendItem

        trend = TrendItem(keyword="テストキーワード", approx_traffic="1000+")

        with patch("main.generate_post_content", return_value=_make_fake_content()), \
             patch("main.get_affiliate_link") as mock_get_link, \
             patch("main.post_to_x", return_value=_make_fake_result()), \
             patch("main.save_post_result"):

            main.process_one_trend(trend, dry_run=True, with_image=False, post_mode="normal")

        mock_get_link.assert_not_called()
