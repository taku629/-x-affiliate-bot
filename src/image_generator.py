"""
image_generator.py
------------------
Hugging Face Inference API（新エンドポイント: router.huggingface.co）で
画像を生成し、X API v1.1 の media/upload に送信して media_id を取得する。

HuggingFace 無料枠制限:
  - 認証ありでもレート制限あり（モデルにより異なる）
  - モデルが "loading" 状態の場合は estimated_time 秒待機してリトライ

X media/upload 仕様:
  - エンドポイント: https://upload.twitter.com/1.1/media/upload.json
  - 認証: OAuth 1.0a
  - 画像上限: 5MB (PNG/JPEG/GIF/WEBP)
  - tweepy.API.media_upload(filename, file=BytesIO) で対応
"""

from __future__ import annotations

import io
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import requests
import tweepy
from PIL import Image
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

logger = logging.getLogger(__name__)

# =====================================================================
# 定数
# =====================================================================

# HuggingFace 新 Serverless Inference エンドポイント（2025年以降）
HF_ROUTER_BASE = "https://router.huggingface.co/hf-inference/models"

# フォールバック順のモデルリスト（速い・安定・無料枠が広いものを優先）
HF_MODEL_CANDIDATES: list[str] = [
    "black-forest-labs/FLUX.1-schnell",          # 最速・高品質（第1候補）
    "stabilityai/stable-diffusion-xl-base-1.0",  # SDXL（第2候補）
    "stabilityai/stable-diffusion-2-1",           # SD 2.1（第3候補）
]

# 生成画像の最大サイズ（X の 5MB 制限に合わせてリサイズ）
MAX_IMAGE_BYTES = 4 * 1024 * 1024   # 4MB（余裕を持って）
TARGET_SIZE     = (1024, 1024)       # HFデフォルト出力サイズ

# モデルロード待機の上限（秒）
MAX_LOADING_WAIT_SEC = 120

# =====================================================================
# データクラス
# =====================================================================

@dataclass
class UploadResult:
    media_id: str           # X の media_id_string
    image_bytes: bytes      # 生成した画像のバイナリ（デバッグ・保存用）
    model_used: str         # 実際に使用した HF モデル名
    size_bytes: int         # アップロードしたファイルサイズ


# =====================================================================
# ユーティリティ
# =====================================================================

def _compress_image(image_bytes: bytes, max_bytes: int = MAX_IMAGE_BYTES) -> bytes:
    """
    画像が max_bytes を超える場合に JPEG 変換＋品質低下で圧縮する。
    PNG → JPEG に変換することで通常 50〜80% のサイズ削減が可能。
    """
    if len(image_bytes) <= max_bytes:
        return image_bytes

    logger.warning(
        "Image too large (%d bytes > %d). Compressing...",
        len(image_bytes), max_bytes
    )
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    for quality in [85, 70, 55, 40]:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        compressed = buf.getvalue()
        if len(compressed) <= max_bytes:
            logger.info(
                "Compressed to %d bytes at quality=%d", len(compressed), quality
            )
            return compressed

    raise RuntimeError(
        f"Cannot compress image below {max_bytes} bytes even at quality=40."
    )


def _build_hf_headers(hf_token: str) -> dict:
    return {
        "Authorization": f"Bearer {hf_token}",
        "Content-Type": "application/json",
        "Accept": "image/png",
    }


# =====================================================================
# HuggingFace 画像生成
# =====================================================================

def _call_hf_model(
    model_id: str,
    prompt: str,
    hf_token: str,
    timeout: int = 60,
) -> bytes:
    """
    指定モデルで画像を生成してバイナリを返す。

    Raises
    ------
    ModelLoadingError : モデルがロード中（estimated_time 付きで再試行可能）
    requests.HTTPError: その他のHTTPエラー
    """
    url = f"{HF_ROUTER_BASE}/{model_id}"
    payload = {
        "inputs": prompt,
        "parameters": {
            "num_inference_steps": 4,    # FLUX.1-schnell は4ステップ推奨
            "guidance_scale": 0.0,       # schnell は CFG不要（0.0）
        }
    }
    logger.info("Calling HF model: %s", model_id)
    resp = requests.post(
        url,
        headers=_build_hf_headers(hf_token),
        json=payload,
        timeout=timeout,
    )

    if resp.status_code == 503:
        # モデルロード中の場合
        try:
            data = resp.json()
            wait_sec = float(data.get("estimated_time", 20))
        except Exception:
            wait_sec = 20.0
        raise _ModelLoadingError(model_id=model_id, wait_sec=wait_sec)

    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    if "image" not in content_type and len(resp.content) < 1000:
        # 画像でなくエラーJSONが返ってきた場合
        raise ValueError(
            f"HF model {model_id} returned non-image response: {resp.text[:200]}"
        )

    logger.info(
        "HF image generated: %d bytes (model=%s)", len(resp.content), model_id
    )
    return resp.content


class _ModelLoadingError(Exception):
    def __init__(self, model_id: str, wait_sec: float):
        self.model_id = model_id
        self.wait_sec = min(wait_sec, MAX_LOADING_WAIT_SEC)
        super().__init__(f"Model {model_id} is loading. Retry in {self.wait_sec:.0f}s.")


def _generate_with_fallback(
    prompt: str,
    hf_token: str,
    model_candidates: list[str] = HF_MODEL_CANDIDATES,
) -> tuple[bytes, str]:
    """
    モデルを順番に試し、最初に成功したものの (image_bytes, model_id) を返す。
    各モデルでロード中なら最大 MAX_LOADING_WAIT_SEC 秒待機してリトライする。
    """
    last_error: Optional[Exception] = None

    for model_id in model_candidates:
        # 1モデルに対して最大2回（ロード待機を含む）試行
        for attempt in range(2):
            try:
                image_bytes = _call_hf_model(model_id, prompt, hf_token)
                return image_bytes, model_id

            except _ModelLoadingError as e:
                if attempt == 0:
                    logger.info(
                        "Model loading (%s). Waiting %.0f sec...",
                        model_id, e.wait_sec,
                    )
                    time.sleep(e.wait_sec)
                else:
                    logger.warning("Model still loading after wait: %s", model_id)
                    last_error = e
                    break  # 次のモデルへ

            except requests.HTTPError as e:
                logger.warning(
                    "HTTP error from model %s (status=%s): %s",
                    model_id, e.response.status_code if e.response else "?", e,
                )
                last_error = e
                break  # 次のモデルへ

            except Exception as e:
                logger.warning("Error from model %s: %s", model_id, e)
                last_error = e
                break  # 次のモデルへ

    raise RuntimeError(
        f"All HF models failed. Last error: {last_error}"
    )


def _generate_placeholder_image(keyword: str = "trending") -> bytes:
    """
    HF API が完全に使えない場合の最終フォールバック。
    Pillow でシンプルなグラデーション画像を生成して返す。
    テスト環境や API 障害時のみ使用。
    """
    logger.warning("Using placeholder image (HF API unavailable).")
    img = Image.new("RGB", (1024, 1024))
    pixels = img.load()
    for y in range(1024):
        for x in range(1024):
            r = int((x / 1024) * 180 + 50)
            g = int((y / 1024) * 100 + 80)
            b = 200
            pixels[x, y] = (r, g, b)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_image(
    prompt: str,
    hf_token: Optional[str] = None,
    use_placeholder_on_failure: bool = False,
) -> tuple[bytes, str]:
    """
    Hugging Face で画像を生成して (image_bytes, model_id) を返す。

    Parameters
    ----------
    prompt                    : Stable Diffusion 向け英語プロンプト
    hf_token                  : HF アクセストークン（省略時は HF_API_TOKEN 環境変数）
    use_placeholder_on_failure: Trueのとき HF失敗時にプレースホルダ画像を使用

    Returns
    -------
    (image_bytes: bytes, model_used: str)
    """
    token = hf_token or os.environ.get("HF_API_TOKEN")
    if not token:
        raise EnvironmentError("HF_API_TOKEN が設定されていません。")

    try:
        raw_bytes, model_id = _generate_with_fallback(prompt, token)
        # X の 5MB 制限に合わせて必要なら圧縮
        final_bytes = _compress_image(raw_bytes)
        return final_bytes, model_id

    except Exception as e:
        if use_placeholder_on_failure:
            logger.error("HF generation failed (%s). Using placeholder.", e)
            placeholder = _generate_placeholder_image()
            return placeholder, "placeholder"
        raise


# =====================================================================
# X API v1.1 メディアアップロード
# =====================================================================

def _build_tweepy_v1_api(
    api_key: str,
    api_secret: str,
    access_token: str,
    access_token_secret: str,
) -> tweepy.API:
    """OAuth 1.0a 認証済みの tweepy.API (v1) インスタンスを返す。"""
    auth = tweepy.OAuth1UserHandler(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
    )
    return tweepy.API(auth, wait_on_rate_limit=True)


@retry(
    retry=retry_if_exception_type(tweepy.errors.TweepyException),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=5, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def _upload_media(
    v1_api: tweepy.API,
    image_bytes: bytes,
    filename: str = "image.png",
) -> str:
    """
    X API v1.1 の media/upload に画像をアップロードし media_id_string を返す。
    tweepy の TweepyException はリトライ対象。
    """
    file_obj = io.BytesIO(image_bytes)
    # Python 3.13+ で imghdr が削除されても mimetypes でファイル名から判定できるよう
    # 拡張子付きファイル名を使用
    media = v1_api.media_upload(filename=filename, file=file_obj)
    media_id = media.media_id_string
    logger.info("Media uploaded to X: media_id=%s", media_id)
    return media_id


def upload_image_to_x(
    image_bytes: bytes,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    access_token: Optional[str] = None,
    access_token_secret: Optional[str] = None,
) -> str:
    """
    画像バイナリを X API v1.1 でアップロードし media_id_string を返す。

    認証情報は引数 > 環境変数 の優先順で取得する。
    """
    creds = {
        "api_key":              api_key              or os.environ.get("X_API_KEY", ""),
        "api_secret":           api_secret           or os.environ.get("X_API_SECRET", ""),
        "access_token":         access_token         or os.environ.get("X_ACCESS_TOKEN", ""),
        "access_token_secret":  access_token_secret  or os.environ.get("X_ACCESS_TOKEN_SECRET", ""),
    }

    missing = [k for k, v in creds.items() if not v]
    if missing:
        raise EnvironmentError(
            f"X 認証情報が不足しています: {missing}\n"
            ".env または環境変数で設定してください。"
        )

    v1_api = _build_tweepy_v1_api(**creds)
    return _upload_media(v1_api, image_bytes)


# =====================================================================
# 統合公開関数
# =====================================================================

def generate_and_upload(
    prompt: str,
    hf_token: Optional[str] = None,
    x_api_key: Optional[str] = None,
    x_api_secret: Optional[str] = None,
    x_access_token: Optional[str] = None,
    x_access_token_secret: Optional[str] = None,
    use_placeholder_on_failure: bool = False,
) -> UploadResult:
    """
    画像を生成し X にアップロードするまでの一連の流れを実行する。

    Parameters
    ----------
    prompt                    : HF に渡す英語プロンプト
    hf_token                  : HuggingFace アクセストークン
    x_*                       : X API 認証情報（省略時は環境変数から取得）
    use_placeholder_on_failure: HF失敗時にプレースホルダ画像で続行するか

    Returns
    -------
    UploadResult (media_id, image_bytes, model_used, size_bytes)
    """
    # Step 1: 画像生成
    image_bytes, model_used = generate_image(
        prompt=prompt,
        hf_token=hf_token,
        use_placeholder_on_failure=use_placeholder_on_failure,
    )

    # Step 2: X にアップロード
    media_id = upload_image_to_x(
        image_bytes=image_bytes,
        api_key=x_api_key,
        api_secret=x_api_secret,
        access_token=x_access_token,
        access_token_secret=x_access_token_secret,
    )

    return UploadResult(
        media_id=media_id,
        image_bytes=image_bytes,
        model_used=model_used,
        size_bytes=len(image_bytes),
    )
