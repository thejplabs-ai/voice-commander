"""
Gera build/icon.ico com ícone de microfone nas cores JP Labs.
Uso: python build/create_icon.py
"""
import math
from PIL import Image, ImageDraw

JP_PURPLE = (107, 47, 248)   # #6B2FF8
JP_BLUE   = (30, 56, 247)    # #1E38F7
BG        = (1, 1, 13)       # #01010D


def make_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size

    # --- Fundo: círculo com gradiente roxo→azul simulado ---
    # Usar cor sólida intermediária para compatibilidade
    mid = tuple((a + b) // 2 for a, b in zip(JP_PURPLE, JP_BLUE))
    margin = max(1, s // 16)
    d.ellipse([margin, margin, s - margin, s - margin], fill=(*mid, 255))

    # Highlight sutil no topo (simula gradiente)
    hi_r = s // 3
    hi_x = s // 2
    hi_y = s // 3
    d.ellipse(
        [hi_x - hi_r, hi_y - hi_r, hi_x + hi_r, hi_y + hi_r // 2],
        fill=(*JP_PURPLE, 120),
    )

    # --- Microfone ---
    cx = s // 2
    # Corpo do mic: retângulo arredondado
    mic_w  = max(4, s // 5)
    mic_h  = max(6, s * 2 // 5)
    mic_x0 = cx - mic_w // 2
    mic_y0 = s // 8
    mic_x1 = cx + mic_w // 2
    mic_y1 = mic_y0 + mic_h
    r_mic  = mic_w // 2
    d.rounded_rectangle([mic_x0, mic_y0, mic_x1, mic_y1], radius=r_mic, fill="white")

    # Arco (suporte do mic)
    arc_r  = max(4, s // 4)
    arc_x0 = cx - arc_r
    arc_y0 = mic_y1 - mic_h // 3
    arc_x1 = cx + arc_r
    arc_y1 = arc_y0 + arc_r * 2
    lw = max(2, s // 22)
    d.arc([arc_x0, arc_y0, arc_x1, arc_y1], start=0, end=180, fill="white", width=lw)

    # Haste vertical + base
    stem_y0 = arc_y0 + arc_r
    stem_y1 = stem_y0 + max(3, s // 9)
    d.line([(cx, stem_y0), (cx, stem_y1)], fill="white", width=lw)
    base_w = max(4, s // 4)
    d.line(
        [(cx - base_w // 2, stem_y1), (cx + base_w // 2, stem_y1)],
        fill="white", width=lw,
    )

    return img


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]

    # Gerar cada tamanho individualmente e salvar como ICO multi-resolução
    # Pillow ICO: salvar a maior imagem com lista de sizes para auto-resize
    img_256 = make_icon(256)
    out = "build/icon.ico"
    img_256.save(
        out,
        format="ICO",
        sizes=[(sz, sz) for sz in sizes],
    )
    print(f"Gerado: {out}  ({len(sizes)} tamanhos: {sizes})")


if __name__ == "__main__":
    main()
