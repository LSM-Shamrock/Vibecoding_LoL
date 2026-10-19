"""챔피언 초상화 생성: 게임의 3D 모델을 머리~어깨 구도로 렌더링해 assets/ui/portraits/<챔피언id>.png 로 저장한다.
사용: python tools/build_portraits.py [챔피언 id ...]   (창이 잠깐 뜬다. 모델을 바꾼 뒤 다시 실행하면 초상화도 갱신된다.
      id 를 적으면 그 챔피언 것만 다시 만든다. 예: python tools/build_portraits.py dragon)
"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import numpy as np
import pygame
from PIL import Image, ImageDraw, ImageFilter

from game.client.app import App
from game.client.gl import model_matrix
from game.shared import data as gamedata

OUT = os.path.join(ROOT, "assets", "ui", "portraits")
SIZE = 128
# 챔피언별 구도 (카메라가 보는 높이, 거리, 좌우 회전). 키가 크거나 작은 모델은 여기서 맞춘다.
FRAMING = {"spider": {"ty": 0.68, "tz": 0.3, "dist": 2.3, "pitch": 14},      # 절차적 리그(거미): 얼굴이 카메라를 보게
           "serpent": {"ty": 1.85, "dist": 4.2, "pitch": 8, "yaw": 25},      # 절차적 리그(이무기): ㄴ자로 세운 몸과 머리를 비스듬히
           "dragon": {"ty": 1.9, "tz": 2.5, "tx": 0.45, "dist": 2.2, "pitch": 4, "yaw": 18}}   # 절차적 리그(용): 앞으로 내민 머리와 가슴
DEFAULT = {"ty": 1.3, "dist": 2.75, "rot": 0.0, "tx": 0.0, "tz": 0.0, "pitch": 4, "yaw": 0.0}


def main():
    os.makedirs(OUT, exist_ok=True)
    app = App()
    r, ctx = app.renderer, app.ctx
    cam = r.camera
    only = sys.argv[1:]
    for cid, data in gamedata.champions().items():
        if only and cid not in only:
            continue
        f = dict(DEFAULT, **FRAMING.get(cid, {}))
        col = tuple(c / 255 for c in data.get("color", (160, 170, 190)))
        mesh = app.models.champion(cid)
        ca = app.models.new_champ_anim(cid)
        if ca:                                      # 절차적 리그: 원점에서 카메라(+Z)를 보게 두고 잠깐 돌려 자세를 잡는다
            class Ent:
                x, z, f = 0.0, 0.0, math.pi / 2
            for _ in range(10):
                ca.update(1 / 30, {"st": (), "a": 0}, Ent)
        cam.tx, cam.ty, cam.tz = f["tx"], f["ty"], f["tz"]
        cam.distance, cam.pitch, cam.yaw = f["dist"], math.radians(f["pitch"]), math.radians(f["yaw"])
        bg = tuple(0.12 + 0.2 * c for c in col)
        r.begin_3d(cam, clear=bg, sky=False)
        if ca:
            ca.draw(r)
        else:
            r.draw(mesh, model_matrix(0, 0, 0, rot_y=f["rot"]))
        w, h = r.window_size
        raw = ctx.screen.read(viewport=(0, 0, w, h), components=3, alignment=1)
        img = Image.frombytes("RGB", (w, h), raw).transpose(Image.FLIP_TOP_BOTTOM)
        s = min(w, h)
        img = img.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2)).resize((SIZE * 2, SIZE * 2), Image.LANCZOS)
        # 가장자리 어둡게 (비네트)
        yy, xx = np.mgrid[0:SIZE * 2, 0:SIZE * 2]
        d = np.sqrt((xx - SIZE) ** 2 + (yy - SIZE) ** 2) / (SIZE * 1.42)
        v = (1 - 0.45 * np.clip(d, 0, 1) ** 2)[..., None]
        img = Image.fromarray((np.asarray(img) * v).astype("uint8")).resize((SIZE, SIZE), Image.LANCZOS)
        img.save(os.path.join(OUT, f"{cid}.png"))
        print("저장:", cid)
        pygame.event.pump()
    pygame.quit()


if __name__ == "__main__":
    main()
