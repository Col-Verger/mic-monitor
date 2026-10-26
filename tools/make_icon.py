# -*- coding: utf-8 -*-
"""Генерация иконки MicMonitor: mic.ico + docs/icon.png (запускать при смене дизайна)."""

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024
ROOT = Path(__file__).resolve().parents[1]

BG = (18, 20, 26, 255)
BORDER = (46, 54, 70, 255)
FG = (233, 238, 247, 255)
DIM = (124, 133, 152, 255)
ACCENT = (61, 220, 132, 255)


def build() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    radius = int(SIZE * 0.22)
    d.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=radius, fill=BG)
    d.rounded_rectangle([9, 9, SIZE - 10, SIZE - 10], radius=radius - 5,
                        outline=BORDER, width=12)

    cx = SIZE / 2
    body_w, body_h, body_top = SIZE * 0.28, SIZE * 0.43, SIZE * 0.15

    # капсула микрофона
    d.rounded_rectangle(
        [cx - body_w / 2, body_top, cx + body_w / 2, body_top + body_h],
        radius=body_w / 2, fill=FG,
    )
    # решётка
    for i in range(1, 6):
        y = body_top + body_h * i / 6
        d.line([cx - body_w * 0.27, y, cx + body_w * 0.27, y],
               fill=DIM, width=int(SIZE * 0.011))

    # скоба-держатель
    arc_r = SIZE * 0.205
    drop = body_top + body_h * 0.72
    d.arc([cx - arc_r, drop, cx + arc_r, drop + arc_r * 1.05],
          start=0, end=180, fill=FG, width=int(SIZE * 0.052))

    # ножка и основание
    stem_top = drop + arc_r * 0.92
    d.rounded_rectangle([cx - SIZE * 0.026, stem_top, cx + SIZE * 0.026, SIZE * 0.795],
                        radius=SIZE * 0.026, fill=FG)
    d.rounded_rectangle([cx - SIZE * 0.15, SIZE * 0.78, cx + SIZE * 0.15, SIZE * 0.84],
                        radius=SIZE * 0.03, fill=FG)

    # зелёная точка записи
    d.ellipse([SIZE * 0.735, SIZE * 0.175, SIZE * 0.875, SIZE * 0.315], fill=ACCENT)

    return img


def main() -> None:
    img = build()
    ROOT.joinpath("mic.ico").write_bytes(b"")
    img.save(ROOT / "mic.ico", format="ICO",
             sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)])
    (ROOT / "docs").mkdir(exist_ok=True)
    img.resize((512, 512), Image.LANCZOS).save(ROOT / "docs" / "icon.png")
    img.resize((256, 256), Image.LANCZOS).save(ROOT / "docs" / "icon_256.png")
    print("готово:", ROOT / "mic.ico", ROOT / "docs" / "icon.png")


if __name__ == "__main__":
    main()
