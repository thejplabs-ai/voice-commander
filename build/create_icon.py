"""
Gera build/icon.ico com o logo V-Wave do Voice Commander.
Design: 10 barras verticais cujos bottoms formam V, tops formam waveform.
Uso: python build/create_icon.py
"""
from PIL import Image, ImageDraw

# V-Wave bar definitions at 512x512 base (from logo.svg)
# Each tuple: (x, y, width, height)
_BARS_512 = [
    (52,  88,  30, 132),
    (94,  56,  30, 211),
    (136, 112, 30, 202),
    (178, 48,  30, 313),
    (220, 144, 30, 264),
    (262, 144, 30, 264),
    (304, 48,  30, 313),
    (346, 112, 30, 202),
    (388, 56,  30, 211),
    (430, 88,  30, 132),
]

JP_AMBER = (196, 149, 106)  # #C4956A


def make_icon(size: int, color: tuple = JP_AMBER) -> Image.Image:
    """Generate V-Wave icon at given size with given bar color."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    scale = size / 512.0
    radius = max(1, int(5 * scale))

    for (bx, by, bw, bh) in _BARS_512:
        x0 = int(bx * scale)
        y0 = int(by * scale)
        x1 = int((bx + bw) * scale)
        y1 = int((by + bh) * scale)
        if x1 - x0 < 1:
            x1 = x0 + 1
        if y1 - y0 < 1:
            y1 = y0 + 1
        d.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=(*color, 255))

    return img


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    img_256 = make_icon(256)
    out = "build/icon.ico"
    img_256.save(out, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"Gerado: {out}  ({len(sizes)} tamanhos: {sizes})")

    for sz in [16, 32, 48]:
        preview = make_icon(sz)
        preview.save(f"build/icon_preview_{sz}.png")
        print(f"Preview: build/icon_preview_{sz}.png")


if __name__ == "__main__":
    main()
