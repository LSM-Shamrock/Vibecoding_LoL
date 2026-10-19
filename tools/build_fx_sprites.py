"""스킬 이펙트용 그림(PNG) 만들기 - 직접 그린 흰색+투명 스프라이트.

게임에서는 이 그림에 색(아군 파랑 / 적 빨강 등)을 곱하고 블렌딩해서 스킬 이펙트로 씁니다.
    assets/fx/<이름>.png   (그림 위쪽 = 이펙트가 향하는 방향)

사용법 (프로젝트 폴더에서):  pip install pillow numpy  →  python tools/build_fx_sprites.py
이미 만들어 둔 PNG 가 assets/fx 에 있으므로 게임을 실행하는 데는 이 스크립트가 필요 없습니다.
모양을 바꾸고 싶으면 아래 그리기 함수를 고치고 다시 실행하세요.
"""
import math
import os
import random

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "fx")
N = 256             # 완성 크기
SS = 4              # 이 배수로 크게 그린 뒤 줄여서 부드럽게 한다
W = 255


def canvas(n=N):
    return Image.new("L", (n * SS, n * SS), 0)


def finish(img, blur=0.6, n=N):
    """L(알파) 그림 -> 흰색 RGBA, 줄이고 살짝 번지게."""
    img = img.resize((n, n), Image.LANCZOS)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur * n / 128))
    out = Image.new("RGBA", (n, n), (255, 255, 255, 0))
    out.putalpha(img)
    return out


def P(x, y, n=N):
    """0~1 좌표(위쪽 y=0) -> 큰 캔버스 픽셀."""
    return (x * n * SS, y * n * SS)


def grid(n=N):
    ys, xs = np.mgrid[0:n, 0:n].astype("f4")
    return (xs + 0.5) / n, (ys + 0.5) / n


def from_array(a, n=N):
    a = np.clip(a, 0, 1) * 255
    img = Image.fromarray(a.astype("u1"), "L")
    out = Image.new("RGBA", (n, n), (255, 255, 255, 0))
    out.putalpha(img)
    return out


# ---------------------------------------------------------------- 그리기 함수들 (각각 RGBA 를 돌려준다)
def glow():
    x, y = grid()
    r = np.hypot(x - 0.5, y - 0.5) * 2
    return from_array(np.exp(-(r * 2.6) ** 2) * 0.95 + np.clip(1 - r, 0, 1) * 0.12)


def spark():
    x, y = grid()
    dx, dy = np.abs(x - 0.5) * 2, np.abs(y - 0.5) * 2
    star = np.exp(-(dx * 14) ** 1.2 - 0) * np.exp(-dy * 2.4) + np.exp(-(dy * 14) ** 1.2) * np.exp(-dx * 2.4)
    r = np.hypot(dx, dy)
    return from_array(star * 0.95 + np.exp(-(r * 4) ** 2))


def _arc_mask(span_deg, r_mid, thick, tip=0.12, n=N, cx=0.5, cy=0.78, tilt=0.0):
    """위쪽(앞)으로 볼록한 호. 가운데가 두껍고 끝이 가늘다."""
    x, y = grid(n)
    dx, dy = x - cx, cy - y                         # dy 위쪽이 +
    r = np.hypot(dx, dy)
    ang = np.degrees(np.arctan2(dx, dy))            # 0 = 위
    half = span_deg / 2
    t = np.clip(1 - np.abs(ang) / half, 0, 1)       # 가운데 1, 끝 0
    width = thick * (tip + (1 - tip) * np.sin(t * math.pi / 2) ** 0.8)
    d = np.abs(r - r_mid)
    a = np.clip(1 - d / np.maximum(width, 1e-4), 0, 1) ** 0.7
    return a * (t > 0)


def arc():
    return from_array(_arc_mask(150, 0.45, 0.075) * 0.95)


def slash():
    """굵은 초승달 베기: 안쪽 가장자리는 부드럽게, 바깥쪽은 날카롭게."""
    x, y = grid()
    cx, cy = 0.5, 0.72
    dx, dy = x - cx, cy - y
    r = np.hypot(dx, dy)
    ang = np.degrees(np.arctan2(dx, dy))
    t = np.clip(1 - np.abs(ang) / 80, 0, 1)
    outer = 0.52
    inner = outer - 0.16 * np.sin(t * math.pi / 2) ** 0.9
    a = np.clip((outer - r) / 0.012, 0, 1) * np.clip((r - inner) / 0.02, 0, 1)
    soft = np.clip((r - inner) / 0.10, 0, 1)         # 안쪽이 연하게
    a = a * (0.25 + 0.75 * soft) * np.clip(t * 2.2, 0, 1) ** 1.4
    img = Image.fromarray((np.clip(a, 0, 1) * 255).astype("u1"), "L").filter(ImageFilter.GaussianBlur(1.6))
    out = Image.new("RGBA", img.size, (255, 255, 255, 0))
    out.putalpha(img)
    return out


def ring():
    x, y = grid()
    r = np.hypot(x - 0.5, y - 0.5) * 2
    return from_array(np.exp(-((r - 0.9) / 0.06) ** 2) * 0.95 + np.exp(-((r - 0.9) / 0.2) ** 2) * 0.25)


def ring_soft():
    x, y = grid()
    r = np.hypot(x - 0.5, y - 0.5) * 2
    return from_array(np.clip(r, 0, 1) ** 3 * np.exp(-((r - 0.96) / 0.05) ** 2 * 0.3) * (r < 1.0) * 0.8
                      + np.exp(-((r - 0.93) / 0.035) ** 2))




def crack():
    rnd = random.Random(7)
    im = canvas()
    d = ImageDraw.Draw(im)

    def branch(x, y, ang, length, w, depth):
        if depth == 0 or length < 0.03:
            return
        pts = [(x, y)]
        for _ in range(4):
            ang += rnd.uniform(-0.45, 0.45)
            x += math.cos(ang) * length / 4
            y += math.sin(ang) * length / 4
            pts.append((x, y))
        for i in range(len(pts) - 1):
            ww = max(1, int(w * (1 - i / 5) * N * SS))
            d.line([P(*pts[i]), P(*pts[i + 1])], fill=W, width=ww)
        if rnd.random() < 0.8:
            branch(x, y, ang + rnd.uniform(0.5, 1.0), length * 0.6, w * 0.6, depth - 1)
        if rnd.random() < 0.6:
            branch(x, y, ang - rnd.uniform(0.5, 1.0), length * 0.6, w * 0.6, depth - 1)
        branch(x, y, ang, length * 0.7, w * 0.7, depth - 1)

    for k in range(9):
        branch(0.5, 0.5, k / 9 * math.tau + rnd.uniform(-0.2, 0.2), 0.22, 0.026, 3)
    img = finish(im, 0.7)
    x, y = grid()
    g = np.exp(-(np.hypot(x - 0.5, y - 0.5) * 7) ** 2) * 0.8
    a = np.maximum(np.asarray(img.getchannel("A"), "f4") / 255, g)
    return from_array(a)


def dust():
    rnd = np.random.RandomState(3)
    x, y = grid()
    a = np.zeros_like(x)
    for _ in range(18):
        cx, cy = rnd.uniform(0.25, 0.75, 2)
        r = rnd.uniform(0.14, 0.26)
        a = np.maximum(a, np.clip(1 - np.hypot(x - cx, y - cy) / r, 0, 1) ** 1.2 * rnd.uniform(0.5, 0.9))
    edge = np.clip(1 - np.hypot(x - 0.5, y - 0.5) * 2, 0, 1)
    return from_array(a * np.sqrt(edge) * 0.9)


def wave():
    """앞으로 퍼지는 소리 파동: 호 세 겹."""
    x, y = grid()
    cx, cy = 0.5, 0.95
    dx, dy = x - cx, cy - y
    r = np.hypot(dx, dy)
    ang = np.degrees(np.arctan2(dx, dy))
    fade = np.clip(1 - np.abs(ang) / 55, 0, 1) ** 0.7
    a = np.zeros_like(r)
    for k, (rad, w, s) in enumerate(((0.30, 0.03, 1.0), (0.52, 0.035, 0.8), (0.74, 0.04, 0.6))):
        a = np.maximum(a, np.exp(-((r - rad) / w) ** 2) * s)
    return from_array(a * fade)


def drop():
    im = canvas()
    d = ImageDraw.Draw(im)
    pts = [P(0.5, 0.08)]
    for k in range(0, 181, 6):
        t = math.radians(k)
        pts.append(P(0.5 + math.sin(t) * 0.26 * (1 if k < 180 else 1), 0.62 - math.cos(t) * 0.28 + 0.0))
    d.polygon([P(0.5, 0.08), P(0.28, 0.5), P(0.72, 0.5)], fill=W)
    d.ellipse([*P(0.24, 0.34), *P(0.76, 0.88)], fill=W)
    return finish(im, 0.8)


def cross():
    x, y = grid()
    dx, dy = np.abs(x - 0.5), np.abs(y - 0.5)
    bar = np.maximum((dx < 0.085) & (dy < 0.36), (dy < 0.085) & (dx < 0.36)).astype("f4")
    g = np.exp(-(np.hypot(dx, dy) * 5) ** 2) * 0.5
    img = from_array(bar).filter(ImageFilter.GaussianBlur(1.2))
    a = np.maximum(np.asarray(img.getchannel("A"), "f4") / 255, g)
    return from_array(a)


def _poly_sprite(points, blur=0.7, extra=None):
    im = canvas()
    d = ImageDraw.Draw(im)
    d.polygon([P(*p) for p in points], fill=W)
    if extra:
        extra(d)
    return finish(im, blur)


def _bezier(p0, p1, p2, n=24):
    out = []
    for i in range(n + 1):
        t = i / n
        out.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                    (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]))
    return out


def feather():
    left = _bezier((0.5, 0.95), (0.12, 0.55), (0.5, 0.05))
    right = _bezier((0.5, 0.05), (0.88, 0.55), (0.5, 0.95))
    im = canvas()
    d = ImageDraw.Draw(im)
    d.polygon([P(*p) for p in left + right], fill=W)
    # 깃대(비어 있는 선)
    cut = Image.new("L", im.size, 0)
    ImageDraw.Draw(cut).line([P(0.5, 0.1), P(0.5, 0.97)], fill=W, width=int(0.016 * N * SS))
    for k in range(8):                                # 깃털 결
        yy = 0.2 + k * 0.08
        ImageDraw.Draw(cut).line([P(0.5, yy + 0.07), P(0.5 + 0.2 * (1 if k % 2 else -1) * (1 - abs(yy - 0.5)), yy)],
                                 fill=W, width=int(0.008 * N * SS))
    im = ImageChops.subtract(im, cut.point(lambda v: int(v * 0.55)))
    return finish(im, 0.6)




def petal():
    left = _bezier((0.5, 0.92), (0.0, 0.55), (0.5, 0.06))
    right = _bezier((0.5, 0.06), (1.0, 0.55), (0.5, 0.92))
    return _poly_sprite(left + right, 0.8)




def flame():
    left = _bezier((0.5, 0.97), (0.04, 0.78), (0.22, 0.42)) + _bezier((0.22, 0.42), (0.34, 0.30), (0.40, 0.08))
    right = _bezier((0.40, 0.08), (0.56, 0.26), (0.60, 0.34)) + _bezier((0.60, 0.34), (0.78, 0.30), (0.74, 0.18)) \
        + _bezier((0.74, 0.18), (0.98, 0.50), (0.84, 0.74)) + _bezier((0.84, 0.74), (0.74, 0.92), (0.5, 0.97))
    im = canvas()
    ImageDraw.Draw(im).polygon([P(*p) for p in left + right], fill=W)
    img = finish(im, 1.0)
    x, y = grid()
    g = 0.45 + 0.55 * y                                    # 아래가 진하고 끝은 흐리게
    a = np.asarray(img.getchannel("A"), "f4") / 255 * g
    return from_array(a)


def shard():
    return _poly_sprite([(0.5, 0.04), (0.74, 0.58), (0.58, 0.96), (0.42, 0.96), (0.26, 0.58)], 0.7)


def streak():
    """긴 꼬리: 위(진행 방향)가 밝고 아래로 갈수록 사라진다."""
    x, y = grid()
    dx = np.abs(x - 0.5) * 2
    t = y                                              # 0 위 ~ 1 아래
    a = np.exp(-(dx / (0.10 + 0.35 * t)) ** 2) * (1 - t) ** 1.4
    head = np.exp(-((np.hypot(dx * 0.5, (t - 0.04) * 1.2)) * 5) ** 2)
    return from_array(np.maximum(a, head))




def swirl():
    im = canvas()
    d = ImageDraw.Draw(im)
    for arm in range(3):
        pts = []
        for k in range(60):
            t = k / 59
            a = arm * math.tau / 3 + t * 5.2
            r = 0.05 + t * 0.42
            pts.append(P(0.5 + math.cos(a) * r, 0.5 + math.sin(a) * r))
        for i in range(len(pts) - 1):
            w = int((0.034 * (1 - i / 60) + 0.004) * N * SS)
            d.line([pts[i], pts[i + 1]], fill=int(W * (1 - i / 90)), width=max(1, w))
    return finish(im, 0.8)


def hex_shield():
    """육각 무늬 보호막 (가운데는 비치고 가장자리가 진한 돔)."""
    x, y = grid()
    r = np.hypot(x - 0.5, y - 0.5) * 2
    size = 0.16
    px, py = (x - 0.5) / size, (y - 0.5) / size
    q = (math.sqrt(3) / 3 * px - 1.0 / 3 * py)
    rr = 2.0 / 3 * py
    cx_, cz_, cy_ = q, rr, -q - rr
    rx, rz, ry = np.round(cx_), np.round(cz_), np.round(cy_)
    dxx, dzz, dyy = np.abs(rx - cx_), np.abs(rz - cz_), np.abs(ry - cy_)
    fix = (dxx > dzz) & (dxx > dyy)
    rx = np.where(fix, -rz - ry, rx)
    fz = (~fix) & (dzz > dyy)
    rz = np.where(fz, -rx - ry, rz)
    fxp = rx * 1.0
    fzp = rz * 1.0
    cx2 = (math.sqrt(3) * fxp + math.sqrt(3) / 2 * fzp) * size
    cy2 = (1.5 * fzp) * size
    dd = np.hypot(x - 0.5 - cx2, y - 0.5 - cy2) / size
    cell_edge = np.clip(dd - 0.82, 0, 1) / 0.18                   # 칸 가장자리가 밝다
    a = (0.10 + 0.55 * cell_edge) * np.clip(r ** 1.5 * 1.1, 0.15, 1)
    a = a + np.exp(-((r - 0.93) / 0.045) ** 2) * 0.9
    return from_array(a * (r < 1.0))










def beam():
    """세로 빛기둥."""
    x, y = grid()
    dx = np.abs(x - 0.5) * 2
    a = np.exp(-(dx * 2.4) ** 2) * np.clip(1 - np.abs(y - 0.5) * 2, 0, 1) ** 0.5
    a = a * 0.8 + np.exp(-(dx * 9) ** 2) * 0.5 * (1 - np.abs(y - 0.5) * 1.6).clip(0, 1)
    return from_array(a)




def claw():
    """세 줄 할퀸 자국."""
    im = canvas()
    d = ImageDraw.Draw(im)
    for k in range(3):
        ox = (k - 1) * 0.22
        pts = _bezier((0.5 + ox - 0.10, 0.06), (0.5 + ox + 0.10, 0.5), (0.5 + ox - 0.04, 0.96))
        poly = pts + [(x + 0.07 * (1 - abs(y - 0.5) * 1.6), y) for x, y in reversed(pts)]
        d.polygon([P(*p) for p in poly], fill=W)
    return finish(im, 0.8)




def ember():
    x, y = grid()
    r = np.hypot(x - 0.5, y - 0.5) * 2
    return from_array(np.clip(1 - r, 0, 1) ** 2 * 1.2)


def web():
    """거미줄: 방사형 살과 처진 겹줄 (거미 여왕의 거미줄 발사 / 둥지)."""
    im = canvas()
    d = ImageDraw.Draw(im)
    rng = random.Random(7)
    spokes = 10
    ang = [k * math.tau / spokes + rng.uniform(-0.12, 0.12) for k in range(spokes)]
    for a in ang:
        d.line([P(0.5, 0.5), P(0.5 + math.cos(a) * 0.47, 0.5 + math.sin(a) * 0.47)], fill=W, width=int(0.012 * N * SS))
    for r in (0.1, 0.19, 0.28, 0.37):          # 바깥을 두르는 원은 그리지 않는다 (범위 테두리처럼 보이지 않게)
        for k in range(spokes):
            a0, a1 = ang[k], ang[(k + 1) % spokes] + (math.tau if k == spokes - 1 else 0)
            p0 = (0.5 + math.cos(a0) * r, 0.5 + math.sin(a0) * r)
            p1 = (0.5 + math.cos(a1) * r, 0.5 + math.sin(a1) * r)
            am = (a0 + a1) / 2
            c = (0.5 + math.cos(am) * r * 0.82, 0.5 + math.sin(am) * r * 0.82)      # 가운데가 안쪽으로 처진다
            pts = [P(*q) for q in _bezier(p0, c, p1, 10)]
            d.line(pts, fill=W, width=int(0.008 * N * SS))
    d.ellipse([*P(0.47, 0.47), *P(0.53, 0.53)], fill=W)
    return finish(im, 0.7)


def venom_disc():
    """독 웅덩이 바닥 (이무기): 어두운 원반. 가장자리는 살짝 얇아진다."""
    x, y = grid()
    r = np.hypot(x - 0.5, y - 0.5) * 2
    inside = np.clip((0.95 - r) / 0.03, 0, 1)
    return from_array(inside * (1.0 - 0.14 * np.clip(r / 0.95, 0, 1) ** 2))


def venom_bubbles():
    """독 웅덩이의 터지는 거품 (원본 보스러시와 같은 난수열): 크기가 다른 고리 26개."""
    im = canvas()
    d = ImageDraw.Draw(im)
    seed = [7]

    def rnd():
        seed[0] = (seed[0] * 16807) % 2147483647
        return seed[0] / 2147483647

    R = 0.92 / 2
    for _ in range(26):
        a = rnd() * math.tau
        dd = math.sqrt(rnd()) * R * 0.82
        rad = (5 + rnd() * 15) / 256
        al = int(W * (0.35 + rnd() * 0.35) / 0.7)
        cx, cy = 0.5 + math.cos(a) * dd, 0.5 + math.sin(a) * dd
        d.ellipse([*P(cx - rad, cy - rad), *P(cx + rad, cy + rad)], outline=min(W, al), width=int(0.0098 * N * SS))
    return finish(im, 0.5)


def venom_rim():
    """독 웅덩이 테두리: 굵은 바깥 선과 안쪽 가는 선."""
    x, y = grid()
    r = np.hypot(x - 0.5, y - 0.5) * 2
    outer = np.exp(-((r - 0.925) / 0.02) ** 2)
    inner = 0.8 * np.exp(-((r - 0.885) / 0.009) ** 2)
    return from_array(np.maximum(outer, inner) * (r < 0.97))


def magma_cracks():
    """불길 웅덩이(용)의 바닥 균열: 식어 굳은 껍질 사이로 용암이 비치는 그물 모양 틈 (보로노이 경계)."""
    x, y = grid()
    rng = np.random.RandomState(11)
    pts = []
    while len(pts) < 20:                                   # 원반 안에 고르게 흩어진 점 (너무 붙지 않게)
        px, py = rng.uniform(0.06, 0.94), rng.uniform(0.06, 0.94)
        if math.hypot(px - 0.5, py - 0.5) < 0.46 and all(math.hypot(px - a, py - b) > 0.1 for a, b in pts):
            pts.append((px, py))
    wob = 0.012 * np.sin(x * 47 + y * 31) + 0.01 * np.sin(x * 29 - y * 53)       # 틈이 곧지 않게 살짝 일렁이게
    d = np.stack([np.hypot(x + wob - a, y - wob - b) for a, b in pts], axis=0)
    d.sort(axis=0)
    edge = np.exp(-((d[1] - d[0]) / 0.011) ** 2)
    r = np.hypot(x - 0.5, y - 0.5) * 2
    inside = np.clip((0.93 - r) / 0.04, 0, 1)
    core = np.exp(-(r * 1.6) ** 2) * 0.35                  # 한가운데는 더 뜨겁게 비친다
    return from_array((edge * (0.75 + 0.25 * np.exp(-(r * 1.4) ** 2)) + core * edge) * inside)


SPRITES = {
    "magma_cracks": magma_cracks,
    "web": web, "venom_disc": venom_disc, "venom_bubbles": venom_bubbles, "venom_rim": venom_rim, "glow": glow, "spark": spark, "arc": arc, "slash": slash, "ring": ring, "ring_soft": ring_soft,
    "crack": crack, "dust": dust, "wave": wave, "drop": drop, "cross": cross, "feather": feather,
    "petal": petal, "flame": flame, "shard": shard, "streak": streak, "swirl": swirl,
    "hex": hex_shield, "beam": beam,
    "claw": claw, "ember": ember,
}


def main():
    """인자 없이 실행하면 전부, 이름을 주면(예: python tools/build_fx_sprites.py web) 그것만 다시 만든다."""
    import sys
    os.makedirs(OUT, exist_ok=True)
    only = [n for n in sys.argv[1:] if n in SPRITES]
    for name, fn in SPRITES.items():
        if only and name not in only:
            continue
        im = fn()
        # 그림 가장자리가 반드시 투명해지도록 (사각형 테두리가 보이지 않게)
        x, y = grid(im.width)
        win = np.clip((0.5 - np.abs(x - 0.5)) / 0.04, 0, 1) * np.clip((0.5 - np.abs(y - 0.5)) / 0.04, 0, 1)
        a = np.asarray(im.getchannel("A"), "f4") / 255 * win
        im.putalpha(Image.fromarray((a * 255).astype("u1"), "L"))
        im.save(os.path.join(OUT, name + ".png"))
    print("이펙트 그림을 만들었습니다:", OUT, f"({len(only) or len(SPRITES)}개)")


if __name__ == "__main__":
    main()
