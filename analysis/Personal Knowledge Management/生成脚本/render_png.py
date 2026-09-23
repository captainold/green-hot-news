# -*- coding: utf-8 -*-
"""
把 .excalidraw 渲染成 PNG（Canvas 内嵌用）。
不依赖任何渲染库：直接按元素坐标用 Pillow 重绘（矩形/圆角/虚线框/文字/箭头）。
运行：python render_png.py
"""
import json
import os
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE_DIR, "图")
OUT = os.path.join(BASE_DIR, "图")
FONT_REG = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
SCALE = 2
MARGIN = 40
LINE_H = 1.25

_font_cache = {}


def font(size, bold=False):
    key = (size, bold)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)
    return _font_cache[key]


def rgb(hex_str):
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def wrap(text, f, max_w):
    """按可用宽度折行（中文逐字、英文按词）。"""
    out = []
    for para in text.split("\n"):
        if not para:
            out.append("")
            continue
        line = ""
        for ch in para:
            if f.getlength(line + ch) <= max_w or not line:
                line += ch
            else:
                out.append(line)
                line = ch
        out.append(line)
    return out


def dashed_line(dr, p1, p2, color, width, dash=14, gap=10):
    import math
    x1, y1 = p1
    x2, y2 = p2
    total = math.hypot(x2 - x1, y2 - y1)
    if total == 0:
        return
    ux, uy = (x2 - x1) / total, (y2 - y1) / total
    pos = 0.0
    while pos < total:
        end = min(pos + dash, total)
        dr.line([(x1 + ux * pos, y1 + uy * pos), (x1 + ux * end, y1 + uy * end)],
                fill=color, width=width)
        pos = end + gap


def arrow_head(dr, p_from, p_to, color, scale):
    import math
    dx, dy = p_to[0] - p_from[0], p_to[1] - p_from[1]
    L = math.hypot(dx, dy) or 1
    ux, uy = dx / L, dy / L
    size = 13 * scale
    bx, by = p_to[0] - ux * size, p_to[1] - uy * size
    nx, ny = -uy, ux
    dr.polygon([p_to, (bx + nx * size * 0.45, by + ny * size * 0.45),
                (bx - nx * size * 0.45, by - ny * size * 0.45)], fill=color)


def render(src_path, out_path):
    with open(src_path, encoding="utf-8") as f:
        doc = json.load(f)
    els = doc["elements"]
    rects = {e["id"]: e for e in els if e["type"] == "rectangle"}

    # ── 计算画布范围（文字用真实字体宽度） ──
    max_x = max_y = 0
    min_x = min_y = 10 ** 9
    for e in els:
        min_x, min_y = min(min_x, e["x"]), min(min_y, e["y"])
        if e["type"] == "text":
            fs = int(e["fontSize"] * SCALE)
            f = font(fs, e["fontSize"] >= 24)
            lines = e["text"].split("\n")
            w = max(f.getlength(l) for l in lines)
            if e.get("containerId"):
                c = rects[e["containerId"]]
                min_x, min_y = min(min_x, c["x"]), min(min_y, c["y"])
                max_x = max(max_x, c["x"] + c["width"])
                max_y = max(max_y, c["y"] + c["height"])
            max_x = max(max_x, e["x"] + w / SCALE)
            max_y = max(max_y, e["y"] + len(lines) * e["fontSize"] * LINE_H)
        elif e["type"] == "arrow":
            pts = [(e["x"] + p[0], e["y"] + p[1]) for p in e["points"]]
            max_x = max(max_x, max(p[0] for p in pts))
            max_y = max(max_y, max(p[1] for p in pts))
            min_x = min(min_x, min(p[0] for p in pts))
            min_y = min(min_y, min(p[1] for p in pts))
        else:
            max_x = max(max_x, e["x"] + e.get("width", 0))
            max_y = max(max_y, e["y"] + e.get("height", 0))

    W = int((max_x - min(min_x, 0) + MARGIN * 2) * SCALE)
    H = int((max_y - min(min_y, 0) + MARGIN * 2) * SCALE)
    img = Image.new("RGB", (W, H), rgb(doc["appState"]["viewBackgroundColor"]))
    dr = ImageDraw.Draw(img)

    def sx(v):
        return (v - min(min_x, 0) + MARGIN) * SCALE

    def sy(v):
        return (v - min(min_y, 0) + MARGIN) * SCALE

    for e in els:
        t = e["type"]
        stroke = rgb(e["strokeColor"])
        if t == "rectangle":
            x0, y0 = sx(e["x"]), sy(e["y"])
            x1, y1 = x0 + e["width"] * SCALE, y0 + e["height"] * SCALE
            fill = None if e["backgroundColor"] == "transparent" else rgb(e["backgroundColor"])
            w = int(e["strokeWidth"] * SCALE)
            radius = int(8 * SCALE)
            if e["strokeStyle"] == "dashed":
                if fill:
                    dr.rectangle([x0, y0, x1, y1], fill=fill)
                for p1, p2 in [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
                               ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]:
                    dashed_line(dr, p1, p2, stroke, w, dash=12 * SCALE, gap=8 * SCALE)
            else:
                dr.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill,
                                     outline=stroke, width=w)
        elif t == "text":
            fs = int(e["fontSize"] * SCALE)
            f = font(fs, e["fontSize"] >= 24)
            lines = e["text"].split("\n")
            lh = e["fontSize"] * LINE_H * SCALE
            if e.get("containerId"):
                c = rects[e["containerId"]]
                pad = 10 * SCALE
                lines = wrap(e["text"], f, c["width"] * SCALE - pad * 2)
                cx = sx(c["x"]) + c["width"] * SCALE / 2
                cy = sy(c["y"]) + c["height"] * SCALE / 2
                total = len(lines) * lh
                for i, ln in enumerate(lines):
                    dr.text((cx, cy - total / 2 + (i + 0.5) * lh), ln, font=f,
                            fill=stroke, anchor="mm")
            else:
                for i, ln in enumerate(lines):
                    if e.get("textAlign") == "center":
                        dr.text((sx(e["x"]) + e["width"] * SCALE / 2,
                                 sy(e["y"]) + (i + 0.5) * lh), ln, font=f,
                                fill=stroke, anchor="mm")
                    else:
                        dr.text((sx(e["x"]), sy(e["y"]) + (i + 0.5) * lh), ln, font=f,
                                fill=stroke, anchor="lm")
        elif t == "arrow":
            pts = [(sx(e["x"] + p[0]), sy(e["y"] + p[1])) for p in e["points"]]
            w = int(e["strokeWidth"] * SCALE)
            if e["strokeStyle"] == "dashed":
                for a, b in zip(pts, pts[1:]):
                    dashed_line(dr, a, b, stroke, w, dash=12 * SCALE, gap=8 * SCALE)
            else:
                dr.line(pts, fill=stroke, width=w, joint="curve")
            if e.get("endArrowhead"):
                arrow_head(dr, pts[-2], pts[-1], stroke, SCALE)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    return out_path, img.size


if __name__ == "__main__":
    for name in sorted(os.listdir(SRC)):
        if name.endswith(".excalidraw"):
            src = os.path.join(SRC, name)
            dst = os.path.join(OUT, name.replace(".excalidraw", ".png"))
            path, size = render(src, dst)
            print(f"{name}  →  {os.path.basename(path)}  {size[0]}x{size[1]} px")
