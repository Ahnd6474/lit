from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


SIZE = 1024
OUTPUT = Path(__file__).with_name("App_icon.png")


def cubic_points(p0, p1, p2, p3, steps: int = 56) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for index in range(steps + 1):
        t = index / steps
        mt = 1.0 - t
        x = (
            (mt ** 3) * p0[0]
            + 3 * (mt ** 2) * t * p1[0]
            + 3 * mt * (t ** 2) * p2[0]
            + (t ** 3) * p3[0]
        )
        y = (
            (mt ** 3) * p0[1]
            + 3 * (mt ** 2) * t * p1[1]
            + 3 * mt * (t ** 2) * p2[1]
            + (t ** 3) * p3[1]
        )
        points.append((x, y))
    return points


def ribbon(
    top: tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]],
    bottom: tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]],
) -> list[tuple[int, int]]:
    upper = cubic_points(*top)
    lower = cubic_points(*bottom)
    points = upper + list(reversed(lower))
    return [(round(x), round(y)) for x, y in points]


def gradient_fill(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGBA", size)
    pixels = image.load()
    height = max(size[1] - 1, 1)
    for y in range(size[1]):
        t = y / height
        color = tuple(round(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        for x in range(size[0]):
            pixels[x, y] = (*color, 255)
    return image


def add_shadow(
    canvas: Image.Image,
    shape_points: list[tuple[int, int]],
    *,
    offset: tuple[int, int] = (0, 0),
    blur: int = 24,
    color: tuple[int, int, int, int] = (0, 0, 0, 110),
) -> None:
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    shifted = [(x + offset[0], y + offset[1]) for x, y in shape_points]
    draw.polygon(shifted, fill=color)
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(layer)


def add_ellipse_glow(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    color: tuple[int, int, int, int],
    blur: int,
) -> None:
    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    draw.ellipse(box, fill=color)
    glow = glow.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(glow)


def main() -> None:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    icon_box = (160, 160, 864, 864)
    radius = 132
    base_mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(base_mask).rounded_rectangle(icon_box, radius=radius, fill=255)

    base_gradient = gradient_fill((SIZE, SIZE), (94, 106, 124), (14, 19, 28))
    base = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    base.paste(base_gradient, (0, 0), base_mask)

    highlight = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    hdraw = ImageDraw.Draw(highlight)
    hdraw.ellipse((140, 120, 720, 620), fill=(255, 255, 255, 44))
    highlight = highlight.filter(ImageFilter.GaussianBlur(70))
    highlight = Image.composite(highlight, Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0)), base_mask)
    base = Image.alpha_composite(base, highlight)

    image.alpha_composite(base)
    add_ellipse_glow(image, (210, 360, 620, 720), (255, 106, 0, 110), 44)
    add_ellipse_glow(image, (360, 330, 710, 620), (255, 193, 54, 95), 34)

    outer_flame = ribbon(
        ((205, 626), (226, 515), (335, 434), (480, 426)),
        ((478, 503), (364, 516), (265, 576), (208, 678)),
    )
    middle_flame = ribbon(
        ((240, 596), (276, 510), (366, 454), (510, 454)),
        ((496, 528), (388, 528), (305, 572), (236, 640)),
    )
    inner_flame = ribbon(
        ((302, 560), (344, 505), (418, 470), (538, 474)),
        ((523, 541), (436, 538), (360, 560), (294, 602)),
    )
    spark_flame = ribbon(
        ((310, 476), (350, 436), (404, 424), (454, 412)),
        ((450, 452), (406, 458), (354, 468), (306, 498)),
    )

    for points, color, offset, blur in (
        (outer_flame, (255, 72, 24, 210), (0, 8), 22),
        (middle_flame, (255, 129, 16, 190), (0, 6), 18),
        (inner_flame, (255, 194, 44, 175), (0, 4), 14),
    ):
        add_shadow(image, points, offset=offset, blur=blur, color=color)

    flames = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(flames)
    fdraw.polygon(outer_flame, fill=(255, 74, 18, 255))
    fdraw.polygon(middle_flame, fill=(255, 128, 15, 255))
    fdraw.polygon(inner_flame, fill=(255, 193, 43, 255))
    fdraw.polygon(spark_flame, fill=(255, 197, 58, 255))
    image.alpha_composite(flames)

    mane = [
        (380, 600),
        (414, 520),
        (462, 444),
        (480, 380),
        (523, 302),
        (560, 332),
        (594, 294),
        (584, 380),
        (654, 402),
        (742, 456),
        (724, 510),
        (674, 550),
        (621, 574),
        (590, 636),
        (482, 646),
    ]
    muzzle = [
        (514, 496),
        (592, 476),
        (664, 478),
        (742, 500),
        (699, 532),
        (639, 545),
        (580, 548),
        (522, 537),
        (500, 516),
    ]
    chest = [
        (485, 510),
        (524, 536),
        (550, 598),
        (594, 630),
        (528, 640),
        (476, 620),
        (452, 572),
    ]
    left_ear = [(506, 318), (548, 250), (590, 334), (552, 350)]
    right_ear = [(596, 346), (670, 292), (652, 380), (596, 366)]
    jaw_shadow = [(612, 540), (681, 520), (732, 508), (700, 534), (644, 548)]
    mane_cut = [(454, 460), (486, 388), (510, 350), (530, 404), (516, 470), (486, 530)]

    for points, offset, blur, color in (
        (mane, (0, 12), 24, (0, 0, 0, 140)),
        (muzzle, (0, 6), 12, (0, 0, 0, 80)),
        (chest, (0, 4), 10, (0, 0, 0, 60)),
    ):
        add_shadow(image, points, offset=offset, blur=blur, color=color)

    wolf = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    wdraw = ImageDraw.Draw(wolf)
    wdraw.polygon(mane, fill=(11, 16, 24, 255))
    wdraw.polygon(left_ear, fill=(11, 16, 24, 255))
    wdraw.polygon(right_ear, fill=(11, 16, 24, 255))
    wdraw.polygon(mane_cut, fill=(42, 50, 64, 220))
    wdraw.polygon(chest, fill=(255, 179, 18, 255))
    wdraw.polygon(muzzle, fill=(245, 245, 246, 255))
    wdraw.polygon(jaw_shadow, fill=(226, 225, 226, 255))
    wdraw.ellipse((688, 506, 702, 520), fill=(16, 16, 18, 255))
    wdraw.polygon([(566, 438), (606, 430), (636, 441), (604, 446)], fill=(235, 235, 236, 255))
    wdraw.polygon([(570, 443), (603, 438), (617, 445), (585, 447)], fill=(18, 22, 31, 255))
    wdraw.line([(542, 330), (530, 366), (537, 402)], fill=(246, 246, 247, 255), width=10)
    wdraw.line([(520, 525), (480, 546), (446, 570)], fill=(255, 210, 80, 220), width=20)
    image.alpha_composite(wolf)

    add_ellipse_glow(image, (470, 488, 610, 642), (255, 179, 18, 65), 26)

    title_shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(title_shadow)
    jakal_font = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 94)
    lit_font = ImageFont.truetype(r"C:\Windows\Fonts\bahnschrift.ttf", 98)

    text_y = 730
    left_margin = 260
    jakal_text = "JAKAL"
    lit_text = "Lit"

    jakal_width = sdraw.textbbox((0, 0), jakal_text, font=jakal_font)[2]
    lit_width = sdraw.textbbox((0, 0), lit_text, font=lit_font)[2]
    gap = 22
    total_width = jakal_width + gap + lit_width
    start_x = round((SIZE - total_width) / 2)
    lit_x = start_x + jakal_width + gap

    sdraw.text((start_x + 2, text_y + 6), jakal_text, font=jakal_font, fill=(0, 0, 0, 110))
    sdraw.text((lit_x + 2, text_y + 6), lit_text, font=lit_font, fill=(0, 0, 0, 110))
    title_shadow = title_shadow.filter(ImageFilter.GaussianBlur(8))
    image.alpha_composite(title_shadow)

    tdraw = ImageDraw.Draw(image)
    tdraw.text((start_x, text_y), jakal_text, font=jakal_font, fill=(250, 247, 242, 255))
    tdraw.text((lit_x, text_y), lit_text, font=lit_font, fill=(255, 120, 10, 255))
    tdraw.line(
        [(lit_x, text_y + 86), (lit_x + lit_width - 6, text_y + 86)],
        fill=(255, 158, 44, 215),
        width=7,
    )

    final_image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    final_image.paste(image, (0, 0), base_mask)
    final_image.save(OUTPUT, format="PNG")


if __name__ == "__main__":
    main()
