"""
STEP 4 動作確認スクリプト

TEST 1: 圧縮ロジック（Pillow のみ・APIキー不要）
TEST 2: プレースホルダ画像生成（APIキー不要）
TEST 3: HF API モック → X アップロード モック（APIキー不要）
TEST 4: HF API 実呼び出し（HF_API_TOKEN がある場合のみ）
TEST 5: X メディアアップロード実呼び出し（X API 認証情報がある場合のみ）
"""

import io
import logging
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

from PIL import Image
from image_generator import (
    _compress_image,
    _generate_placeholder_image,
    _build_tweepy_v1_api,
    generate_image,
    upload_image_to_x,
    generate_and_upload,
    HF_MODEL_CANDIDATES,
    MAX_IMAGE_BYTES,
    TARGET_SIZE,
)

print("=" * 60)
print("STEP 4 テスト: 画像生成 & X メディアアップロード")
print("=" * 60)

# =====================================================================
# TEST 1: 圧縮ロジック
# =====================================================================
print("\n[TEST 1] 画像圧縮ロジック")

def _make_test_png(size=(1024, 1024), color=(100, 150, 200)) -> bytes:
    """テスト用ダミーPNG画像を生成"""
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

# 5MB超えのダミー画像でテスト
large_png = _make_test_png((2048, 2048))
print(f"  入力サイズ     : {len(large_png):,} bytes ({len(large_png)/1024/1024:.2f} MB)")

compressed = _compress_image(large_png, max_bytes=MAX_IMAGE_BYTES)
print(f"  圧縮後サイズ   : {len(compressed):,} bytes ({len(compressed)/1024/1024:.2f} MB)")
print(f"  制限以内か     : {len(compressed) <= MAX_IMAGE_BYTES}")

# すでに小さい画像は変更されないことを確認
small_png = _make_test_png((64, 64))
unchanged = _compress_image(small_png)
print(f"  小画像は非圧縮 : {small_png == unchanged}")

# =====================================================================
# TEST 2: プレースホルダ画像生成
# =====================================================================
print("\n[TEST 2] プレースホルダ画像生成（HF APIなし）")

placeholder = _generate_placeholder_image("テストトレンド")
img = Image.open(io.BytesIO(placeholder))
print(f"  サイズ   : {img.size}")
print(f"  モード   : {img.mode}")
print(f"  バイト数 : {len(placeholder):,} bytes")

# ファイルとして保存してフォーマット確認
assert img.size == (1024, 1024), "プレースホルダは 1024x1024 であるべき"
print("  [OK] プレースホルダ画像生成成功")

# =====================================================================
# TEST 3: モックでフル生成→アップロードフロー確認
# =====================================================================
print("\n[TEST 3] モックによる generate_and_upload フロー確認")

MOCK_PROMPT = (
    "Photorealistic 8k image of a Japanese male long distance runner "
    "competing on an athletics track, vibrant colors, high quality"
)
MOCK_IMAGE_BYTES = _make_test_png((512, 512), color=(80, 120, 200))
MOCK_MEDIA_ID = "1234567890123456789"

# HF API レスポンスをモック
mock_hf_response = MagicMock()
mock_hf_response.status_code = 200
mock_hf_response.content = MOCK_IMAGE_BYTES
mock_hf_response.headers = {"Content-Type": "image/png"}
mock_hf_response.raise_for_status = MagicMock()

# tweepy メディアアップロードをモック
mock_media = MagicMock()
mock_media.media_id_string = MOCK_MEDIA_ID
mock_v1_api = MagicMock()
mock_v1_api.media_upload.return_value = mock_media

with patch("image_generator.requests.post", return_value=mock_hf_response), \
     patch("image_generator._build_tweepy_v1_api", return_value=mock_v1_api), \
     patch.dict(os.environ, {
         "HF_API_TOKEN":           "mock_hf_token",
         "X_API_KEY":              "mock_key",
         "X_API_SECRET":           "mock_secret",
         "X_ACCESS_TOKEN":         "mock_access_token",
         "X_ACCESS_TOKEN_SECRET":  "mock_access_secret",
     }):
    result = generate_and_upload(prompt=MOCK_PROMPT)

print(f"  media_id   : {result.media_id}")
print(f"  model_used : {result.model_used}")
print(f"  size_bytes : {result.size_bytes:,}")
assert result.media_id == MOCK_MEDIA_ID, "media_id が一致しない"
assert result.model_used == HF_MODEL_CANDIDATES[0], "第1候補モデルが使われるべき"
print("  [OK] モックフロー成功")

# =====================================================================
# TEST 3b: HF 503 → モデルロード待機 → 成功フロー
# =====================================================================
print("\n[TEST 3b] HF 503 (モデルロード中) → 成功フロー確認")

mock_503 = MagicMock()
mock_503.status_code = 503
mock_503.json.return_value = {"error": "Model is loading", "estimated_time": 0.01}

call_count = {"n": 0}
def side_effect_503_then_ok(*args, **kwargs):
    call_count["n"] += 1
    if call_count["n"] == 1:
        return mock_503
    return mock_hf_response

with patch("image_generator.requests.post", side_effect=side_effect_503_then_ok), \
     patch("image_generator._build_tweepy_v1_api", return_value=mock_v1_api), \
     patch.dict(os.environ, {
         "HF_API_TOKEN": "mock_hf_token",
         "X_API_KEY": "mock_key", "X_API_SECRET": "mock_secret",
         "X_ACCESS_TOKEN": "mock_token", "X_ACCESS_TOKEN_SECRET": "mock_secret2",
     }):
    result_503 = generate_and_upload(prompt=MOCK_PROMPT)

print(f"  API呼び出し回数 : {call_count['n']}回（1回目は503、2回目は成功）")
print(f"  media_id        : {result_503.media_id}")
assert call_count["n"] == 2, "503後に1回リトライされるべき"
print("  [OK] 503リトライフロー成功")

# =====================================================================
# TEST 3c: 全モデル失敗 → プレースホルダフォールバック
# =====================================================================
print("\n[TEST 3c] 全モデル失敗 → プレースホルダフォールバック確認")

mock_error = MagicMock()
mock_error.status_code = 500
mock_error.raise_for_status.side_effect = Exception("500 Server Error")

with patch("image_generator.requests.post", side_effect=Exception("Connection error")), \
     patch("image_generator._build_tweepy_v1_api", return_value=mock_v1_api), \
     patch.dict(os.environ, {
         "HF_API_TOKEN": "mock_hf_token",
         "X_API_KEY": "mock_key", "X_API_SECRET": "mock_secret",
         "X_ACCESS_TOKEN": "mock_token", "X_ACCESS_TOKEN_SECRET": "mock_secret2",
     }):
    result_ph = generate_and_upload(
        prompt=MOCK_PROMPT,
        use_placeholder_on_failure=True,
    )

print(f"  model_used : {result_ph.model_used}")
print(f"  size_bytes : {result_ph.size_bytes:,}")
assert result_ph.model_used == "placeholder"
print("  [OK] プレースホルダフォールバック成功")

# =====================================================================
# TEST 4: HF API 実呼び出し（HF_API_TOKEN がある場合のみ）
# =====================================================================
print("\n[TEST 4] HF API 実呼び出し")
hf_token = os.environ.get("HF_API_TOKEN")

if not hf_token:
    print("  HF_API_TOKEN が未設定のためスキップ。")
    print("  実行方法: HF_API_TOKEN=hf_xxxx python test_step4.py")
else:
    print(f"  HFトークン検出: {hf_token[:8]}...")
    try:
        image_bytes, model_id = generate_image(
            prompt="A photorealistic 8k image of Mount Fuji at sunrise, vibrant colors",
            hf_token=hf_token,
            use_placeholder_on_failure=False,
        )
        img = Image.open(io.BytesIO(image_bytes))
        print(f"  モデル         : {model_id}")
        print(f"  画像サイズ     : {img.size}")
        print(f"  バイト数       : {len(image_bytes):,} bytes")
        # 保存して目視確認できるようにする
        out_path = "/tmp/test_hf_output.png"
        with open(out_path, "wb") as f:
            f.write(image_bytes)
        print(f"  保存先         : {out_path}")
        print("  [OK] HF API 実呼び出し成功")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")

# =====================================================================
# TEST 5: X メディアアップロード実呼び出し（X API 認証情報がある場合のみ）
# =====================================================================
print("\n[TEST 5] X メディアアップロード実呼び出し")
has_x_creds = all([
    os.environ.get("X_API_KEY"),
    os.environ.get("X_API_SECRET"),
    os.environ.get("X_ACCESS_TOKEN"),
    os.environ.get("X_ACCESS_TOKEN_SECRET"),
])

if not has_x_creds:
    print("  X API 認証情報が未設定のためスキップ。")
    print("  実行方法: X_API_KEY=... X_API_SECRET=... python test_step4.py")
else:
    print("  X 認証情報検出。アップロードを試みます...")
    try:
        test_image = _make_test_png((256, 256), color=(255, 100, 50))
        media_id = upload_image_to_x(test_image)
        print(f"  media_id : {media_id}")
        print("  [OK] X メディアアップロード成功")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")

print("\n[OK] STEP 4 テスト完了")
