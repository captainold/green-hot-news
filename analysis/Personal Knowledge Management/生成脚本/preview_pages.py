# -*- coding: utf-8 -*-
"""
把 演示文稿.excalidraw 的每一页渲染成 PNG，用于**放映前离线检查**（不开 Obsidian 也能看）。
顺带作为"会议室电脑没装 Obsidian"的兜底：投屏只放 预览/ 文件夹里的 PNG 即可。

依赖 render_png.py（同目录）。
运行：python preview_pages.py
输出：<项目>/预览/01-封面.png …（每页一张）
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_png  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DECK = os.path.join(BASE_DIR, "演示文稿.excalidraw")
OUT_DIR = os.path.join(BASE_DIR, "预览")
PAD = 30


def e_bounds(e):
    if e["type"] == "arrow":
        xs = [e["x"] + p[0] for p in e["points"]]
        ys = [e["y"] + p[1] for p in e["points"]]
        return min(xs), min(ys), max(xs), max(ys)
    return e["x"], e["y"], e["x"] + e.get("width", 0), e["y"] + e.get("height", 0)


def main():
    with open(DECK, encoding="utf-8") as f:
        deck = json.load(f)
    els = deck["elements"]
    frames = [e for e in els if e["type"] == "frame"]
    frames.sort(key=lambda f: f["customData"]["slideshow"]["order"])

    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="deck_page_")

    for f in frames:
        order = f["customData"]["slideshow"]["order"] + 1
        kids = [e for e in els if e.get("frameId") == f["id"]]
        if not kids:
            print(f"  跳过（空页）：{f['name']}")
            continue
        xs1 = min(e_bounds(e)[0] for e in kids)
        ys1 = min(e_bounds(e)[1] for e in kids)
        page = []
        for e in kids:
            new = json.loads(json.dumps(e))
            new["x"] = round(new["x"] - xs1 + PAD, 2)
            new["y"] = round(new["y"] - ys1 + PAD, 2)
            new["frameId"] = None
            new.pop("customData", None)
            page.append(new)
        # frame 元素本身也画出来（带名字的边框），便于对照
        frame_copy = json.loads(json.dumps(f))
        frame_copy["x"], frame_copy["y"] = PAD, PAD
        frame_copy["width"] = round(max(e_bounds(e)[2] for e in kids) - xs1 + PAD * 2)
        frame_copy["height"] = round(max(e_bounds(e)[3] for e in kids) - ys1 + PAD * 2)
        frame_copy.pop("customData", None)
        page.append(frame_copy)

        src = os.path.join(tmp, f"page{order:02d}.excalidraw")
        with open(src, "w", encoding="utf-8") as fp:
            json.dump({"type": "excalidraw", "version": 2, "elements": page,
                       "appState": {"viewBackgroundColor": "#ffffff"}, "files": {}},
                      fp, ensure_ascii=False)
        name = f["name"].replace(" ", "-").replace("·", "")
        out = os.path.join(OUT_DIR, f"{order:02d}-{name}.png")
        render_png.render(src, out)
        print(f"  {os.path.basename(out)}")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n共 {len(frames)} 页 → {OUT_DIR}")


if __name__ == "__main__":
    main()
