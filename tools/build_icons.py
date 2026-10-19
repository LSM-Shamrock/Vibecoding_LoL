"""스킬·소환사 주문·능력치 아이콘(PNG) 만들기.

game-icons.net (https://game-icons.net, CC BY 3.0) 의 SVG 아이콘을 골라서 게임용 PNG 로 바꿉니다.
    assets/ui/skills/<챔피언 id>_<Q|W|E|R>.png   챔피언 색 배경 + 흰 아이콘 (R 은 금색 테두리)
    assets/ui/spells/<주문 이름>.png              소환사 주문 아이콘
    assets/ui/stats/<능력치 키>.png               능력치 패널 아이콘 (배경 없는 색 아이콘)

사용법 (프로젝트 폴더에서):
    git clone --depth 1 https://github.com/game-icons/icons.git <아무 폴더>/gameicons
    pip install cairosvg pillow
    python tools/build_icons.py --src <아무 폴더>/gameicons

아이콘을 바꾸고 싶으면 아래 SKILLS / SPELLS / STATS 표에서 "작가/아이콘이름" 만 바꾸고 다시 실행하세요.
이미 만들어 둔 PNG 가 assets/ui 에 들어 있으므로, 게임을 그냥 실행하는 데는 이 스크립트가 필요 없습니다.
출처 표기는 assets/ui/CREDITS.md 를 보세요.
"""
import argparse
import io
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "ui")

# 챔피언 id -> {스킬 키: "작가/아이콘 이름"}
SKILLS = {
    "spider": {"Q": "lorc/divergence", "W": "lorc/spider-web", "E": "sbed/big-egg", "R": "@spider_leap"},
    "serpent": {"Q": "lorc/droplet-splash", "W": "lorc/bestial-fangs", "E": "lorc/earth-spit", "R": "@serpent_dive"},
    "dragon": {"Q": "lorc/fire-zone", "W": "lorc/wind-slap", "E": "lorc/bat-wing", "R": "lorc/burning-meteor"},
}

# 소환사 주문 이름 -> (아이콘, 배경 색)
SPELLS = {
    "flash": ("@flash_blink", (235, 200, 70)),
    "mark": ("lorc/frozen-orb", (110, 190, 245)),
    "heal": ("sbed/health-increase", (90, 210, 120)),
    "ghost": ("lorc/ghost", (150, 170, 230)),
    "barrier": ("lorc/bordered-shield", (225, 170, 70)),
    "cleanse": ("delapouite/holy-water", (90, 215, 220)),
    "exhaust": ("lorc/snail", (170, 120, 220)),
    "ignite": ("delapouite/fire-spell-cast", (240, 110, 70)),
}

# 능력치 키 -> (예전 game-icons 아이콘(지금은 쓰지 않음), 색). 그림은 simple_stat 이 직접 그린다
STATS = {
    "ad": ("lorc/broadsword", (255, 150, 90)),
    "ap": ("lorc/magic-swirl", (190, 135, 255)),
    "armor": ("lorc/checked-shield", (240, 205, 110)),
    "mr": ("lorc/magic-shield", (110, 200, 255)),
    "attack_speed": ("delapouite/fast-forward-button", (255, 225, 110)),
    "move_speed": ("delapouite/running-shoe", (140, 230, 150)),
    "ability_haste": ("lorc/hourglass", (130, 175, 255)),
    "crit": ("delapouite/crosshair", (255, 110, 110)),
}

GOLD = (240, 200, 90)
BIG = 256           # 이 크기로 그린 뒤 줄여서 부드럽게 만든다
TILE = 96


def mix(a, b, k):
    return tuple(int(a[i] * (1 - k) + b[i] * k) for i in range(3))


def svg_to_image(path, size, color):
    import cairosvg
    from PIL import Image
    s = open(path, encoding="utf-8").read()
    s = re.sub(r'<path d="M0 0h512v512H0z"/>', "", s, count=1)         # game-icons 의 검은 바탕 제거
    hexc = "#%02x%02x%02x" % color
    s = s.replace('fill="#fff"', f'fill="{hexc}"')
    if hexc not in s:
        s = s.replace("<path ", f'<path fill="{hexc}" ', 1)
    png = cairosvg.svg2png(bytestring=s.encode("utf-8"), output_width=size, output_height=size)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def spider_leap(src, size, color):
    """거미 여왕 R: 거미가 포물선을 그리며 뛰어올라 한 곳에 내려앉는 그림 (game-icons 의 거미 + 직접 그린 궤적·착지 표시)."""
    from PIL import Image, ImageDraw
    k = 3
    S = size * k
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = (*color, 255)
    # 도약 궤적: 점선 포물선 (왼쪽 아래 -> 꼭대기 -> 거미), 갈수록 굵어진다
    pts = []
    for i in range(0, 11):
        t = i / 10
        x = (0.07 + 0.52 * t) * S
        y = (0.88 - 2.1 * t * (1 - t) * 0.82 - 0.30 * t) * S
        pts.append((x, y))
    for i, (x, y) in enumerate(pts[:-2]):
        r = (0.020 + 0.022 * i / 10) * S
        d.ellipse((x - r, y - r, x + r, y + r), fill=c)
    # 착지 자리: 납작한 타원과 충격선
    ex, ey, ew, eh = 0.74 * S, 0.90 * S, 0.30 * S, 0.075 * S
    d.ellipse((ex - ew, ey - eh, ex + ew, ey + eh), outline=c, width=int(0.022 * S))
    for a in (-0.55, 0.0, 0.55):
        x0, x1 = ex + a * ew * 1.0, ex + a * ew * 1.35
        d.line([(x0, ey - eh * 1.4), (x1, ey - eh * 3.0)], fill=c, width=int(0.02 * S))
    spider = svg_to_image(os.path.join(src, "carl-olsen/spider-alt.svg"), int(S * 0.60), color)
    spider = spider.rotate(52, resample=Image.BICUBIC, expand=True)
    im.alpha_composite(spider, (int(0.60 * S - spider.width / 2), int(0.45 * S - spider.height / 2)))
    return im.resize((size, size), Image.LANCZOS)


def serpent_dive(src, size, color):
    """이무기 R: 이무기가 물결 속으로 가라앉는 그림 (game-icons 의 바다뱀 + 직접 그린 물결·가라앉는 효과)."""
    from PIL import Image, ImageDraw
    k = 3
    S = size * k
    c = (*color, 255)
    snake = svg_to_image(os.path.join(src, "lorc/sea-serpent.svg"), int(S * 0.78), color)
    # 물 아래로 잠기는 부분은 서서히 사라지게 한다
    mask = Image.new("L", snake.size, 255)
    md = ImageDraw.Draw(mask)
    h = snake.height
    y0 = int(h * 0.55)
    for y in range(y0, h):
        md.line([(0, y), (snake.width, y)], fill=int(255 * max(0.0, 1 - (y - y0) / (h * 0.30))))
    alpha = snake.getchannel("A")
    from PIL import ImageChops
    snake.putalpha(ImageChops.multiply(alpha, mask))
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    im.alpha_composite(snake, (int(0.50 * S - snake.width / 2), int(0.02 * S)))
    d = ImageDraw.Draw(im)
    cx, cy = 0.50 * S, 0.80 * S
    for i, (w, hh) in enumerate(((0.40, 0.085), (0.30, 0.060), (0.20, 0.038))):
        d.ellipse((cx - w * S, cy - hh * S, cx + w * S, cy + hh * S), outline=c, width=int(0.024 * S))
    return im.resize((size, size), Image.LANCZOS)


def flash_blink(src, size, color):
    """점멸: 왼쪽 아래에서 오른쪽 위로 순식간에 옮겨 가는 그림 (번쩍이는 별 + 뒤에 남는 빛줄기, 전부 직접 그림)."""
    import math
    from PIL import Image, ImageDraw
    k = 3
    S = size * k
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = (*color, 255)

    def star(cx, cy, R, r, rot, fill):
        pts = []
        for i in range(8):
            a = rot + i * math.pi / 4
            rr = R if i % 2 == 0 else r
            pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
        d.polygon(pts, fill=fill)

    # 빛줄기: 떠난 자리(왼쪽 아래)에서 도착한 별 쪽으로 갈수록 굵어지는 세 줄
    ex, ey = 0.66 * S, 0.34 * S
    ang = math.atan2(ey - 0.86 * S, ex - 0.14 * S)
    ux, uy = math.cos(ang), math.sin(ang)
    nx, ny = -uy, ux
    for off, l0, l1, w in ((0.0, 0.10, 0.50, 0.050), (0.11, 0.20, 0.44, 0.030), (-0.11, 0.20, 0.44, 0.030)):
        sx, sy = 0.14 * S + nx * off * S, 0.86 * S + ny * off * S
        ax, ay = sx + ux * l0 * S, sy + uy * l0 * S
        bx, by = sx + ux * (l0 + l1) * S, sy + uy * (l0 + l1) * S
        hw = w * S / 2
        d.polygon([(ax, ay), (bx + nx * hw, by + ny * hw), (bx - nx * hw, by - ny * hw)], fill=c)
    # 떠난 자리의 작은 반짝임, 도착한 자리의 큰 별 (뒤에 45도 돌린 작은 별을 겹친다)
    star(0.16 * S, 0.84 * S, 0.09 * S, 0.025 * S, 0.0, c)
    star(ex, ey, 0.25 * S, 0.06 * S, math.pi / 4, c)
    star(ex, ey, 0.36 * S, 0.075 * S, 0.0, c)
    return im.resize((size, size), Image.LANCZOS)


def simple_stat(key, size, color):
    """능력치 패널용 단순한 평면 아이콘 (직접 그림). 굵은 선과 단색 도형만 쓴다."""
    import math
    from PIL import Image, ImageDraw
    S = size * 4
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = (*color, 255)
    w = int(S * 0.11)                                       # 기본 선 굵기

    def shield(pts_only=False):
        return [(0.18 * S, 0.14 * S), (0.82 * S, 0.14 * S), (0.82 * S, 0.50 * S), (0.50 * S, 0.88 * S), (0.18 * S, 0.50 * S)]

    if key == "ad":                                         # 칼: 비스듬한 칼날 + 가드 + 손잡이
        d.polygon([(0.80 * S, 0.12 * S), (0.88 * S, 0.20 * S), (0.42 * S, 0.66 * S), (0.34 * S, 0.58 * S)], fill=c)
        d.line([(0.22 * S, 0.56 * S), (0.44 * S, 0.78 * S)], fill=c, width=w)
        d.line([(0.33 * S, 0.67 * S), (0.16 * S, 0.84 * S)], fill=c, width=int(w * 0.9))
    elif key == "ap":                                       # 반짝이는 별
        cx, cy = 0.5 * S, 0.5 * S
        pts = []
        for i in range(8):
            a = -math.pi / 2 + i * math.pi / 4
            r = 0.40 * S if i % 2 == 0 else 0.12 * S
            pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
        d.polygon(pts, fill=c)
    elif key == "armor":                                    # 꽉 찬 방패
        d.polygon(shield(), fill=c)
    elif key == "mr":                                       # 테두리 방패 + 가운데 구슬
        d.polygon(shield(), outline=c, width=w)
        d.ellipse((0.40 * S, 0.34 * S, 0.60 * S, 0.54 * S), fill=c)
    elif key == "attack_speed":                             # 겹친 두 화살촉 >>
        for ox in (0.0, 0.28):
            d.line([((0.20 + ox) * S, 0.22 * S), ((0.46 + ox) * S, 0.50 * S), ((0.20 + ox) * S, 0.78 * S)], fill=c, width=w,
                   joint="curve")
    elif key == "move_speed":                               # 장화 + 속도선
        d.polygon([(0.40 * S, 0.16 * S), (0.62 * S, 0.16 * S), (0.62 * S, 0.58 * S), (0.86 * S, 0.66 * S), (0.86 * S, 0.84 * S),
                   (0.40 * S, 0.84 * S)], fill=c)
        for y in (0.36, 0.52, 0.68):
            d.line([(0.10 * S, y * S), (0.28 * S, y * S)], fill=c, width=int(w * 0.6))
    elif key == "ability_haste":                            # 모래시계
        d.line([(0.22 * S, 0.14 * S), (0.78 * S, 0.14 * S)], fill=c, width=w)
        d.line([(0.22 * S, 0.86 * S), (0.78 * S, 0.86 * S)], fill=c, width=w)
        d.polygon([(0.30 * S, 0.20 * S), (0.70 * S, 0.20 * S), (0.50 * S, 0.50 * S)], fill=c)
        d.polygon([(0.50 * S, 0.50 * S), (0.70 * S, 0.80 * S), (0.30 * S, 0.80 * S)], outline=c, width=int(w * 0.6))
    elif key == "crit":                                     # 조준경: 고리 + 네 방향 눈금 + 가운데 점
        d.ellipse((0.20 * S, 0.20 * S, 0.80 * S, 0.80 * S), outline=c, width=int(w * 0.8))
        for (x0, y0, x1, y1) in ((0.5, 0.06, 0.5, 0.30), (0.5, 0.70, 0.5, 0.94), (0.06, 0.5, 0.30, 0.5), (0.70, 0.5, 0.94, 0.5)):
            d.line([(x0 * S, y0 * S), (x1 * S, y1 * S)], fill=c, width=int(w * 0.8))
        d.ellipse((0.44 * S, 0.44 * S, 0.56 * S, 0.56 * S), fill=c)
    return im.resize((size, size), Image.LANCZOS)


COMPOSED = {"@spider_leap": spider_leap, "@serpent_dive": serpent_dive, "@flash_blink": flash_blink}


def tile(src, rel, base, gold=False):
    """둥근 사각형 타일: 한 가지 색의 평평한 배경 + 그림자가 있는 밝은 아이콘 + 테두리."""
    from PIL import Image, ImageDraw, ImageFilter
    n = BIG
    bg = mix(base, (14, 16, 26), 0.58)
    grad = Image.new("RGBA", (n, n), (*bg, 255))
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, n - 1, n - 1), radius=int(n * 0.16), fill=255)
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    im.paste(grad, (0, 0), mask)
    if rel in COMPOSED:                                     # "@이름": 직접 그린 그림
        glyph = COMPOSED[rel](src, int(n * 0.70), mix(base, (255, 255, 255), 0.82))
        shadow = COMPOSED[rel](src, int(n * 0.70), (0, 0, 0))
    else:
        glyph = svg_to_image(os.path.join(src, rel + ".svg"), int(n * 0.70), mix(base, (255, 255, 255), 0.82))
        shadow = svg_to_image(os.path.join(src, rel + ".svg"), int(n * 0.70), (0, 0, 0))
    shadow = shadow.filter(ImageFilter.GaussianBlur(n * 0.012))
    shadow.putalpha(shadow.getchannel("A").point(lambda v: int(v * 0.75)))
    off = (n - glyph.width) // 2
    im.alpha_composite(shadow, (off + int(n * 0.014), off + int(n * 0.022)))
    im.alpha_composite(glyph, (off, off))
    line = GOLD if gold else mix(base, (255, 255, 255), 0.40)
    d = ImageDraw.Draw(im)
    w = max(3, n // 32)
    d.rounded_rectangle((0, 0, n - 1, n - 1), radius=int(n * 0.16), outline=(*mix(line, (0, 0, 0), 0.35), 255), width=w)
    d.rounded_rectangle((w, w, n - 1 - w, n - 1 - w), radius=int(n * 0.14), outline=(*line, 255), width=max(2, w // 2))
    return im.resize((TILE, TILE), Image.LANCZOS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="game-icons/icons 저장소를 받아 둔 폴더")
    ap.add_argument("--only", nargs="*", help="이 챔피언 id 의 스킬 아이콘만 다시 만든다 (예: --only spider)")
    args = ap.parse_args()
    src = args.src
    colors = {}
    for fn in os.listdir(os.path.join(ROOT, "data", "champions")):
        if fn.endswith(".json"):
            with open(os.path.join(ROOT, "data", "champions", fn), encoding="utf-8") as f:
                d = json.load(f)
            colors[d["id"]] = tuple(d.get("color", (160, 170, 190)))
    for sub in ("skills", "spells", "stats"):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)
    for cid, slots in SKILLS.items():
        if args.only and cid not in args.only:
            continue
        for slot, rel in slots.items():
            tile(src, rel, colors.get(cid, (140, 150, 170)), gold=(slot == "R")).save(
                os.path.join(OUT, "skills", f"{cid}_{slot}.png"))
    if args.only:
        print("스킬 아이콘만 만들었습니다:", ", ".join(args.only))
        return
    for name, (rel, col) in SPELLS.items():
        tile(src, rel, col).save(os.path.join(OUT, "spells", f"{name}.png"))
    from PIL import Image
    for key, (_rel, col) in STATS.items():                 # 능력치 아이콘은 단순한 평면 그림 (직접 그림)
        simple_stat(key, 64, col).save(os.path.join(OUT, "stats", f"{key}.png"))
    print("아이콘을 만들었습니다:", OUT)


if __name__ == "__main__":
    main()
