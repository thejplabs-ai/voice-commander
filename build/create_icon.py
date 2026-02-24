"""
Gera build/icon.ico com ícone de microfone nas cores JP Labs.
Design: fundo roxo sólido + microfone branco grosso — legível em 16x16.
Uso: python build/create_icon.py
"""
from PIL import Image, ImageDraw

JP_PURPLE = (107, 47, 248)  # #6B2FF8


def make_icon(size: int) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Fundo: quadrado arredondado roxo sólido (sem transparência)
    radius = max(3, s // 6)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=(*JP_PURPLE, 255))

    # Escala: tudo relativo ao tamanho
    cx = s // 2

    # Corpo do microfone (retângulo arredondado branco, mais largo e visível)
    mic_w  = max(3, s * 3 // 10)
    mic_h  = max(4, s * 9 // 20)
    mic_x0 = cx - mic_w // 2
    mic_y0 = max(2, s // 10)
    mic_x1 = cx + mic_w // 2
    mic_y1 = mic_y0 + mic_h
    mic_r  = mic_w // 2
    d.rounded_rectangle([mic_x0, mic_y0, mic_x1, mic_y1], radius=mic_r, fill="white")

    # Arco inferior (headset)
    lw     = max(2, s // 14)
    arc_r  = max(3, s * 3 // 10)
    arc_cx = cx
    arc_cy = mic_y1 - mic_h // 4
    d.arc(
        [arc_cx - arc_r, arc_cy, arc_cx + arc_r, arc_cy + arc_r * 2],
        start=0, end=180, fill="white", width=lw,
    )

    # Haste
    stem_top = arc_cy + arc_r
    stem_bot = stem_top + max(2, s // 9)
    d.line([(cx, stem_top), (cx, stem_bot)], fill="white", width=lw)

    # Base horizontal
    base_w = max(3, s // 4)
    d.line(
        [(cx - base_w // 2, stem_bot), (cx + base_w // 2, stem_bot)],
        fill="white", width=lw,
    )

    return img


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    img_256 = make_icon(256)
    out = "build/icon.ico"
    img_256.save(out, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"Gerado: {out}  ({len(sizes)} tamanhos: {sizes})")

    # Preview rápido dos tamanhos críticos
    for sz in [16, 32, 48]:
        preview = make_icon(sz)
        preview.save(f"build/icon_preview_{sz}.png")
        print(f"Preview: build/icon_preview_{sz}.png")


if __name__ == "__main__":
    main()
