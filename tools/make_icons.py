"""生成 PWA 图标（仅开发时使用）。

用法：
    python tools/make_icons.py > icons.json
再由 PowerShell/CI 解码为 PNG。这里输出 JSON 到 stdout，避免依赖本地写文件权限。
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024
BG = "#0b1220"
COLORS = ["#ff8b66", "#6fd3df", "#f4c95d", "#b8a1e6"]


def make_icon() -> Image.Image:
    image = Image.new("RGB", (SIZE, SIZE), BG)
    draw = ImageDraw.Draw(image)

    # 很淡的网格，增加质感但不影响小尺寸识别。
    grid = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    grid_draw = ImageDraw.Draw(grid)
    for position in range(0, SIZE, 96):
        grid_draw.line((position, 0, position, SIZE), fill=(255, 255, 255, 10), width=2)
        grid_draw.line((0, position, SIZE, position), fill=(255, 255, 255, 10), width=2)
    image = Image.alpha_composite(image.convert("RGBA"), grid).convert("RGB")
    draw = ImageDraw.Draw(image)

    # 底部基线
    draw.rounded_rectangle((190, 792, 834, 804), radius=6, fill=(255, 255, 255, 38))

    bar_width = 76
    gap = 44
    start_x = 222
    baseline = 780
    heights = [188, 326, 258, 392]

    for index, (color, height) in enumerate(zip(COLORS, heights)):
        x = start_x + index * (bar_width + gap)
        top = baseline - height
        draw.rounded_rectangle(
            (x, top, x + bar_width, baseline),
            radius=bar_width // 2,
            fill=color,
        )

    return image


def encode(image: Image.Image, size: int) -> str:
    resized = image.resize((size, size), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    resized.save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def main() -> None:
    image = make_icon()
    result = {
        "icon-192.png": encode(image, 192),
        "icon-512.png": encode(image, 512),
        "apple-touch-icon.png": encode(image, 180),
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
