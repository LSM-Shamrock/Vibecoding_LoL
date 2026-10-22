"""미니언·새끼 거미·고치·포탑·억제기·넥서스 초상화 생성 (유닛 정보창 왼쪽 위 원).
게임의 3D 모델을 렌더링해 assets/ui/portraits/units/<이름>_<팀>.png (팀 0 파랑 / 1 빨강, 고치는 팀 없음) 로 저장한다.
사용: python tools/build_unit_portraits.py   (창이 잠깐 뜬다. 모델을 바꾼 뒤 다시 실행하면 초상화도 갱신된다.)
"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import numpy as np
import pygame
from PIL import Image

from game.client.app import App
from game.client.gl import facing_to_rot, model_matrix

OUT = os.path.join(ROOT, "assets", "ui", "portraits", "units")
SIZE = 128
# 구도: 모델 높이에 대한 카메라가 보는 높이(fy)와 거리(fd), 내려다보는 각도(pitch), 좌우 회전(yaw)
FRAMING = {"minion_melee": {"fy": 0.6, "fd": 1.6}, "minion_caster": {"fy": 0.62, "fd": 1.5},
           "minion_cannon": {"fy": 0.5, "fd": 1.7, "yaw": 30, "pitch": 14}, "minion_super": {"fy": 0.62, "fd": 1.6},
           "minion_spiderling": {"fy": 0.45, "fd": 1.7, "pitch": 22},
           "turret": {"fy": 0.82, "fd": 0.7, "pitch": 8}, "inhibitor": {"fy": 0.5, "fd": 1.3, "pitch": 20},
           "nexus": {"fy": 0.68, "fd": 1.25, "pitch": 12}, "cocoon": {"fy": 0.5, "fd": 2.2, "pitch": 14}}


def shoot(app, draw, bounds, f, bg):
    r, ctx = app.renderer, app.ctx
    cam = r.camera
    lo, hi = bounds
    h = float(hi[1] - lo[1])
    cam.tx, cam.tz = float(lo[0] + hi[0]) / 2, float(lo[2] + hi[2]) / 2
    cam.ty = float(lo[1]) + h * f["fy"]
    cam.distance = max(h, float(hi[0] - lo[0]), float(hi[2] - lo[2])) * f["fd"]
    cam.pitch, cam.yaw = math.radians(f.get("pitch", 8)), math.radians(f.get("yaw", 15))
    r.begin_3d(cam, clear=bg, sky=False)
    draw(r)
    w, hh = r.window_size
    raw = ctx.screen.read(viewport=(0, 0, w, hh), components=3, alignment=1)
    img = Image.frombytes("RGB", (w, hh), raw).transpose(Image.FLIP_TOP_BOTTOM)
    s = min(w, hh)
    img = img.crop(((w - s) // 2, (hh - s) // 2, (w + s) // 2, (hh + s) // 2)).resize((SIZE * 2, SIZE * 2), Image.LANCZOS)
    yy, xx = np.mgrid[0:SIZE * 2, 0:SIZE * 2]
    d = np.sqrt((xx - SIZE) ** 2 + (yy - SIZE) ** 2) / (SIZE * 1.42)
    v = (1 - 0.45 * np.clip(d, 0, 1) ** 2)[..., None]
    return Image.fromarray((np.asarray(img) * v).astype("uint8")).resize((SIZE, SIZE), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    app = App()
    m = app.models
    rot = facing_to_rot(math.pi / 2)                 # 카메라(+Z) 쪽을 본다
    bgs = {0: (0.12, 0.17, 0.28), 1: (0.28, 0.13, 0.13)}
    for team in (0, 1):
        meshes = m.team_meshes[team]
        for key in ("minion_melee", "minion_caster", "minion_cannon", "minion_super", "minion_spiderling",
                    "turret", "inhibitor", "nexus"):
            mesh = meshes[key]
            weapon = m.minion_weapons[team].get(key)

            def draw(r, mesh=mesh, weapon=weapon):
                r.draw(mesh, model_matrix(0, 0, 0, rot_y=rot))
                if weapon:
                    wmesh, (px, py, pz) = weapon
                    c, s_ = math.cos(rot), math.sin(rot)
                    r.draw(wmesh, model_matrix(c * px + s_ * pz, py, -s_ * px + c * pz, rot_y=rot))
            img = shoot(app, draw, mesh.bounds, FRAMING[key], bgs[team])
            name = key.replace("minion_", "")
            img.save(os.path.join(OUT, f"{name}_{team}.png"))
            print("저장:", name, team)
            pygame.event.pump()
    img = shoot(app, lambda r: r.draw(m.cocoon, model_matrix(0, 0, 0)), m.cocoon.bounds, FRAMING["cocoon"], (0.2, 0.18, 0.15))
    img.save(os.path.join(OUT, "cocoon.png"))
    print("저장: cocoon")
    pygame.quit()


if __name__ == "__main__":
    main()
