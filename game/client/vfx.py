"""스킬 이펙트: 직접 그린 그림(assets/fx/*.png)을 이용한 입자 효과.

서버가 보내는 효과 이벤트(fx)와 스킬 시전(cast), 날아가는 투사체, 챔피언 상태를 받아서
각 스킬의 컨셉에 맞는 이펙트(균열, 베기, 소리 파동, 가시 덩굴, 빛기둥, 날개 ...)를 만든다.

그림은 흰색+투명이라 색을 곱해서 쓴다: 아군 스킬은 파랑, 적 스킬은 빨강이 주색이고(fx_color),
피해 없이 효과만 주는 스킬은 더 연하고 투명하게 그린다.
"""
import contextlib
import math
import os
import random

import moderngl
import numpy as np
import pygame

from .geometry import MeshBuilder
from .gl import Mesh, facing_to_rot, model_matrix

# ---------------------------------------------------------------- 색 규칙 (아군 파랑 / 적 빨강)
TEAM_FX = {True: (0.35, 0.62, 1.0), False: (1.0, 0.30, 0.27)}
TEAM_FX_MIX = 0.72                  # 팀 색 비율 (나머지는 스킬 고유 색)
SUPPORT_ALPHA = 0.55                # 피해 없이 효과만 주는 스킬 이펙트의 투명도 (피해 스킬은 1.0)
SUPPORT_LIGHTEN = 0.35              # ... 그리고 그만큼 흰색 쪽으로 연하게
# 피해를 주지 않고 효과(회복·보호막·강화·이동·약화)만 주는 이펙트
SUPPORT_FX = {"relic", "recall", "flash"}
SUPPORT_SPELLS = {"heal", "ghost", "barrier", "cleanse", "exhaust"}      # 소환사 주문 중 피해 없는 것


def fx_color(col, ally, support):
    """이펙트 색 -> (보여 줄 색, 투명도 배율). ally: True 아군 / False 적 / None 중립(원래 색 유지)."""
    if ally is not None:
        t = TEAM_FX[ally]
        col = tuple(t[i] * TEAM_FX_MIX + col[i] * (1 - TEAM_FX_MIX) for i in range(3))
    if support:
        col = tuple(min(1.4, c + (1.0 - c) * SUPPORT_LIGHTEN) for c in col)
        return col, SUPPORT_ALPHA
    return col, 1.0


FX_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "fx")
MAX_PARTICLES = 700

# 자주 쓰는 색 (스킬 고유 색 — 여기에 팀 색이 섞인다)
GOLD = (1.0, 0.85, 0.4)
PALE = (0.92, 0.96, 1.0)
STEEL = (0.85, 0.92, 1.0)
SOUL = (0.55, 0.35, 0.9)
GHOST = (0.6, 0.85, 1.0)
EARTH = (0.8, 0.62, 0.38)
FIRE = (1.0, 0.5, 0.15)
HOLY = (1.0, 0.93, 0.6)
BRONZE = (0.9, 0.7, 0.35)
CREAM = (0.96, 0.9, 0.78)               # 거미줄
POISON = (1.0, 0.38, 0.2)               # 독침
VENOM = (0.6, 0.95, 0.3)                # 독 거미줄 둥지
TEAL = (0.4, 0.95, 0.82)                # 이무기의 물기운
TOXIC = (0.5, 1.0, 0.45)                # 이무기의 독
TOXIC_DARK = (0.12, 0.5, 0.28)          # (예전 초록 독 바닥: 지금은 쓰지 않음)
VENOM_P = (0.34, 0.1, 0.82)             # 이무기의 독 덩어리 (보스러시 원본의 보라색 독)
VENOM_HOT = (0.48, 0.24, 0.88)
VENOM_FLOOR = (0.1, 0.03, 0.26)         # 독 웅덩이의 어두운 바닥
VENOM_BUB = (0.5, 0.32, 0.88)           # 거품 고리
VENOM_RIM = (0.45, 0.25, 0.85)          # 웅덩이 테두리
LAVA = (1.0, 0.5, 0.12)                 # 용의 불길
LAVA_HOT = (1.0, 0.82, 0.38)
SCORCH = (0.12, 0.04, 0.025)            # 불길 웅덩이의 그을린 바닥
LAVA_RIM = (1.0, 0.42, 0.1)
WIND = (1.0, 0.88, 0.7)                 # 날개바람 (불기운이 섞인 뜨거운 바람)
REAP = (0.62, 0.48, 1.0)                # 사신의 영혼 빛
REAP_HOT = (0.86, 0.82, 1.0)
REAP_SOUL = (0.55, 0.95, 1.0)           # 사신의 눈·날끝과 같은 청록 빛

_rnd = random.Random(11)


def _smooth01(k):
    k = min(1.0, max(0.0, k))
    return k * k * (3 - 2 * k)


def rr(a, b):
    return _rnd.uniform(a, b)


def _unit_quads(renderer):
    """그림 한 장을 붙일 사각형 두 개: 땅에 눕는 것(XZ, 위쪽 = +Z)과 서 있는 것(XY, 위쪽 = +Y)."""
    flat, bill = MeshBuilder(), MeshBuilder()
    n = (0, 1, 0)
    flat.tri((-.5, 0, -.5), (-.5, 0, .5), (.5, 0, .5), (1, 1, 1), n, n, n, (0, 0), (0, 1), (1, 1))
    flat.tri((-.5, 0, -.5), (.5, 0, .5), (.5, 0, -.5), (1, 1, 1), n, n, n, (0, 0), (1, 1), (1, 0))
    n = (0, 0, 1)
    bill.tri((-.5, -.5, 0), (.5, -.5, 0), (.5, .5, 0), (1, 1, 1), n, n, n, (0, 0), (1, 0), (1, 1))
    bill.tri((-.5, -.5, 0), (.5, .5, 0), (-.5, .5, 0), (1, 1, 1), n, n, n, (0, 0), (1, 1), (0, 1))
    return flat.array(), bill.array()


class Vfx:
    def __init__(self, renderer):
        self.r = renderer
        self.flat_arr, self.bill_arr = _unit_quads(renderer)
        self.meshes = {}                # 이름 -> (눕는 메시, 서 있는 메시)
        self.parts = []
        self.now = 0.0
        self.dt = 0.016
        self._ctx = (None, False)
        self.enabled = True

    # ------------------------------------------------------------ 그림 불러오기
    def mesh(self, name, mode):
        pair = self.meshes.get(name)
        if pair is None:
            path = os.path.join(FX_DIR, name + ".png")
            tex = None
            if os.path.exists(path):
                try:
                    tex = self.r.make_texture(pygame.image.load(path).convert_alpha())
                    tex.build_mipmaps()
                    tex.filter = (moderngl.LINEAR, moderngl.LINEAR)     # 이펙트 그림은 보간만 (밉맵 없이)
                except pygame.error:
                    tex = None
            if tex is None:
                pair = (None, None)
            else:
                pair = (Mesh(self.r, [(self.flat_arr, tex)]), Mesh(self.r, [(self.bill_arr, tex)]))
            self.meshes[name] = pair
        return pair[0 if mode == "flat" else 1]

    # ------------------------------------------------------------ 색 규칙 적용 범위
    def ctx(self, ally, support):
        self._ctx = (ally, support)

    def clear_ctx(self):
        self._ctx = (None, False)

    @contextlib.contextmanager
    def neutral(self):
        """이 안에서 만드는 입자는 팀 색을 섞지 않고 제 색 그대로 (불꽃처럼 색이 곧 정체인 이펙트)."""
        old = self._ctx
        self._ctx = (None, False)
        try:
            yield
        finally:
            self._ctx = old

    # ------------------------------------------------------------ 입자
    def emit(self, name, x, y, z, size=1.0, size_to=None, dur=0.6, delay=0.0, col=(1, 1, 1), col_to=None, alpha=1.0,
             mode="bill", rot=0.0, spin=0.0, vel=(0.0, 0.0, 0.0), grav=0.0, add=True, fade_in=0.08, fade_pow=1.0,
             orbit=None, pivot=0.0, roll_to_vel=False):
        """그림 하나를 띄운다.
        mode "bill": 카메라를 보는 그림 (rot = 그림 안에서 돌린 각도) / "flat": 땅과 나란한 그림 (rot = 위쪽이 향하는 방향의 Y 회전).
        size: 숫자 또는 (폭, 길이). orbit = (cx, cz, 반지름 시작, 반지름 끝, 각도 시작, 각속도, 올라가는 속도).
        pivot: flat 그림을 위쪽 방향으로 (길이 × pivot) 만큼 밀어 중심을 맞춘다 (호 모양 그림의 원 중심을 시전자에 맞출 때)."""
        if len(self.parts) >= MAX_PARTICLES or not self.enabled:
            return
        ally, support = self._ctx
        c, am = fx_color(col, ally, support)
        c2 = None
        if col_to is not None:
            c2 = fx_color(col_to, ally, support)[0]
        s0 = size if isinstance(size, (tuple, list)) else (size, size)
        if size_to is None:
            s1 = s0
        else:
            s1 = size_to if isinstance(size_to, (tuple, list)) else (size_to, size_to)
        self.parts.append({"n": name, "x": x, "y": y, "z": z, "s0": s0, "s1": s1, "dur": max(0.05, dur),
                           "t0": self.now + delay, "c0": c, "c1": c2 or c, "a": alpha * am, "mode": mode, "rot": rot,
                           "spin": spin, "v": vel, "g": grav, "add": add, "fi": fade_in, "fp": fade_pow,
                           "orb": orbit, "pv": pivot, "rv": roll_to_vel})

    def burst(self, name, x, y, z, n, speed, size, dur, col, up=0.0, grav=0.0, spread=1.0, size_to=0.0, spin=0.0, **kw):
        """한 점에서 사방으로 흩어지는 입자 n 개."""
        for _ in range(n):
            a = rr(0, math.tau)
            sp = speed * rr(0.5, 1.0)
            self.emit(name, x, y, z, size=size * rr(0.7, 1.3), size_to=size_to, dur=dur * rr(0.8, 1.2), col=col,
                      vel=(math.cos(a) * sp * spread, up * rr(0.6, 1.2), math.sin(a) * sp * spread), grav=grav,
                      rot=rr(0, math.tau), spin=rr(-spin, spin), **kw)

    def rate(self, per_sec):
        """이번 프레임에 만들 입자 수 (초당 per_sec 개를 확률로 맞춘다)."""
        v = per_sec * self.dt
        n = int(v)
        if _rnd.random() < v - n:
            n += 1
        return n

    def tick(self, now):
        self.dt = max(0.001, min(0.1, now - self.now)) if self.now else 0.016
        self.now = now
        self.parts = [p for p in self.parts if now - p["t0"] < p["dur"]]

    # ------------------------------------------------------------ 그리기
    def draw(self, cam):
        r = self.r
        yaw, pitch = cam.yaw, cam.pitch
        sy, cy, sp_, cp = math.sin(yaw), math.cos(yaw), math.sin(pitch), math.cos(pitch)
        right = np.array([cy, 0.0, -sy], dtype="f4")
        up = np.array([-sy * sp_, cp, -cy * sp_], dtype="f4")
        nrm = np.array([sy * cp, sp_, cy * cp], dtype="f4")
        now = self.now
        for additive in (False, True):
            for p in self.parts:
                if p["add"] != additive:
                    continue
                age = now - p["t0"]
                if age < 0:
                    continue
                k = age / p["dur"]
                mesh = self.mesh(p["n"], p["mode"])
                if mesh is None:
                    continue
                if p["orb"]:
                    cx, cz, r0, r1, a0, w, rise = p["orb"]
                    ang = a0 + w * age
                    rad = r0 + (r1 - r0) * k
                    x, z = cx + math.cos(ang) * rad, cz + math.sin(ang) * rad
                    y = p["y"] + rise * age
                else:
                    vx, vy, vz = p["v"]
                    x = p["x"] + vx * age
                    z = p["z"] + vz * age
                    y = p["y"] + vy * age + 0.5 * p["g"] * age * age
                    if y < 0.05 and p["g"] != 0.0:
                        y = 0.05
                w = p["s0"][0] + (p["s1"][0] - p["s0"][0]) * k
                h = p["s0"][1] + (p["s1"][1] - p["s0"][1]) * k
                al = p["a"] * min(1.0, age / p["fi"] if p["fi"] > 0 else 1.0) * max(0.0, 1.0 - k) ** p["fp"]
                if al <= 0.004:
                    continue
                col = tuple(p["c0"][i] + (p["c1"][i] - p["c0"][i]) * k for i in range(3))
                rot = p["rot"] + p["spin"] * age
                if p["mode"] == "flat":
                    if p["pv"]:
                        x += math.sin(rot) * h * p["pv"]
                        z += math.cos(rot) * h * p["pv"]
                    m = model_matrix(x, y, z, rot_y=rot, sx=w, sy=1.0, sz=h)
                else:
                    if p["rv"]:
                        vx, vy, vz = p["v"]
                        sx_, sy_ = float(np.dot((vx, vy, vz), right)), float(np.dot((vx, vy, vz), up))
                        rot = math.atan2(-sx_, sy_) if (sx_ or sy_) else rot
                    y = max(y, h * 0.5 * cp)            # 땅 속으로 잘려 들어가지 않게
                    c, s = math.cos(rot), math.sin(rot)
                    rx = right * c + up * s
                    ux = -right * s + up * c
                    m = np.eye(4, dtype="f4")
                    m[:3, 0] = rx * w
                    m[:3, 1] = ux * h
                    m[:3, 2] = nrm
                    m[:3, 3] = (x, y, z)
                r.draw_transparent(mesh, m, (*col, min(1.0, al)), additive=additive)

    # ============================================================== 서버 효과 이벤트별 연출
    def play(self, kind, ev, ally, support):
        """서버 fx 이벤트 하나를 컨셉 이펙트로 만든다. 만든 게 있으면 True (기존 단순 효과는 건너뛴다)."""
        fn = getattr(self, "fx_" + kind, None)
        if fn is None and kind.endswith("_hit"):
            fn = self.fx_hit
        if fn is None:
            return False
        self.ctx(ally, support)
        try:
            fn(kind, ev)
        finally:
            self.clear_ctx()
        return True

    # ---- 공통 부품
    def shock(self, x, z, radius, col=PALE, dur=0.5, delay=0.0):
        self.emit("ring", x, 0.1, z, size=radius * 0.6, size_to=radius * 2.1, dur=dur, delay=delay, col=col, mode="flat",
                  fade_pow=1.3)

    def dust_ring(self, x, z, radius, n=10, col=(0.8, 0.78, 0.72), dur=0.8):
        for i in range(n):
            a = i / n * math.tau + rr(-0.2, 0.2)
            sp = radius * rr(1.0, 1.6)
            self.emit("dust", x + math.cos(a) * radius * 0.2, 0.3, z + math.sin(a) * radius * 0.2, size=radius * 0.5,
                      size_to=radius * rr(0.9, 1.3), dur=dur * rr(0.8, 1.2), col=col, alpha=0.55, add=False,
                      vel=(math.cos(a) * sp, 0.4, math.sin(a) * sp), fade_pow=1.4)

    def pillar(self, x, z, col, h=9.0, w=1.2, dur=0.6):
        self.emit("beam", x, h * 0.5, z, size=(w * 1.6, h), size_to=(w * 0.5, h), dur=dur, col=col, fade_in=0.05)

    def stones(self, x, z, radius, n, col=EARTH, dur=0.8):
        for _ in range(n):
            a = rr(0, math.tau)
            d = radius * rr(0.15, 0.9)
            self.emit("shard", x + math.cos(a) * d, 0.2, z + math.sin(a) * d, size=(rr(0.25, 0.5), rr(0.4, 0.8)),
                      dur=dur * rr(0.7, 1.1), col=col, add=False, vel=(math.cos(a) * 1.5, rr(4, 8), math.sin(a) * 1.5),
                      grav=-22.0, rot=rr(0, math.tau), spin=rr(-9, 9), fade_pow=0.6, fade_in=0.01)

    # ---- 내려찍기 착지 ----------------------------------------------------
    def fx_slam(self, kind, ev):
        x, z, r = ev["x"], ev["z"], ev.get("r", 3.0)
        style = ev.get("style", "pounce")
        if style == "pounce":                               # 거미의 점프 덮치기: 갈라진 땅, 먼지, 흩어지는 거미줄
            self.emit("crack", x, 0.06, z, size=r * 2.4, dur=1.2, col=CREAM, mode="flat", rot=rr(0, 6), fade_pow=0.8)
            self.emit("web", x, 0.08, z, size=r * 1.5, size_to=r * 2.6, dur=0.8, col=CREAM, mode="flat", rot=rr(0, 6),
                      fade_pow=1.2)
            self.emit("glow", x, 0.1, z, size=r * 2.0, dur=0.3, col=POISON, mode="flat")
            self.shock(x, z, r, CREAM, 0.5)
            self.dust_ring(x, z, r * 0.9, 12)
            self.stones(x, z, r, 10, col=(0.7, 0.5, 0.35))
        elif style == "serpent":                              # 이무기 내려찍기: 머리가 땅에 꽂히며 균열과 물보라
            self.emit("crack", x, 0.06, z, size=r * 2.4, dur=1.2, col=(0.7, 1.0, 0.9), mode="flat", rot=rr(0, 6), fade_pow=0.8)
            self.emit("glow", x, 0.1, z, size=r * 2.1, dur=0.3, col=TEAL, mode="flat")
            self.shock(x, z, r, TEAL, 0.45)
            self.dust_ring(x, z, r * 0.8, 10)
            self.stones(x, z, r, 9)
            self.burst("glow", x, 0.5, z, 12, r * 2.0, 0.45, 0.7, TEAL, up=5.0, grav=-14)
        elif style == "skyfire":                              # 용의 급강하 착지: 땅이 터지며 불기둥이 솟는다
            self.spit_land_fire(x, z, r)
            self.emit("crack", x, 0.06, z, size=r * 2.6, dur=1.6, col=LAVA, mode="flat", rot=rr(0, 6), fade_pow=0.8, alpha=0.9)
            self.shock(x, z, r * 1.5, LAVA_HOT, 0.6)
            self.shock(x, z, r * 2.0, LAVA_RIM, 0.8, 0.1)
            self.dust_ring(x, z, r, 14)
            with self.neutral():
                self.emit("flame", x, 2.2, z, size=(r * 1.2, r * 3.0), dur=0.7, col=LAVA, col_to=LAVA_HOT, vel=(0, 3, 0), fade_pow=0.8, fade_in=0.0)
                for i in range(10):
                    a_ = i / 10 * math.tau
                    self.emit("flame", x + math.cos(a_) * r * 0.7, 0.3, z + math.sin(a_) * r * 0.7, size=(1.1, 2.2), dur=rr(0.5, 0.8),
                              col=LAVA, col_to=LAVA_HOT, vel=(math.cos(a_) * 3, rr(2, 4), math.sin(a_) * 3), fade_pow=0.9)
        elif style == "wing":                                 # 용의 날개 후려치기: 몸 둘레를 도는 날개 베기와 뜨거운 먼지
            base = rr(0, math.tau)
            for k in range(3):
                self.emit("slash", x, 0.9, z, size=r * 2.2, dur=0.4, delay=k * 0.05, col=WIND, mode="flat", rot=base + k * 2.1, spin=-12.0,
                          pivot=0.22, fade_pow=0.8, fade_in=0.02)
            self.emit("arc", x, 0.95, z, size=r * 2.4, dur=0.35, col=LAVA_HOT, mode="flat", rot=base, spin=-12.0, pivot=0.28, fade_pow=0.8)
            self.emit("glow", x, 0.1, z, size=r * 2.2, dur=0.3, col=LAVA, mode="flat")
            self.shock(x, z, r, LAVA_HOT, 0.45)
            self.dust_ring(x, z, r * 0.8, 12)
            self.burst("ember", x, 0.7, z, 10, r * 2.4, 0.3, 0.5, LAVA_HOT, up=1.5, grav=-6)
        elif style == "dive":                                 # 이무기 솟구침: 땅이 터지며 물기둥이 선다
            self.emit("crack", x, 0.06, z, size=r * 2.6, dur=1.3, col=(0.7, 1.0, 0.9), mode="flat", rot=rr(0, 6), fade_pow=0.8)
            self.emit("glow", x, 0.1, z, size=r * 2.4, dur=0.4, col=TEAL, mode="flat")
            self.shock(x, z, r, TEAL, 0.5)
            self.shock(x, z, r * 1.4, PALE, 0.65, 0.08)
            self.dust_ring(x, z, r * 0.9, 12)
            self.stones(x, z, r, 12)
            self.pillar(x, z, TEAL, 9.0, 1.8, 0.55)
            self.burst("glow", x, 0.5, z, 16, r * 2.2, 0.45, 0.8, TEAL, up=6.0, grav=-15)

    def fx_hit(self, kind, ev):
        """투사체가 맞았을 때: 투사체 종류마다 다른 모습."""
        x, z = ev["x"], ev["z"]
        style = kind[:-4]
        if style == "web":                                  # 거미줄 덩어리: 터지며 거미줄이 달라붙는다
            self.emit("web", x, 1.0, z, size=1.2, size_to=2.6, dur=0.7, col=CREAM, rot=rr(0, 6), fade_pow=1.1)
            self.emit("glow", x, 1.0, z, size=1.8, dur=0.3, col=CREAM)
            self.burst("spark", x, 1.0, z, 8, 3.0, 0.3, 0.4, CREAM, up=1.2)
        elif style == "spine":                                # 독침: 독이 튄다
            self.emit("glow", x, 1.0, z, size=1.4, dur=0.25, col=POISON)
            self.burst("drop", x, 1.0, z, 4, 2.6, 0.28, 0.5, POISON, up=2.0, grav=-9)
        elif style == "fire_bolt":                            # 불꽃: 작게 터지는 불똥
            with self.neutral():
                self.emit("glow", x, 1.2, z, size=1.6, dur=0.25, col=LAVA)
                self.emit("flame", x, 1.0, z, size=(0.6, 0.9), dur=0.35, col=LAVA, col_to=LAVA_HOT, vel=(0, 1.5, 0))
                self.burst("ember", x, 1.1, z, 5, 2.6, 0.18, 0.4, LAVA_HOT, up=1.5, grav=-6)
        elif style == "tornado":                              # 회오리: 맞은 자리에 바람이 휘감긴다
            c_ = (0.87, 0.92, 1.0)
            self.emit("ring", x, 0.8, z, size=0.8, size_to=2.2, dur=0.35, col=c_, mode="flat", fade_pow=1.1)
            self.burst("spark", x, 1.0, z, 8, 3.2, 0.25, 0.4, c_, up=1.5)
        elif style == "scythe":                               # 던진 낫: 베인 자리에 영혼 빛이 튄다
            self.emit("slash", x, 1.1, z, size=1.9, dur=0.25, col=REAP_HOT, rot=rr(0, 6), fade_pow=0.8)
            self.emit("glow", x, 1.0, z, size=1.5, dur=0.25, col=REAP)
            self.burst("spark", x, 1.0, z, 7, 3.2, 0.3, 0.4, REAP_SOUL, up=1.5)
        elif style == "snowball":                             # 눈덩이: 눈가루
            self.emit("dust", x, 1.0, z, size=1.0, size_to=2.0, dur=0.4, col=PALE, alpha=0.8, add=False)
            self.burst("spark", x, 1.0, z, 6, 3.0, 0.3, 0.4, PALE, up=1.5)
        else:
            self.emit("spark", x, 1.0, z, size=1.1, dur=0.22, col=PALE)

    # ---- 소환사 주문 (회복·정화) ------------------------------------------
    def fx_heal(self, kind, ev):                              # 치유의 빛: 십자가가 피어오른다
        x, z = ev["x"], ev["z"]
        self.emit("glow", x, 1.0, z, size=3.0, dur=0.7, col=HOLY, fade_in=0.15)
        self.emit("ring", x, 0.1, z, size=1.0, size_to=2.2, dur=0.6, col=HOLY, mode="flat")
        for i in range(6):
            a = rr(0, math.tau)
            d = rr(0.2, 0.8)
            self.emit("cross", x + math.cos(a) * d, 0.3, z + math.sin(a) * d, size=rr(0.35, 0.6), dur=rr(0.8, 1.2),
                      delay=i * 0.07, col=HOLY, vel=(0, rr(1.2, 2.2), 0), fade_pow=0.8)
        for i in range(3):
            self.emit("feather", x, 1.5, z, size=(0.4, 0.7), dur=1.0, delay=i * 0.1, col=PALE,
                      vel=(rr(-0.8, 0.8), -0.6, rr(-0.8, 0.8)), rot=rr(-1, 1), spin=rr(-2, 2), fade_pow=0.8)

    def fx_cleanse(self, kind, ev):                           # 정화: 맑은 불꽃이 둘레를 돌며 오른다
        x, z = ev["x"], ev["z"]
        for k in range(10):
            a = k / 10 * math.tau
            self.emit("spark", x, 0.2, z, size=0.7, dur=0.9, delay=k * 0.03, col=PALE,
                      orbit=(x, z, 1.2, 0.5, a, 6.0, 2.0), fade_pow=0.8)
        for k in range(2):
            self.emit("ring", x, 0.1, z, size=0.8, size_to=2.6, dur=0.7, delay=k * 0.15, col=PALE, mode="flat")
        self.emit("glow", x, 1.0, z, size=2.4, dur=0.5, col=PALE)
        self.burst("feather", x, 1.4, z, 3, 1.0, 0.45, 1.0, PALE, up=0.5, grav=-1.5, spin=2)

    def fx_zone_start(self, kind, ev):
        x, z, r = ev["x"], ev["z"], ev.get("r", 4.0)
        if ev.get("style") == "web":                        # 독 거미줄 둥지: 거미줄이 쫙 펼쳐지고 독 방울이 오른다
            self.emit("web", x, 0.09, z, size=r * 1.2, size_to=r * 2.2, dur=0.9, col=CREAM, mode="flat", fade_pow=1.4)
            self.emit("glow", x, 0.1, z, size=r * 2.2, dur=0.5, col=VENOM, mode="flat")
            self.shock(x, z, r, VENOM, 0.7)
            self.dust_ring(x, z, min(r * 0.45, 1.8), 8, col=(0.8, 0.85, 0.7))     # 먼지 덩어리가 너무 크면 바닥에 잘려 네모로 보인다

    # ---- 거미 여왕 ------------------------------------------------------
    def fx_volley(self, kind, ev):                            # 독침 탄막: 배끝에서 독침이 부채꼴로 튀어나간다
        x, z, a = ev["x"], ev["z"], ev["a"]
        w = math.radians(ev.get("w", 56))
        self.emit("glow", x, 0.9, z, size=2.4, dur=0.3, col=POISON)
        self.shock(x, z, 1.4, POISON, 0.35)
        for k in range(5):
            rot = facing_to_rot(a + (k / 4 - 0.5) * w)
            self.emit("streak", x, 0.9, z, size=(0.25, 3.2), dur=0.28, col=POISON, mode="flat", rot=rot, pivot=0.5,
                      fade_pow=0.8)
        self.burst("drop", x, 1.2, z, 6, 3.0, 0.3, 0.5, POISON, up=2.5, grav=-8)

    def fx_leap(self, kind, ev):                              # 점프 덮치기: 도약 지점에 먼지 + 날아가는 자국
        x, z, x2, z2 = ev["x"], ev["z"], ev["x2"], ev["z2"]
        dx, dz = x2 - x, z2 - z
        dist = max(0.5, math.hypot(dx, dz))
        rot = math.atan2(dx, dz)
        self.shock(x, z, 1.5, CREAM, 0.4)
        self.dust_ring(x, z, 1.3, 8)
        self.emit("glow", x, 0.1, z, size=2.4, dur=max(0.2, ev.get("delay", 0.0) + 0.1), col=CREAM, mode="flat")   # 웅크리며 모으는 기운

    def fx_cocoon_set(self, kind, ev):                        # 고치가 툭 떨어진다: 비단 가루와 먼지
        x, z = ev["x"], ev["z"]
        self.emit("web", x, 0.08, z, size=1.0, size_to=1.9, dur=0.5, col=CREAM, mode="flat", rot=rr(0, 6), fade_pow=1.2)
        self.burst("glow", x, 0.5, z, 5, 1.6, 0.22, 0.4, CREAM, up=1.4, grav=-6)
        self.dust_ring(x, z, 0.7, 5)

    def fx_cocoon_hatch(self, kind, ev):                      # 부화: 껍질이 터지며 새끼 거미가 튀어나온다
        x, z = ev["x"], ev["z"]
        self.emit("glow", x, 0.6, z, size=2.2, dur=0.3, col=(1.0, 0.8, 0.35))
        self.shock(x, z, 1.0, CREAM, 0.35)
        self.burst("shard", x, 0.5, z, 8, 3.0, 0.22, 0.5, CREAM, up=3.0, grav=-12, spin=8)

    def fx_cocoon_break(self, kind, ev):                      # 부화 전에 깨짐: 비단 조각만 흩어진다
        x, z = ev["x"], ev["z"]
        self.burst("shard", x, 0.5, z, 10, 3.2, 0.24, 0.5, CREAM, up=3.0, grav=-12, spin=8)
        self.dust_ring(x, z, 0.8, 5)

    def fx_spiderling_pop(self, kind, ev):                    # 새끼 거미 폭발: 독 방울이 터진다
        x, z, r = ev["x"], ev["z"], ev.get("r", 0.0)
        if r > 0:
            self.shock(x, z, r, POISON, 0.4)
            self.emit("glow", x, 0.5, z, size=r * 1.6, dur=0.3, col=POISON)
        self.burst("drop", x, 0.6, z, 8, 3.0, 0.28, 0.5, POISON, up=3.0, grav=-9)

    def web_zone(self, x, z, radius, ally, left, total):
        """독 거미줄 둥지가 남아 있는 동안 매 프레임: 바닥의 거미줄과 오르는 독 방울."""
        self.ctx(ally, False)
        try:
            fade = min(1.0, left / 1.2)
            self.emit("web", x, 0.075, z, size=radius * 2.15, dur=self.dt * 1.4 + 0.001, col=CREAM, mode="flat",
                      fade_in=0.0, alpha=0.8 * fade)
            self.emit("glow", x, 0.06, z, size=radius * 2.0, dur=self.dt * 1.4 + 0.001, col=VENOM, mode="flat",
                      fade_in=0.0, alpha=0.25 * fade)
        finally:
            self.clear_ctx()

    # ---- 이무기 ---------------------------------------------------------
    def fx_spit(self, kind, ev):                              # 독 뱉기: 입에서 독 덩어리가 포물선을 그리며 날아간다
        if ev.get("style") == "fire":
            return self.spit_fire(ev)
        x, z, x2, z2 = ev["x"], ev["z"], ev["x2"], ev["z2"]
        dx, dz = x2 - x, z2 - z
        dist = max(0.5, math.hypot(dx, dz))
        ux, uz = dx / dist, dz / dist
        if "mx" in ev:                                        # 서버가 머리를 쳐든 뒤에 보낸 이벤트 + 리그의 실제 입 위치
            delay = 0.0
            x0, y0, z0 = ev["mx"], ev["my"], ev["mz"]
        else:
            delay = 0.1                                       # 머리를 쳐드는 동안은 입에서 아직 안 나간다
            x0, y0, z0 = x + ux * 0.9, 2.45, z + uz * 0.9            # 세운 머리의 입 높이
        T = max(0.25, ev.get("dur", 0.7) - delay)
        g = -18.0
        vx, vz = (x2 - x0) / T, (z2 - z0) / T
        vy = ((0.15 - y0) - 0.5 * g * T * T) / T
        self.emit("glow", x0, y0, z0, size=1.0, dur=T, delay=delay, col=VENOM_P, vel=(vx, vy, vz), grav=g, fade_in=0.0, fade_pow=0.15)
        self.emit("glow", x0, y0, z0, size=0.55, dur=T, delay=delay, col=(0.82, 0.7, 1.0), vel=(vx, vy, vz), grav=g,
                  fade_in=0.0, fade_pow=0.1)
        for i in range(10):                                   # 지나간 자리에 남는 독방울 꼬리
            ti = T * (i + 0.5) / 10
            self.emit("glow", x0 + vx * ti, y0 + vy * ti + 0.5 * g * ti * ti, z0 + vz * ti, size=0.5, size_to=0.08, dur=0.4,
                      delay=delay + ti, col=VENOM_P, alpha=0.7, fade_in=0.0, vel=(0, 0.3, 0))
        self.burst("glow", x0, y0, z0, 5, 2.0, 0.28, 0.4, VENOM_P, up=1.5, grav=-9, delay=delay)

    def fx_spit_land(self, kind, ev):                         # 독 덩어리가 터진다
        x, z, r = ev["x"], ev["z"], ev.get("r", 2.0)
        if ev.get("style") == "fire":
            return self.spit_land_fire(x, z, r)
        self.emit("glow", x, 0.1, z, size=r * 2.0, dur=0.35, col=VENOM_P, mode="flat")
        self.shock(x, z, r * 1.15, VENOM_HOT, 0.4)
        self.burst("glow", x, 0.4, z, 12, r * 1.6, 0.4, 0.6, VENOM_P, up=4.0, grav=-14)

    def venom_zone(self, x, z, radius, ally, left, total):
        """독 웅덩이 (원본 보스러시와 같은 모양): 어두운 보라색 바닥 + 터지는 거품 고리 + 밝은 보라 테두리.
        웅덩이는 팀과 상관없이 보라색이고, 사라지기 직전 1.6초는 깜빡인다."""
        dt = self.dt * 1.4 + 0.001
        grow = min(1.0, (total - left) / 0.22) if total > 0 else 1.0
        grow = 0.55 + 0.45 * (1 - (1 - grow) ** 3)
        fade = min(1.0, left / 1.2) * min(1.0, max(0.05, (total - left) / 0.22))
        warn = 0.6 + 0.4 * math.sin(self.now * 18) if left < 1.6 else 1.0
        k = fade * warn
        S = radius * 2.1 * grow
        spin = self.now * 0.25 + x * 1.7 + z * 0.9
        self.ctx(None, False)
        try:
            self.emit("venom_disc", x, 0.05, z, size=S, dur=dt, col=VENOM_FLOOR, mode="flat", fade_in=0.0, alpha=0.94 * k, add=False)
            self.emit("venom_bubbles", x, 0.055, z, size=S, dur=dt, col=VENOM_BUB, mode="flat", fade_in=0.0, alpha=0.95 * k, add=False,
                      rot=spin)
            self.emit("venom_rim", x, 0.06, z, size=S, dur=dt, col=VENOM_RIM, mode="flat", fade_in=0.0, alpha=1.0 * k, add=False)
            for _ in range(self.rate(5 * radius / 2.5)):          # 가끔 튀어 오르는 독방울
                a = rr(0, math.tau)
                d = radius * math.sqrt(rr(0.0, 1.0)) * 0.85
                self.emit("glow", x + math.cos(a) * d, 0.1, z + math.sin(a) * d, size=rr(0.16, 0.3), size_to=0.05,
                          dur=rr(0.5, 0.9), col=VENOM_P, vel=(0, rr(0.9, 1.6), 0), grav=-2.0, alpha=0.9 * fade, fade_pow=1.0)
        finally:
            self.clear_ctx()

    def fx_lunge(self, kind, ev):                             # 돌진: 노려보는 동안 예고선, 그 길로 쏜살같이 지나간다
        if ev.get("style") == "wraith":
            return self.wraith_step(ev)
        x, z, x2, z2 = ev["x"], ev["z"], ev["x2"], ev["z2"]
        dx, dz = x2 - x, z2 - z
        dist = max(0.5, math.hypot(dx, dz))
        rot = math.atan2(dx, dz)
        w = ev.get("w", 1.8)
        delay = ev.get("delay", 0.4)
        dur = max(0.1, ev.get("dur", 0.3))
        self.emit("streak", x, 0.08, z, size=(w, dist), dur=delay + 0.05, col=PALE, mode="flat", rot=rot, pivot=0.5, alpha=0.4,
                  fade_in=0.05, fade_pow=0.5)
        self.emit("glow", x, 0.1, z, size=w * 2.0, dur=delay + 0.1, col=TEAL, mode="flat")
        self.emit("streak", x, 0.2, z, size=(w * 0.9, dist + 1.5), dur=dur + 0.25, delay=delay, col=PALE, mode="flat", rot=rot,
                  pivot=0.5, alpha=0.65, fade_pow=1.2)
        for i in range(8):                                    # 지나간 자리에 먼지
            f = i / 7
            self.emit("dust", x + dx * f, 0.3, z + dz * f, size=0.8, size_to=1.7, dur=0.6, delay=delay + dur * f, col=(0.8, 0.78, 0.72),
                      alpha=0.5, add=False, vel=(rr(-0.4, 0.4), 0.5, rr(-0.4, 0.4)), fade_pow=1.4)

    def fx_bite(self, kind, ev):                              # 물어뜯기
        x, z = ev["x"], ev["z"]
        self.emit("claw", x, 1.0, z, size=1.8, dur=0.28, col=PALE, rot=rr(-0.6, 0.6))
        self.emit("glow", x, 0.9, z, size=1.6, dur=0.2, col=TEAL)
        self.burst("glow", x, 0.9, z, 6, 2.5, 0.3, 0.45, TOXIC, up=2.0, grav=-9)

    def fx_serpent_rear(self, kind, ev):                      # 내려찍기 준비: 몸을 쳐들며 물기운이 모인다
        x, z = ev["x"], ev["z"]
        self.shock(x, z, 1.6, TEAL, 0.45)
        self.emit("glow", x, 2.8, z, size=2.4, dur=max(0.3, ev.get("dur", 0.75)), col=TEAL, alpha=0.6)

    def fx_shockwave(self, kind, ev):                         # 내려찍기 충격파: 안쪽 원에서 바깥 원으로 퍼지는 고리
        x, z, r, r2 = ev["x"], ev["z"], ev.get("r", 2.0), ev.get("r2", 5.0)
        dur = max(0.2, ev.get("dur", 0.56))
        self.emit("ring", x, 0.12, z, size=r * 2.0, size_to=r2 * 2.1, dur=dur + 0.2, col=TEAL, mode="flat", fade_pow=1.1)
        self.emit("ring", x, 0.12, z, size=r * 1.6, size_to=r2 * 1.9, dur=dur + 0.3, delay=0.05, col=PALE, mode="flat", alpha=0.6)
        for i in range(10):
            a = i / 10 * math.tau + rr(-0.2, 0.2)
            sp = (r2 - r) / dur
            self.emit("dust", x + math.cos(a) * r, 0.3, z + math.sin(a) * r, size=0.8, size_to=1.6, dur=dur + 0.2,
                      col=(0.75, 0.85, 0.8), alpha=0.5, add=False, vel=(math.cos(a) * sp, 0.3, math.sin(a) * sp), fade_pow=1.4)

    def fx_dive(self, kind, ev):                              # 잠행: 머리부터 땅속으로 — 물이 튀고, 도착지엔 땅이 갈라진다
        x, z = ev["x"], ev["z"]
        sink = ev.get("sink", 0.6)
        self.emit("swirl", x, 0.1, z, size=3.2, size_to=1.2, dur=sink + 0.3, col=TEAL, mode="flat", spin=6.0)
        self.shock(x, z, 1.8, TEAL, 0.5)
        self.dust_ring(x, z, 1.4, 10)
        self.burst("glow", x, 0.3, z, 10, 2.5, 0.4, 0.6, TEAL, up=4.0, grav=-13)
        x2, z2, r = ev["x2"], ev["z2"], ev.get("r", 3.0)
        total = sink + ev.get("dur", 0.8)
        self.emit("crack", x2, 0.06, z2, size=r * 2.0, dur=total, col=TEAL, mode="flat", rot=rr(0, 6), alpha=0.7, fade_in=0.4,
                  fade_pow=0.4)

    def fx_dive_out(self, kind, ev):                          # 솟구침의 시작: 땅이 부풀며 번쩍 (나머지는 slam:dive 가 맡는다)
        self.emit("glow", ev["x"], 0.9, ev["z"], size=ev.get("r", 3.0) * 1.6, dur=0.3, col=TEAL)

    # ---- 용 --------------------------------------------------------------
    def spit_fire(self, ev):                                  # 화염 뱉기: 고개를 치켜든 용의 입에서 불덩이가 포물선을 그리며 날아간다
        x, z, x2, z2 = ev["x"], ev["z"], ev["x2"], ev["z2"]
        dx, dz = x2 - x, z2 - z
        dist = max(0.5, math.hypot(dx, dz))
        ux, uz = dx / dist, dz / dist
        delay = 0.3                                           # 고개를 치켜드는 동안은 입에서 아직 안 나간다
        T = max(0.25, ev.get("dur", 0.8) - delay)
        x0, y0, z0 = x + ux * 2.5, 2.1, z + uz * 2.5            # 들어 올린 머리의 입
        g = -16.0
        vx, vz = (x2 - x0) / T, (z2 - z0) / T
        vy = ((0.15 - y0) - 0.5 * g * T * T) / T
        with self.neutral():
            self.emit("glow", x0, y0, z0, size=0.9, size_to=2.4, dur=delay + 0.05, col=LAVA_HOT, alpha=0.8, fade_in=0.05)      # 입에 불이 모인다
            self.emit("glow", x0, y0, z0, size=2.0, dur=T, delay=delay, col=LAVA, vel=(vx, vy, vz), grav=g, fade_in=0.0, fade_pow=0.15)
            self.emit("glow", x0, y0, z0, size=1.0, dur=T, delay=delay, col=LAVA_HOT, vel=(vx, vy, vz), grav=g, fade_in=0.0, fade_pow=0.1)
            self.emit("flame", x0, y0 + 0.3, z0, size=(1.1, 1.6), dur=T, delay=delay, col=LAVA, col_to=LAVA_HOT, vel=(vx, vy, vz), grav=g,
                      fade_in=0.0, fade_pow=0.2)
            for i in range(14):                                   # 지나간 자리에 남는 불꽃 꼬리
                ti = T * (i + 0.5) / 14
                px, py, pz = x0 + vx * ti, y0 + vy * ti + 0.5 * g * ti * ti, z0 + vz * ti
                self.emit("flame" if i % 2 else "ember", px, py, pz, size=(0.7, 1.1) if i % 2 else 0.7, size_to=0.1, dur=0.45,
                          delay=delay + ti, col=LAVA, col_to=(0.9, 0.2, 0.05), alpha=0.8, fade_in=0.0, vel=(rr(-0.3, 0.3), rr(0.6, 1.4), rr(-0.3, 0.3)))
            self.burst("spark", x0, y0, z0, 6, 3.0, 0.3, 0.45, LAVA_HOT, up=1.5, grav=-9, delay=delay)

    def spit_land_fire(self, x, z, r):                        # 불덩이가 터진다
        self.shock(x, z, r * 1.2, LAVA_HOT, 0.45)             # 고리는 팀 색 (누구의 불인지 보이게)
        with self.neutral():
            self.emit("glow", x, 0.1, z, size=r * 2.4, dur=0.4, col=LAVA, mode="flat", alpha=0.7)
            self.emit("glow", x, 0.9, z, size=r * 1.3, dur=0.25, col=LAVA_HOT, alpha=0.7)
            for _ in range(7):
                a, d = rr(0, math.tau), r * rr(0.0, 0.8)
                self.emit("flame", x + math.cos(a) * d, 0.2, z + math.sin(a) * d, size=(rr(0.8, 1.3), rr(1.5, 2.4)), dur=rr(0.5, 0.8),
                          col=LAVA, col_to=(1.0, 0.8, 0.3), vel=(math.cos(a) * 1.2, rr(2.0, 4.0), math.sin(a) * 1.2), fade_pow=0.9)
            self.burst("spark", x, 0.5, z, 10, r * 2.2, 0.4, 0.6, LAVA_HOT, up=5.0, grav=-14)
            self.stones(x, z, r, 4, col=(0.3, 0.12, 0.06), dur=0.7)

    def fire_zone(self, x, z, radius, ally, left, total):
        """불길 웅덩이: 그을린 바닥 + 용암빛 균열 + 일렁이는 테두리 + 피어오르는 불꽃. 팀과 상관없이 불 색이고, 사라지기 직전 1.6초는 깜빡인다."""
        dt = self.dt * 1.4 + 0.001
        grow = min(1.0, (total - left) / 0.22) if total > 0 else 1.0
        grow = 0.55 + 0.45 * (1 - (1 - grow) ** 3)
        fade = min(1.0, left / 1.2) * min(1.0, max(0.05, (total - left) / 0.22))
        warn = 0.6 + 0.4 * math.sin(self.now * 18) if left < 1.6 else 1.0
        k = fade * warn
        S = radius * 2.1 * grow
        pulse = 0.75 + 0.25 * math.sin(self.now * 3.0 + x * 1.3 + z)
        spin = x * 1.7 + z * 0.9
        self.ctx(None, False)
        try:
            self.emit("venom_disc", x, 0.05, z, size=S, dur=dt, col=SCORCH, mode="flat", fade_in=0.0, alpha=0.93 * k, add=False)
            self.emit("glow", x, 0.055, z, size=S * 0.95, dur=dt, col=(0.6, 0.16, 0.04), mode="flat", fade_in=0.0, alpha=0.5 * pulse * k)
            self.emit("magma_cracks", x, 0.06, z, size=S, dur=dt, col=LAVA, mode="flat", fade_in=0.0, alpha=pulse * k, rot=spin)
            self.emit("venom_rim", x, 0.065, z, size=S, dur=dt, col=LAVA_RIM, mode="flat", fade_in=0.0, alpha=0.95 * k, add=False)
            for _ in range(self.rate(9 * radius / 2.0)):          # 바닥에서 올라오는 불꽃
                a = rr(0, math.tau)
                d = radius * math.sqrt(rr(0.0, 1.0)) * 0.9
                self.emit("flame", x + math.cos(a) * d, 0.1, z + math.sin(a) * d, size=(rr(0.45, 0.8), rr(0.9, 1.5)),
                          size_to=(0.1, 0.25), dur=rr(0.5, 0.9), col=LAVA, col_to=(0.9, 0.18, 0.04), alpha=0.9 * fade,
                          vel=(rr(-0.15, 0.15), rr(0.9, 1.7), rr(-0.15, 0.15)), fade_pow=0.9)
            for _ in range(self.rate(3.0 * radius / 2.0)):        # 튀는 불똥
                a = rr(0, math.tau)
                d = radius * math.sqrt(rr(0.0, 1.0)) * 0.9
                self.emit("ember", x + math.cos(a) * d, 0.2, z + math.sin(a) * d, size=rr(0.14, 0.26), size_to=0.04, dur=rr(0.6, 1.1),
                          col=LAVA_HOT, vel=(rr(-0.5, 0.5), rr(1.5, 3.0), rr(-0.5, 0.5)), grav=-2.5, alpha=0.9 * fade)
        finally:
            self.clear_ctx()

    def fx_wing_wind(self, kind, ev):                         # 날개 후려치기 준비: 날개를 뒤로 젖히는 동안 바람이 감겨 든다
        x, z, r = ev["x"], ev["z"], ev.get("r", 3.6)
        delay = max(0.1, ev.get("delay", 0.45))
        self.emit("ring", x, 0.1, z, size=r * 2.6, size_to=r * 2.0, dur=delay + 0.05, col=LAVA_RIM, mode="flat", alpha=0.55, fade_in=0.05,
                  fade_pow=0.4)
        for i in range(10):
            b = rr(0, math.tau)
            d = r * rr(0.8, 1.3)
            self.emit("dust", x + math.cos(b) * d, 0.3, z + math.sin(b) * d, size=0.8, size_to=0.3, dur=delay, col=(0.85, 0.8, 0.72),
                      alpha=0.5, add=False, vel=(-math.cos(b) * d / delay * 0.8, 0.4, -math.sin(b) * d / delay * 0.8), fade_pow=1.2)

    def fx_gust_wind(self, kind, ev):                         # 날개 폭풍 준비: 날개를 치켜드는 동안 부채꼴 예고 + 바람이 모인다
        x, z, r, a = ev["x"], ev["z"], ev.get("r", 6.5), ev["a"]
        rot = facing_to_rot(a)
        delay = max(0.1, ev.get("delay", 0.35))
        h = r / 0.74
        self.emit("wave", x, 0.1, z, size=(h * 1.05, h), dur=delay + 0.05, col=WIND, mode="flat", rot=rot, pivot=0.45, alpha=0.45,
                  fade_in=0.05, fade_pow=0.4)
        self.emit("glow", x, 0.1, z, size=3.0, dur=delay, col=LAVA, mode="flat", alpha=0.5)
        for i in range(8):                                    # 몸쪽으로 빨려드는 먼지
            b = rot + rr(-0.9, 0.9)
            d = rr(2.0, 3.4)
            self.emit("dust", x + math.sin(b) * d, 0.3, z + math.cos(b) * d, size=0.8, size_to=0.3, dur=delay,
                      col=(0.85, 0.8, 0.72), alpha=0.5, add=False, vel=(-math.sin(b) * d / delay, 0.4, -math.cos(b) * d / delay),
                      fade_pow=1.2)

    def fx_gust(self, kind, ev):                              # 날개 폭풍: 부채꼴로 쏟아지는 뜨거운 바람
        x, z, r, a = ev["x"], ev["z"], ev.get("r", 6.5), ev["a"]
        rot = facing_to_rot(a)
        fx_, fz_ = math.sin(rot), math.cos(rot)
        half = math.radians(ev.get("w", 100)) / 2
        h = r / 0.74
        for k in range(4):                                    # 바깥으로 퍼지는 바람 물결
            self.emit("wave", x, 0.2 + k * 0.01, z, size=(h * 1.05, h * 0.9), size_to=(h * 1.35, h * 1.15), dur=0.45, delay=k * 0.06,
                      col=WIND, mode="flat", rot=rot, vel=(fx_ * 5, 0, fz_ * 5), pivot=0.45, fade_pow=0.9)
        for i in range(16):                                   # 부채꼴을 가르는 바람줄
            b = rot + rr(-half, half) * 0.9
            sp = rr(14, 22)
            d0 = rr(1.2, 2.5)
            self.emit("streak", x + math.sin(b) * d0, 0.4 + rr(0, 1.4), z + math.cos(b) * d0, size=(0.3, rr(2.2, 3.6)), dur=rr(0.28, 0.42),
                      delay=rr(0, 0.12), col=WIND, mode="flat", rot=b + math.pi, pivot=-0.5, alpha=0.7,
                      vel=(math.sin(b) * sp, 0, math.cos(b) * sp), fade_pow=0.9)
        for i in range(10):                                   # 휩쓸려 나가는 먼지와 불똥
            b = rot + rr(-half, half) * 0.9
            sp = rr(7, 13)
            self.emit("dust", x + fx_ * 1.5, 0.3, z + fz_ * 1.5, size=0.9, size_to=1.8, dur=0.7, col=(0.85, 0.8, 0.72), alpha=0.5, add=False,
                      vel=(math.sin(b) * sp, 0.5, math.cos(b) * sp), fade_pow=1.4)
        for i in range(8):
            b = rot + rr(-half, half) * 0.9
            sp = rr(8, 15)
            self.emit("ember", x + fx_ * 1.5, rr(0.6, 1.8), z + fz_ * 1.5, size=rr(0.15, 0.3), size_to=0.04, dur=rr(0.4, 0.7), col=LAVA_HOT,
                      vel=(math.sin(b) * sp, rr(0.0, 1.5), math.cos(b) * sp), alpha=0.9)

    def tornado_trail(self, x, z, dx, dz):                    # 회오리가 굴러가며 흩날리는 바람 입자와 먼지
        c = (0.87, 0.92, 1.0)
        for _ in range(self.rate(16)):
            a = rr(0, math.tau)
            h = rr(0.0, 2.6)
            rad = 0.35 + h * 0.42
            self.emit("spark", x + math.cos(a) * rad, 0.2 + h, z + math.sin(a) * rad, size=rr(0.2, 0.4), dur=0.4, col=c,
                      vel=(-math.sin(a) * 4 - dx * 2, rr(0.0, 1.0), math.cos(a) * 4 - dz * 2), fade_pow=1.0, alpha=0.8)
        for _ in range(self.rate(5)):
            a = rr(0, math.tau)
            self.emit("dust", x + math.cos(a) * 0.9, 0.2, z + math.sin(a) * 0.9, size=0.6, size_to=1.4, dur=0.6, col=(0.7, 0.62, 0.52),
                      alpha=0.45, add=False, vel=(-dx * 1.5, 0.5, -dz * 1.5), fade_pow=1.3)

    def fx_burn(self, kind, ev):                              # 급강하 불길에 닿은 적: 불꽃이 확 인다
        x, z = ev["x"], ev["z"]
        with self.neutral():
            self.emit("glow", x, 1.0, z, size=2.2, dur=0.3, col=LAVA)
            for _ in range(3):
                self.emit("flame", x + rr(-0.4, 0.4), 0.4, z + rr(-0.4, 0.4), size=(rr(0.7, 1.0), rr(1.4, 2.0)), dur=rr(0.4, 0.7),
                          col=LAVA, col_to=LAVA_HOT, vel=(rr(-1, 1), rr(2, 4), rr(-1, 1)), fade_pow=0.9)
            self.burst("ember", x, 1.0, z, 6, 3.0, 0.2, 0.5, LAVA_HOT, up=2.0, grav=-6)

    def fx_sky_dive(self, kind, ev):
        """R 불꽃 비행: 떠오를 때 발밑에서 불길이 치솟고, 땅에는 지나갈 길(일자)과 착지 원이 표시되며,
        높이 뜬 채 수평으로 날아가는 동안 입에서 아래로 불줄기를 쏟는다 (마지막에 내려앉는다)."""
        x, z, x2, z2 = ev["x"], ev["z"], ev["x2"], ev["z2"]
        rise, dur, h, R, w = ev.get("rise", 1.0), ev.get("dur", 1.0), ev.get("h", 6.5), ev.get("r", 3.2), ev.get("w", 5.0)
        dx, dz = x2 - x, z2 - z
        dist = max(0.5, math.hypot(dx, dz))
        ux, uz = dx / dist, dz / dist
        rot = math.atan2(dx, dz)
        self.shock(x, z, 2.6, LAVA_HOT, 0.6)
        self.dust_ring(x, z, 2.0, 12)
        with self.neutral():
            self.emit("glow", x2, 0.1, z2, size=R * 2.0, dur=rise + dur, col=LAVA, mode="flat", alpha=0.4, fade_in=0.4, fade_pow=0.5)
            self.emit("glow", x, 0.3, z, size=4.0, dur=0.5, col=LAVA, mode="flat", alpha=0.7)
            for i in range(8):                                    # 솟구치는 동안 발밑에서 불길
                tt = rise * i / 8
                self.emit("flame", x + rr(-0.6, 0.6), 0.3, z + rr(-0.6, 0.6), size=(rr(0.9, 1.3), rr(1.6, 2.4)), dur=0.5, delay=tt,
                          col=LAVA, col_to=LAVA_HOT, vel=(rr(-1, 1), rr(1, 3), rr(-1, 1)), fade_pow=0.9)
            n = max(8, int(dur * 24))
            half = w * 0.5
            for i in range(n):                                    # 수평 비행: 입에서 아래로, 바깥 바 폭 가득 불줄기를 흩뿌린다
                u = i / (n - 1)
                tt = rise + u * dur
                air = h if u < 0.8 else h * (1 - _smooth01((u - 0.8) / 0.2))
                px, pz = x + dx * u + ux * 1.7, z + dz * u + uz * 1.7             # 몸보다 앞선 입
                py = air + 1.0
                for k in range(9):                                # 입에서 옆으로 퍼지며 떨어지는 불줄기
                    side = rr(-half, half)
                    fx_, fz_ = px - uz * side, pz + ux * side
                    top = py * rr(0.55, 1.0)
                    self.emit("flame", px, top, pz, size=(rr(0.8, 1.3), rr(1.4, 2.3)), size_to=0.3, dur=rr(0.4, 0.6), delay=tt,
                              col=LAVA, col_to=(0.9, 0.25, 0.05), vel=((fx_ - px) / 0.45 + ux * 3, -(top - 0.3) / 0.45, (fz_ - pz) / 0.45 + uz * 3),
                              fade_in=0.0, alpha=0.85)
                for k in range(3):                                # 땅에 닿아 번지는 불길
                    side = rr(-half, half)
                    gx_, gz_ = px - uz * side, pz + ux * side
                    self.emit("flame", gx_, 0.3, gz_, size=(rr(0.9, 1.4), rr(1.6, 2.4)), dur=rr(0.4, 0.7), delay=tt + 0.35,
                              col=LAVA, col_to=LAVA_HOT, vel=(0, rr(1.5, 3.5), 0), fade_in=0.0, alpha=0.8)
                self.emit("glow", px, py, pz, size=2.4, dur=0.3, delay=tt, col=LAVA_HOT, fade_in=0.0, alpha=0.7)
                self.emit("glow", px - uz * 0, 0.15, pz, size=w * 0.9, dur=0.6, delay=tt + 0.3, col=LAVA, mode="flat", fade_in=0.0, alpha=0.4)
                for k in range(2):
                    side = rr(-half, half)
                    self.emit("ember", px - uz * side, 0.3, pz + ux * side, size=0.3, size_to=0.05, dur=0.9, delay=tt + 0.35, col=LAVA_HOT,
                              vel=(rr(-1, 1), rr(1.5, 4), rr(-1, 1)), grav=-4)

    # ---- 그 밖의 효과 ----------------------------------------------------
    def fx_wallhit(self, kind, ev):
        x, z = ev["x"], ev["z"]
        self.emit("crack", x, 0.06, z, size=2.0, dur=0.6, col=EARTH, mode="flat", rot=rr(0, 6))
        self.dust_ring(x, z, 0.8, 6)
        self.emit("spark", x, 0.8, z, size=1.4, dur=0.2, col=PALE)

    def fx_flash(self, kind, ev):
        for key, big in ((("x", "z"), 1.0), (("x2", "z2"), 1.3)):
            x, z = ev[key[0]], ev[key[1]]
            self.emit("spark", x, 1.0, z, size=2.2 * big, dur=0.3, col=GOLD)
            self.emit("ring", x, 0.12, z, size=0.6, size_to=2.0 * big, dur=0.4, col=GOLD, mode="flat")
            self.burst("spark", x, 1.0, z, 5, 2.5, 0.3, 0.4, PALE, up=1.0)

    def fx_recall(self, kind, ev):
        for key in (("x", "z"), ("x2", "z2")):
            x, z = ev[key[0]], ev[key[1]]
            self.pillar(x, z, GHOST, 9.0, 1.2, 0.7)
            self.emit("ring", x, 0.12, z, size=0.8, size_to=2.6, dur=0.7, col=GHOST, mode="flat")
            self.burst("spark", x, 0.5, z, 6, 1.4, 0.35, 0.8, PALE, up=3.0)

    def fx_spell(self, kind, ev):
        """소환사 주문 (회복 / 유체화 / 방어막 / 정화 / 탈진 / 점화)."""
        x, z = ev["x"], ev["z"]
        style = ev.get("style")
        if style == "heal":
            self.fx_heal("heal", ev)
        elif style == "cleanse":
            self.fx_cleanse("cleanse", ev)
        elif style == "ghost":
            self.emit("swirl", x, 0.12, z, size=3.2, size_to=1.4, dur=0.9, col=GHOST, mode="flat", spin=8.0)
            self.burst("glow", x, 1.0, z, 6, 1.6, 0.6, 0.7, GHOST, up=1.5, size_to=0.1)
        elif style == "barrier":
            self.emit("hex", x, 1.15, z, size=3.0, size_to=3.5, dur=0.9, col=BRONZE, fade_in=0.05)
            self.emit("ring", x, 0.1, z, size=1.6, size_to=3.0, dur=0.6, col=BRONZE, mode="flat")
        elif style == "exhaust":                              # 탈진: 무거운 기운이 짓누른다
            self.emit("swirl", x, 0.12, z, size=3.0, size_to=1.2, dur=1.0, col=SOUL, mode="flat", spin=-5.0)
            for i in range(6):
                a = rr(0, math.tau)
                self.emit("drop", x + math.cos(a) * 0.5, 2.2, z + math.sin(a) * 0.5, size=(0.3, 0.45), dur=0.9,
                          delay=i * 0.06, col=SOUL, vel=(0, -2.0, 0), fade_pow=0.8)
        elif style == "ignite":                               # 점화: 불길
            for i in range(9):
                a = rr(0, math.tau)
                d = rr(0.1, 0.8)
                self.emit("flame", x + math.cos(a) * d, 0.3, z + math.sin(a) * d, size=(rr(0.6, 1.0), rr(1.1, 1.8)),
                          dur=rr(0.5, 0.9), delay=i * 0.04, col=FIRE, col_to=GOLD, vel=(0, rr(1.5, 3.0), 0))
            self.emit("glow", x, 1.0, z, size=2.8, dur=0.4, col=FIRE)
        else:
            return

    # ---- 망령 사신 --------------------------------------------------------
    def fx_reap_wind(self, kind, ev):                         # 영혼 베기 준비: 부채꼴 예고 + 젖힌 낫 끝으로 영혼이 빨려 든다
        x, z, r = ev["x"], ev["z"], ev.get("r", 4.0)
        rot = facing_to_rot(ev["a"])
        delay = max(0.1, ev.get("delay", 0.3))
        h = r / 0.74
        self.emit("wave", x, 0.1, z, size=(h * 1.05, h), dur=delay + 0.05, col=REAP, mode="flat", rot=rot, pivot=0.45, alpha=0.4,
                  fade_in=0.05, fade_pow=0.4)
        bx, bz = x + math.sin(rot + 2.4) * 1.6, z + math.cos(rot + 2.4) * 1.6
        self.emit("glow", bx, 1.4, bz, size=0.6, size_to=1.6, dur=delay, col=REAP_SOUL, alpha=0.8)
        for i in range(9):
            b_ = rr(0, math.tau)
            d = rr(1.2, 2.2)
            self.emit("glow", bx + math.cos(b_) * d, rr(0.6, 2.0), bz + math.sin(b_) * d, size=rr(0.25, 0.45), size_to=0.08, dur=delay,
                      col=REAP, vel=(-math.cos(b_) * d / delay, 0.0, -math.sin(b_) * d / delay), fade_pow=0.6)

    def fx_reap_sweep(self, kind, ev):                        # 영혼 베기: 반원을 휩쓰는 낫 자국, 날끝을 따라 흩어지는 영혼
        x, z, r = ev["x"], ev["z"], ev.get("r", 4.0)
        rot = facing_to_rot(ev["a"])
        half = math.radians(ev.get("w", 160)) / 2
        sweep = 0.2
        for k in range(2):
            self.emit("slash", x, 0.95 + k * 0.02, z, size=r * 1.7, dur=0.24, delay=k * 0.03, col=REAP, mode="flat", alpha=0.75 - 0.25 * k,
                      rot=rot + half * 0.85, spin=-(2 * half * 0.85) / sweep, pivot=0.22, fade_pow=1.2, fade_in=0.02)
        self.emit("arc", x, 1.0, z, size=r * 1.8, dur=0.22, col=REAP_SOUL, mode="flat", rot=rot + half * 0.85, alpha=0.8,
                  spin=-(2 * half * 0.85) / sweep, pivot=0.26, fade_pow=1.2)
        for i in range(14):
            b_ = rot + half * 0.85 - (2 * half * 0.85) * i / 13
            d = r * rr(0.75, 0.95)
            self.emit("glow", x + math.sin(b_) * d, rr(0.6, 1.3), z + math.cos(b_) * d, size=rr(0.3, 0.55), size_to=0.05, dur=rr(0.4, 0.7),
                      delay=sweep * i / 13, col=REAP, vel=(math.sin(b_) * 1.5, rr(0.6, 1.8), math.cos(b_) * 1.5), fade_pow=0.8)

    def fx_reap_edge(self, kind, ev):                         # 날끝에 베인 적: 영혼이 뜯겨 나온다
        x, z = ev["x"], ev["z"]
        self.emit("claw", x, 1.0, z, size=1.7, dur=0.26, col=REAP_HOT, rot=rr(-0.6, 0.6))
        self.burst("glow", x, 1.1, z, 6, 2.2, 0.3, 0.5, REAP_SOUL, up=2.2, size_to=0.05)

    def fx_scythe_throw(self, kind, ev):                      # 낫 던지기: 손을 떠나는 순간의 회오리 빛
        x, z = ev["x"], ev["z"]
        self.emit("swirl", x, 1.2, z, size=1.4, size_to=2.6, dur=0.35, col=REAP, spin=-14.0, fade_pow=1.0)

    def fx_scythe_catch(self, kind, ev):                      # 돌아온 낫을 받아 쥔다
        x, z = ev["x"], ev["z"]
        self.emit("glow", x, 1.2, z, size=1.6, dur=0.25, col=REAP_SOUL, alpha=0.7)
        self.burst("spark", x, 1.2, z, 5, 2.0, 0.25, 0.35, REAP_HOT, up=1.0)

    def wraith_step(self, ev):                                # 망령 걸음: 반투명한 잔상이 길을 따라 늘어서고 영혼 불꽃이 흩날린다
        x, z, x2, z2 = ev["x"], ev["z"], ev["x2"], ev["z2"]
        dx, dz = x2 - x, z2 - z
        dist = max(0.5, math.hypot(dx, dz))
        rot = math.atan2(dx, dz)
        w = ev.get("w", 1.6)
        delay = ev.get("delay", 0.05)
        dur = max(0.1, ev.get("dur", 0.2))
        self.emit("swirl", x, 0.12, z, size=2.6, size_to=1.0, dur=0.45, col=REAP, mode="flat", spin=9.0, alpha=0.8)
        self.emit("streak", x, 0.15, z, size=(w * 0.8, dist + 1.2), dur=dur + 0.5, delay=delay, col=REAP, mode="flat", rot=rot, pivot=0.5,
                  alpha=0.55, fade_pow=1.0)
        for i in range(9):
            f = i / 8
            px, pz = x + dx * f, z + dz * f
            self.emit("glow", px, 1.0, pz, size=1.6, size_to=0.6, dur=0.5, delay=delay + dur * f, col=REAP, alpha=0.45, fade_pow=1.2)
            self.emit("glow", px + rr(-0.4, 0.4), rr(0.3, 1.4), pz + rr(-0.4, 0.4), size=rr(0.3, 0.5), size_to=0.05, dur=rr(0.5, 0.8),
                      delay=delay + dur * f, col=REAP_SOUL, vel=(rr(-0.4, 0.4), rr(1.0, 2.0), rr(-0.4, 0.4)), fade_pow=0.8)

    def fx_soul_rend(self, kind, ev):                         # 망령 걸음에 스친 적
        x, z = ev["x"], ev["z"]
        self.emit("claw", x, 1.0, z, size=1.5, dur=0.25, col=REAP, rot=rr(-0.6, 0.6))
        self.burst("glow", x, 1.0, z, 5, 2.0, 0.28, 0.45, REAP_SOUL, up=1.8, size_to=0.05)

    def fx_reap(self, kind, ev):                              # 사형 선고 준비: 대상 발밑에 영혼이 소용돌이친다
        x2, z2, r = ev.get("x2", ev["x"]), ev.get("z2", ev["z"]), ev.get("r", 1.8)
        dur = max(0.2, ev.get("dur", 0.8))
        self.emit("swirl", x2, 0.12, z2, size=r * 2.8, size_to=r * 1.6, dur=dur, col=REAP, mode="flat", spin=4.0, alpha=0.7, fade_in=0.1,
                  fade_pow=0.5)
        for i in range(10):
            b_ = rr(0, math.tau)
            self.emit("glow", x2 + math.cos(b_) * r, 0.2, z2 + math.sin(b_) * r, size=rr(0.3, 0.5), size_to=0.1, dur=dur * rr(0.6, 1.0),
                      delay=rr(0, dur * 0.3), col=REAP_SOUL, vel=(0, rr(2.0, 3.5), 0), fade_pow=0.8)
        self.emit("glow", ev["x"], 2.4, ev["z"], size=1.0, size_to=2.4, dur=dur, col=REAP_SOUL, alpha=0.6)

    def fx_reap_strike(self, kind, ev):                       # 사형 선고: 하늘에서 거대한 영혼의 낫이 내리꽂힌다
        x, z, r = ev["x"], ev["z"], ev.get("r", 1.8)
        self.emit("slash", x, 2.6, z, size=(r * 3.2, r * 3.6), dur=0.28, col=REAP_HOT, rot=0.9, spin=-9.0, fade_in=0.0, fade_pow=0.9)
        self.emit("beam", x, 3.5, z, size=(1.2, 7.0), size_to=(0.3, 7.0), dur=0.4, col=REAP_SOUL, fade_in=0.02)
        self.emit("crack", x, 0.06, z, size=r * 2.8, dur=1.2, col=REAP, mode="flat", rot=rr(0, 6), fade_pow=0.8)
        self.emit("glow", x, 0.1, z, size=r * 2.6, dur=0.35, col=REAP, mode="flat")
        self.shock(x, z, r, REAP_HOT, 0.45)
        self.shock(x, z, r * 1.6, REAP, 0.6, 0.06)
        self.burst("glow", x, 0.6, z, 12, r * 2.2, 0.4, 0.7, REAP_SOUL, up=4.0, grav=-6, size_to=0.05)

    def fx_reap_soul(self, kind, ev):                         # 사형 선고로 처치: 영혼이 빠져나와 위로 흩어진다
        x, z = ev["x"], ev["z"]
        self.emit("glow", x, 1.0, z, size=1.2, size_to=2.8, dur=0.9, col=REAP_SOUL, vel=(0, 2.5, 0), fade_pow=0.8)
        self.emit("ring", x, 0.12, z, size=1.0, size_to=4.0, dur=0.6, col=REAP_HOT, mode="flat")

    # ============================================================== 시전(cast) 연출 (서버 이펙트가 없는 스킬)
    def cast(self, champ, slot, x, z, facing):
        """스킬을 쓰는 순간 시전자에게 붙는 이펙트. champ: 챔피언 id."""
        rot = facing_to_rot(facing)
        fx_, fz_ = math.sin(rot), math.cos(rot)
        if champ == "spider" and slot == "W":               # 거미줄 장판: 입에서 하얀 빛이 모인다
            self.emit("glow", x + fx_ * 0.9, 0.9, z + fz_ * 0.9, size=2.0, dur=0.3, col=CREAM)
            self.emit("web", x, 0.1, z, size=1.0, size_to=2.4, dur=0.45, col=CREAM, mode="flat", rot=rr(0, 6), fade_pow=1.2)
        elif champ == "spider" and slot == "E":               # 고치: 배 끝에서 누런 빛
            self.emit("glow", x - fx_ * 0.8, 0.9, z - fz_ * 0.8, size=2.0, dur=0.4, col=CREAM)
        elif champ == "spider" and slot == "R":               # 점프: 다리를 웅크리며 먼지
            self.dust_ring(x, z, 1.1, 6)
        elif champ == "serpent" and slot == "Q":              # 독 뱉기: 머리를 쳐들며 입에 독이 고인다
            self.emit("glow", x + fx_ * 0.9, 1.3, z + fz_ * 0.9, size=1.8, dur=0.35, col=TOXIC)
        elif champ == "dragon" and slot == "Q":               # 화염 뱉기: 입에 불이 고인다 (불덩이는 spit 이벤트가 맡는다)
            self.emit("glow", x + fx_ * 1.6, 1.8, z + fz_ * 1.6, size=1.2, size_to=2.2, dur=0.3, col=LAVA_HOT)
        elif champ == "dragon" and slot == "W":               # 회오리: 날개를 치켜들며 먼지
            self.dust_ring(x, z, 1.4, 8)


    # ============================================================== 날아가는 투사체
    TRAIL = {
        #  종류: (꼬리 그림, 길이, 폭, 꼬리 색, 빛 색, 빛 크기, 입자 그림 (또는 None), 초당 입자 수)
        "arrow": ("streak", 2.4, 0.30, STEEL, STEEL, 0.0, "spark", 6),
        "snowball": ("streak", 1.4, 0.45, PALE, (0.7, 0.85, 1.0), 1.1, "spark", 10),
        "fire_bolt": ("streak", 1.3, 0.35, LAVA, LAVA_HOT, 1.1, "ember", 14),
        "web": ("streak", 2.2, 0.55, CREAM, CREAM, 1.3, "spark", 8),
        "web_shot": ("streak", 1.3, 0.3, CREAM, CREAM, 0.7, "spark", 3),
        "baby_shot": ("streak", 0.6, 0.12, CREAM, CREAM, 0.3, "spark", 2),
        "spine": ("streak", 1.7, 0.22, POISON, POISON, 0.6, "spark", 4),
        "turret_shot": ("glow", 0.5, 0.5, (1.0, 0.8, 0.4), (1.0, 0.8, 0.4), 1.2, "ember", 22),
        "turret_shot_2": ("glow", 0.5, 0.5, (1.0, 0.55, 0.3), (1.0, 0.55, 0.3), 1.6, "ember", 32),     # 연속 공격 중: 붉고 불씨가 많다
        "turret_shot_3": ("glow", 0.5, 0.5, (1.0, 0.3, 0.2), (1.0, 0.3, 0.2), 2.2, "ember", 46),   # 뾰족한 꼬리 대신 둥근 빛 + 뒤로 남는 입자 경로
        "scythe": ("", 0.0, 0.0, REAP, REAP_SOUL, 1.4, "spark", 16),
        "minion_bolt": ("streak", 1.0, 0.25, PALE, PALE, 0.7, None, 0),
        "cannon_ball": ("streak", 1.2, 0.4, (0.8, 0.8, 0.85), (0.8, 0.8, 0.85), 0.0, None, 0),
    }

    def projectile(self, p, x, y, z, ally, team_tint=True):
        """날아가는 투사체 하나의 꼬리와 빛, 흩날리는 입자. 매 프레임 부른다."""
        if p["style"] == "tornado":
            self.ctx(None, False)
            try:
                self.tornado_trail(x, z, p["dx"], p["dz"])
            finally:
                self.clear_ctx()
            return
        spec = self.TRAIL.get(p["style"])
        if spec is None:
            return
        name, ln, wd, tcol, gcol, gsize, part, prate = spec
        champion = p["style"] not in ("minion_bolt", "cannon_ball", "fire_bolt", "tornado")      # 포탑 투사체도 팀 색
        self.ctx(ally if champion else None, False)
        try:
            dx, dz = p["dx"], p["dz"]
            rot = math.atan2(dx, dz)
            if p["style"].startswith("turret_shot"):                    # 포탑: 구 앞쪽엔 빛 없이 뒤 경로 입자만
                name, gsize = None, 0
            if name:
              self.emit(name, x, y, z, size=(wd, ln), dur=self.dt * 1.4 + 0.001, col=tcol, mode="flat", rot=rot + math.pi,
                        pivot=-0.5, fade_in=0.0, alpha=0.85)
            if gsize > 0:
                self.emit("glow", x, y, z, size=gsize, dur=self.dt * 1.4 + 0.001, col=gcol, fade_in=0.0, alpha=0.8)
            if part:
                for _ in range(self.rate(prate)):
                    jx, jz = rr(-0.25, 0.25), rr(-0.25, 0.25)
                    if part == "ember":                         # 둥근 불씨가 뒤로 흩어진다
                        self.emit("glow", x + jx - dx * 0.4, y, z + jz - dz * 0.4, size=rr(0.22, 0.42), dur=0.45, col=tcol,
                                  vel=(jx * 0.5, rr(-0.2, 0.3), jz * 0.5), fade_pow=1.0)
                    else:
                        sk = 0.45 if p["style"] == "baby_shot" else 1.0
                        self.emit("spark", x + jx * sk - dx * 0.3, y, z + jz * sk - dz * 0.3, size=rr(0.25, 0.5) * sk, dur=0.35, col=tcol,
                                  vel=(jx, rr(-0.3, 0.8), jz), fade_pow=1.0)
        finally:
            self.clear_ctx()

    # ============================================================== 챔피언에 붙어 있는 상태 표시
    def status(self, st, x, z, lift, ally, is_shield):
        """상태가 이어지는 동안 몸 주변에 흐르는 입자. 매 프레임 부른다."""
        self.ctx(ally, False)
        try:
            if "ghost" in st:                                 # 망령: 영혼 불꽃
                for _ in range(self.rate(9)):
                    a = rr(0, math.tau)
                    self.emit("glow", x + math.cos(a) * 0.5, 0.4 + lift, z + math.sin(a) * 0.5, size=rr(0.4, 0.7), dur=0.9,
                              col=GHOST, vel=(0, rr(0.8, 1.6), 0), fade_pow=0.8, alpha=0.7)
            if "ignite" in st:                                # 점화: 불꽃
                for _ in range(self.rate(10)):
                    a = rr(0, math.tau)
                    self.emit("flame", x + math.cos(a) * 0.4, 0.3 + lift, z + math.sin(a) * 0.4, size=(0.4, 0.7), dur=0.6,
                              col=FIRE, col_to=GOLD, vel=(0, rr(1.0, 2.2), 0))
            if "exhaust" in st and _rnd.random() < self.dt * 3.0:     # 탈진: 늘어지는 보랏빛 방울
                self.emit("drop", x + rr(-0.4, 0.4), 2.1 + lift, z + rr(-0.4, 0.4), size=(0.22, 0.32), dur=0.8, col=SOUL,
                          vel=(0, -1.6, 0), fade_pow=0.8)
            if is_shield:                                     # 보호막: 도는 꽃잎 / 반짝이는 막
                if _rnd.random() < self.dt * 5.0:
                    a = rr(0, math.tau)
                    self.emit("petal", x, 0.6 + lift, z, size=(0.3, 0.5), dur=1.0, col=(0.8, 0.9, 1.0),
                              orbit=(x, z, 1.0, 1.0, a, 4.0, 0.7), rot=a, spin=2.0, fade_pow=0.8, alpha=0.7)
        finally:
            self.clear_ctx()
