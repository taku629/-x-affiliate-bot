"""HuggingFace Inference API で画像を生成し、X v1.1 API にアップロードする。

モデルのフォールバック順:
  1. black-forest-labs/FLUX.1-schnell
  2. stabilityai/stable-diffusion-xl-base-1.0
  3. stabilityai/stable-diffusion-2-1
"""

import io
import os
import time
import requests
import tweepy

_HF_API_BASE = "https://api-inference.huggingface.co/models"

_MODELS = [
    "black-forest-labs/FLUX.1-schnell",
    "stabilityai/stable-diffusion-xl-base-1.0",
    "stabilityai/stable-diffusion-2-1",
]

_SAFE_SUFFIX = ", bright colors, cheerful, high quality, 4k"
_TIMEOUT = 60
_MAX_RETRIES = 2


def _hf_headers() -> dict:
    token = os.getenv("HF_API_TOKEN")
    if not token:
        raise ValueError("HF_API_TOKEN が設定されていません")
    return {"Authorization": f"Bearer {token}"}


def _generate_with_model(model: str, prompt: str) -> bytes:
    url = f"{_HF_API_BASE}/{model}"
    headers = _hf_headers()
    payload = {"inputs": prompt + _SAFE_SUFFIX}

    for attempt in range(_MAX_RETRIES + 1):
        resp = requests.post(url, headers=headers, json=payload, timeout=_TIMEOUT)
        if resp.status_code == 200:
            return resp.content
        if resp.status_code == 503:
            # モデルのウォームアップ待ち
            wait = resp.json().get("estimated_time", 20)
            time.sleep(min(wait, 30))
            continue
        resp.raise_for_status()

    raise RuntimeError(f"{model}: {_MAX_RETRIES + 1}回試みましたが画像生成に失敗しました")


def generate_image(prompt: str) -> bytes | None:
    """画像をバイト列で返す。全モデルが失敗した場合は None を返す。"""
    for model in _MODELS:
        try:
            return _generate_with_model(model, prompt)
        except Exception as exc:
            print(f"[image] {model} 失敗: {exc}")
    return None


def upload_to_x(image_bytes: bytes) -> str | None:
    """X v1.1 media/upload エンドポイントに画像をアップロードして media_id を返す。"""
    api_key = os.getenv("X_API_KEY")
    api_secret = os.getenv("X_API_SECRET")
    access_token = os.getenv("X_ACCESS_TOKEN")
    access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")

    if not all([api_key, api_secret, access_token, access_token_secret]):
        raise ValueError("X API 認証情報が不足しています")

    auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_token_secret)
    api_v1 = tweepy.API(auth)

    media = api_v1.media_upload(filename="image.jpg", file=io.BytesIO(image_bytes))
    return str(media.media_id)
