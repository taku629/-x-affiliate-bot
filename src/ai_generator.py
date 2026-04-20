"""
ai_generator.py
---------------
Google Gemini API を使って、トレンドワードから X投稿コンテンツを生成する。

無料枠: gemini-1.5-flash — 15 RPM / 1,500 RPD / 1M TPM
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# X 文字数制限
X_MAX_CHARS     = 140
X_URL_COST      = 23   # t.co 短縮URL 固定コスト
X_NEWLINE_COST  = 1
POST_BODY_LIMIT = X_MAX_CHARS - X_URL_COST - X_NEWLINE_COST  # = 116


@dataclass
class GeneratedContent:
    post_text: str
    image_prompt: str
    hashtags: list[str]
    affiliate_category: str
    raw_json: dict = field(default_factory=dict)

    @property
    def post_char_count(self) -> int:
        return len(self.post_text)

    def is_within_limit(self) -> bool:
        return self.post_char_count <= POST_BODY_LIMIT
