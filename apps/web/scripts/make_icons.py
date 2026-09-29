"""Genera los íconos de la PWA (192, 512, maskable, apple-touch). Uso:

    uv run --with pillow python scripts/make_icons.py

Es un ícono provisional (marca «UNO» sobre azul) hasta que Novamed entregue su identidad (Q12).
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "public" / "icons"
OUT.mkdir(parents=True, exist_ok=True)
BLUE = (22, 104, 240, 255)
WHITE = (255, 255, 255, 255)
FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def draw_icon(size: int, *, maskable: bool, rounded: bool) -> Image.Image:
    scale = 4  # dibuja al cuádruple y reduce (bordes suaves)
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if maskable:
        d.rectangle([0, 0, s, s], fill=BLUE)  # el sistema recorta la forma
        text_h = int(s * 0.26)  # dentro de la zona segura (80 %)
    else:
        radius = int(s * 0.22) if rounded else 0
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=BLUE)
        text_h = int(s * 0.32)
    f = font(text_h)
    bbox = d.textbbox((0, 0), "UNO", font=f)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((s - w) / 2 - bbox[0], (s - h) / 2 - bbox[1] - s * 0.02), "UNO", font=f, fill=WHITE)
    # punto de acento (una «visita») bajo el texto
    r = int(s * 0.035)
    cx, cy = s // 2, int(s * (0.70 if not maskable else 0.68))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE)
    return img.resize((size, size), Image.LANCZOS)


for name, size, maskable, rounded in [
    ("icon-192.png", 192, False, True),
    ("icon-512.png", 512, False, True),
    ("icon-maskable-512.png", 512, True, False),
    ("apple-touch-icon.png", 180, False, False),  # iOS aplica su propio redondeo
    ("badge-72.png", 72, False, True),
]:
    draw_icon(size, maskable=maskable, rounded=rounded).save(OUT / name)
    print("ok", name)
