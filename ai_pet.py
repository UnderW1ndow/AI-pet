"""AI-pet 0.11: turn a character image into a desktop pet pack."""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import webbrowser
from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter, ImageTk
from secret_store import delete_key, load_key, save_key, storage_description
from video_api import generate_three
from vace_api import generate_three as generate_vace_three
from video_postprocess import convert_video

W, H = 640, 360
FPS = 15
VIDEO_API_INFO_URL = "https://www.aliyun.com/benefit/ai/aistar?clubBiz=subTask..12934056..10274.."
APP_ROOT = Path(__file__).resolve().parent
DEFAULT_HOME = APP_ROOT / "data" if (APP_ROOT / "runtime").exists() else Path.home() / ".dsh"


def start_or_reload_runtime() -> str:
    """Refresh a running local player, or start the bundled standalone runtime."""
    home = Path(os.environ.get("DSH_HOME", DEFAULT_HOME))
    state_file = home / "dsh-pet" / "standalone-runtime.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            request = urllib.request.Request(
                f"http://127.0.0.1:{int(state['port'])}/dsh-pet-7340/reload",
                data=b"{}", method="POST",
                headers={"x-dsh-pet-token": state["token"], "content-type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                if response.status == 200:
                    return "已重载桌宠"
        except Exception:
            pass
    runtime = APP_ROOT / "runtime"
    if not (runtime / "lib" / "standalone.js").exists():
        return "角色包已生成；请启动 AI-pet。"
    env = os.environ.copy()
    env["DSH_HOME"] = str(home)
    electron_relative = (
        Path("Electron.app") / "Contents" / "MacOS" / "Electron"
        if sys.platform == "darwin" else Path("electron.exe")
    )
    existing_electron = Path.home() / ".dsh" / "electron" / electron_relative
    if existing_electron.exists():
        env["DSH_PET_ELECTRON_PATH"] = str(existing_electron)
    log = APP_ROOT / "ai-pet-runtime.log"
    with log.open("ab") as stream:
        subprocess.Popen(["node", str(runtime / "lib" / "standalone.js")], cwd=runtime,
                         env=env, stdout=stream, stderr=subprocess.STDOUT,
                         creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    return "已启动桌宠运行器"


def remove_background(image: Image.Image) -> tuple[Image.Image, str]:
    """Keep source alpha, or flood-fill a nearly uniform edge background."""
    im = image.convert("RGBA")
    alpha = im.getchannel("A")
    if alpha.getextrema()[0] < 250:
        return im, "原图透明通道"
    # Edge pixels from the corners define a likely studio / chroma background.
    sample = [im.getpixel(p)[:3] for p in ((0, 0), (im.width - 1, 0), (0, im.height - 1), (im.width - 1, im.height - 1))]
    bg = tuple(sorted(c[i] for c in sample)[2] for i in range(3))
    spread = max(max(c[i] for c in sample) - min(c[i] for c in sample) for i in range(3))
    if spread > 45:
        raise ValueError("背景并非纯色，0.11 版暂无法可靠自动抠图。请上传透明 PNG 或纯色背景图。")
    # Work at a bounded size to keep flood fill predictable on large uploads.
    scale = min(1.0, 1200 / max(im.size))
    if scale < 1:
        im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.Resampling.LANCZOS)
    pix = im.load()
    width, height = im.size
    seen = bytearray(width * height)
    queue = deque()
    for x in range(width):
        queue.extend(((x, 0), (x, height - 1)))
    for y in range(height):
        queue.extend(((0, y), (width - 1, y)))
    while queue:
        x, y = queue.popleft()
        idx = y * width + x
        if seen[idx]:
            continue
        seen[idx] = 1
        r, g, b, _ = pix[x, y]
        if max(abs(r - bg[0]), abs(g - bg[1]), abs(b - bg[2])) > 42:
            continue
        pix[x, y] = (r, g, b, 0)
        if x:
            queue.append((x - 1, y))
        if x + 1 < width:
            queue.append((x + 1, y))
        if y:
            queue.append((x, y - 1))
        if y + 1 < height:
            queue.append((x, y + 1))
    # Slight edge softening reduces a hard chroma fringe.
    a = im.getchannel("A").filter(ImageFilter.GaussianBlur(0.5))
    im.putalpha(a)
    return im, "自动纯色背景抠像"


def normalize(image: Image.Image) -> tuple[Image.Image, dict]:
    alpha = image.getchannel("A")
    mask = alpha.point(lambda v: 255 if v > 30 else 0)
    bbox = mask.getbbox()
    if not bbox:
        raise ValueError("没有检测到角色。")
    left, top, right, bottom = bbox
    if (right - left) < 24 or (bottom - top) < 24:
        raise ValueError("角色过小，请上传更清晰的全身图。")
    if (right - left) / image.width > .985 and (bottom - top) / image.height > .985:
        raise ValueError("角色几乎填满整张图，无法判断轮廓；请提供透明或纯色背景图。")
    cut = image.crop(bbox)
    # Match upstream's 640x360 asset canvas and put the visible foot on y=306.
    factor = min(220 / cut.width, 270 / cut.height)
    nw, nh = max(1, round(cut.width * factor)), max(1, round(cut.height * factor))
    cut = cut.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.alpha_composite(cut, ((W - nw) // 2, 306 - nh))
    return canvas, {"source_bbox": list(bbox), "foot_y": 306, "scaled_size": [nw, nh]}


def warp_idle(base: Image.Image, t: float) -> Image.Image:
    # Gentle breathing: 1.5% vertical expansion, anchored to foot baseline.
    pulse = .5 - .5 * math.cos(2 * math.pi * t)
    stretch = 1 + .015 * pulse
    nh = round(H * stretch)
    resized = base.resize((W, nh), Image.Resampling.BICUBIC)
    frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    frame.alpha_composite(resized, (0, round(306 * (1 - stretch))))
    return frame


def warp_blink(base: Image.Image, t: float) -> Image.Image:
    """Close the inferred upper-face band briefly; works best on frontal art."""
    frame = warp_idle(base, t)
    amount = max(0.0, 1 - abs(t - .48) / .11)
    if amount <= 0:
        return frame
    bbox = frame.getchannel("A").getbbox()
    if not bbox:
        return frame
    x0, y0, x1, y1 = bbox
    body_h = y1 - y0
    # Eye band is an approximation; reserve exact landmarks for a future model.
    band_top = y0 + round(body_h * .16)
    band_bottom = y0 + round(body_h * .34)
    band = frame.crop((x0, band_top, x1, band_bottom))
    narrow_h = max(1, round(band.height * (1 - .78 * amount)))
    narrowed = band.resize((band.width, narrow_h), Image.Resampling.BICUBIC)
    overlay = Image.new("RGBA", band.size, (0, 0, 0, 0))
    overlay.alpha_composite(narrowed, (0, (band.height - narrow_h) // 2))
    frame.paste(overlay, (x0, band_top))
    return frame


def warp_click(base: Image.Image, t: float) -> Image.Image:
    # One squash/stretch and a short hop; return to the same base pose.
    envelope = math.sin(math.pi * t) ** 2
    sx = 1 + .07 * envelope * math.cos(2 * math.pi * t)
    sy = 1 - .07 * envelope * math.cos(2 * math.pi * t)
    nw, nh = round(W * sx), round(H * sy)
    obj = base.resize((nw, nh), Image.Resampling.BICUBIC)
    frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    frame.alpha_composite(obj, ((W - nw) // 2, round(306 * (1 - sy) - 13 * envelope)))
    return frame


def encode_clip(base: Image.Image, function, target: Path, duration: float, ffmpeg: str) -> None:
    with tempfile.TemporaryDirectory(prefix="ai-pet-") as temp:
        folder = Path(temp)
        frames = round(duration * FPS)
        for i in range(frames):
            function(base, i / max(1, frames - 1)).save(folder / f"{i:04d}.png")
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(FPS),
                   "-i", str(folder / "%04d.png"), "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                   "-auto-alt-ref", "0", "-crf", "35", "-b:v", "0", str(target)]
        subprocess.run(command, check=True, capture_output=True, text=True)


def prepare_image(source: Path, name: str, ffmpeg: str) -> tuple[Image.Image, str, dict]:
    if not shutil.which(ffmpeg):
        raise RuntimeError("找不到 ffmpeg，请安装后把它加入 PATH。")
    if not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in name):
        raise ValueError("角色名称只能使用小写英文字母、数字和连字符。")
    if source.stat().st_size > 25 * 1024 * 1024:
        raise ValueError("图片不能超过 25 MB。")
    with Image.open(source) as raw:
        raw.load()
        if raw.width * raw.height > 20_000_000:
            raise ValueError("图片像素过大，请缩小到 2000 万像素以内。")
        cut, method = remove_background(raw)
    base, geometry = normalize(cut)
    return base, method, geometry


def write_pack(destination: Path, name: str, method: str, geometry: dict,
               engine: str) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    config = {
        "pets": [{"id": name, "name": name, "size": 320, "balanceEnabled": False, "whisperEnabled": False,
                  "workStatusEnabled": False, "fixedEnabled": True, "display": "desktop",
                  "position": {"corner": "bottom-right", "marginX": 32, "marginY": 48}}],
        "animations": {"idle": ["待机呼吸", "眨眼"], "turn": [], "drag": [],
                       "clicks": ["点击回应"],
                       "moves": {"default": {"minDist": 80, "maxDist": 360, "margin": 20,
                                             "leadSec": 2, "tailSec": 2}, "actions": []},
                       "categories": [], "events": {"balance": ["待机呼吸"]}},
        "animationWeights": {"idle": 100, "turn": 0, "move": 0}
    }
    config_path = destination / f"{name}-config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    (destination / f"{name}-report.json").write_text(json.dumps({"segmentation": method, "engine": engine, **geometry}, ensure_ascii=False, indent=2), encoding="utf-8")
    return config_path


def create_pack(source: Path, destination: Path, name: str = "my-pet", ffmpeg: str = "ffmpeg") -> Path:
    base, method, geometry = prepare_image(source, name, ffmpeg)
    destination.mkdir(parents=True, exist_ok=True)
    asset_dir = destination / f"{name}-animation"
    asset_dir.mkdir(exist_ok=True)
    base.save(asset_dir / "preview.png")
    for title, fn, seconds in (("待机呼吸", warp_idle, 3), ("眨眼", warp_blink, 2), ("点击回应", warp_click, 1)):
        encode_clip(base, fn, asset_dir / f"{title}.webm", seconds, ffmpeg)
    return write_pack(destination, name, method, geometry, "local")


def create_video_pack(source: Path, destination: Path, name: str, key: str,
                      progress=lambda _: None, ffmpeg: str = "ffmpeg",
                      model: str = "wan2.7-i2v-2026-04-25") -> Path:
    if not key.strip():
        raise ValueError("请先填写并保存视频 API Key。")
    base, method, geometry = prepare_image(source, name, ffmpeg)
    generator = generate_vace_three if model == "wanx2.1-vace-plus" else generate_three
    clips = generator(base, key.strip(), APP_ROOT / "data" / "video-cache", progress)
    destination.mkdir(parents=True, exist_ok=True)
    asset_dir = destination / f"{name}-animation"
    asset_dir.mkdir(exist_ok=True)
    base.save(asset_dir / "preview.png")
    for title, clip in clips.items():
        progress(f"{title}：转换透明桌宠动画")
        convert_video(clip, asset_dir / f"{title}.webm", ffmpeg)
    return write_pack(destination, name, method, geometry, model)


def launch_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    import threading

    root = tk.Tk()
    root.title("AI-pet 0.11")
    root.geometry("560x850")
    root.resizable(False, False)
    source = tk.StringVar()
    target = tk.StringVar(value=str(Path(os.environ.get("DSH_HOME", DEFAULT_HOME)) / "dsh-pet" / "pet"))
    name = tk.StringVar(value="my-pet")
    status = tk.StringVar(value="请选择透明 PNG 或纯色背景的正面全身角色图")
    ttk.Label(root, text="AI-pet 0.11", font=("Segoe UI", 20, "bold")).pack(pady=(16, 5))
    ttk.Label(root, text="一张图 → 待机呼吸、眨眼、点击回应 → AI-pet 角色包").pack()
    ttk.Label(root, text="要制作更自然的桌宠动作，需要使用能够生成视频的 API。",
              wraplength=500).pack(pady=(12, 2))
    ttk.Button(root, text="了解阿里云视频生成 API 与可选模型",
               command=lambda: webbrowser.open(VIDEO_API_INFO_URL)).pack()
    ttk.Label(root, text="阿里云有免费额度和免费模型可选；具体适用范围以页面和账号显示为准。",
              foreground="#52606d", wraplength=500).pack(pady=(4, 0))
    ttk.Label(root, text="视频 API Key").pack(pady=(10, 2))
    api_key = tk.StringVar()
    ttk.Entry(root, textvariable=api_key, show="*", width=50).pack()
    api_status = tk.StringVar(value="尚未保存 API Key")
    try:
        if load_key(APP_ROOT):
            api_status.set(storage_description())
    except Exception:
        api_status.set("已保存的 API Key 无法读取，可重新填写")
    key_actions = ttk.Frame(root)
    key_actions.pack(pady=(4, 0))
    def save_api_key():
        try:
            save_key(APP_ROOT, api_key.get())
            api_key.set("")
            api_status.set(storage_description())
        except Exception as error:
            messagebox.showerror("保存失败", str(error))
    def clear_api_key():
        try:
            delete_key(APP_ROOT)
            api_key.set("")
            api_status.set("尚未保存 API Key")
        except Exception as error:
            messagebox.showerror("清除失败", str(error))
    ttk.Button(key_actions, text="保存 API Key", command=save_api_key).pack(side="left", padx=5)
    ttk.Button(key_actions, text="清除", command=clear_api_key).pack(side="left", padx=5)
    ttk.Label(root, textvariable=api_status, foreground="#52606d").pack(pady=(3, 0))
    ttk.Label(root, text="视频生成功能使用阿里云百炼万相。生成三个动作可能消耗免费额度或产生费用。",
              foreground="#52606d", wraplength=500).pack(pady=(2, 0))
    ttk.Label(root, text="视频模型").pack(pady=(6, 0))
    model_choice = tk.StringVar(value="wan2.7-i2v-2026-04-25")
    ttk.Combobox(root, textvariable=model_choice, values=("wan2.7-i2v-2026-04-25", "wanx2.1-vace-plus"),
                 state="readonly", width=35).pack()
    ttk.Entry(root, textvariable=source, width=64).pack(pady=(16, 4))
    ttk.Button(root, text="选择角色图片", command=lambda: source.set(filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.webp")]))).pack()
    preview = ttk.Label(root, text="图片预览")
    preview.pack(pady=8)
    def update_preview(*_):
        try:
            im = Image.open(source.get()).convert("RGBA")
            im.thumbnail((140, 140))
            thumb = ImageTk.PhotoImage(im)
            preview.configure(image=thumb, text="")
            preview.image = thumb
        except Exception:
            preview.configure(image="", text="图片预览")
    source.trace_add("write", update_preview)
    ttk.Label(root, text="角色名称（小写英文、数字、连字符）").pack()
    ttk.Entry(root, textvariable=name, width=28).pack(pady=4)
    ttk.Label(root, text="AI-pet 角色包目录").pack()
    ttk.Entry(root, textvariable=target, width=64).pack(pady=4)
    ttk.Button(root, text="选择输出目录", command=lambda: target.set(filedialog.askdirectory() or target.get())).pack()
    button = ttk.Button(root, text="用视频 API 制作三个动作")
    button.pack(pady=(12, 4))
    local_button = ttk.Button(root, text="本地生成三个基础动作（免费）")
    local_button.pack(pady=(0, 8))
    ttk.Label(root, textvariable=status, wraplength=500).pack()
    def start(use_video: bool):
        if not source.get() or not Path(source.get()).is_file():
            messagebox.showerror("缺少图片", "请先选择一张角色图片。")
            return
        try:
            key = load_key(APP_ROOT) if use_video else ""
        except Exception as error:
            messagebox.showerror("读取 API Key 失败", str(error))
            return
        if use_video and not key:
            messagebox.showerror("缺少 API Key", "请先填写并保存视频 API Key。")
            return
        if use_video and not messagebox.askyesno("确认生成", "将提交待机呼吸、眨眼、点击回应三个视频生成任务。可能消耗免费额度或产生费用，确认开始吗？"):
            return
        button.configure(state="disabled")
        local_button.configure(state="disabled")
        status.set("正在抠图、对齐脚底并生成动作…")
        def update(message: str):
            root.after(0, lambda: status.set(message))
        def enable():
            button.configure(state="normal")
            local_button.configure(state="normal")
        def work():
            try:
                if use_video:
                    result = create_video_pack(Path(source.get()), Path(target.get()), name.get(), key, update,
                                               model=model_choice.get())
                else:
                    result = create_pack(Path(source.get()), Path(target.get()), name.get())
                runtime_status = start_or_reload_runtime()
                root.after(0, lambda: (status.set(f"已生成：{result}；{runtime_status}"), messagebox.showinfo("完成", f"角色包已生成：\n{result}\n\n{runtime_status}"), enable()))
            except Exception as error:
                root.after(0, lambda err=str(error): (status.set(err), messagebox.showerror("生成失败", err), enable()))
        threading.Thread(target=work, daemon=True).start()
    button.configure(command=lambda: start(True))
    local_button.configure(command=lambda: start(False))
    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="AI-pet 0.11: one image to an AI-pet character pack")
    parser.add_argument("image", nargs="?", type=Path)
    parser.add_argument("--output", type=Path, default=Path(os.environ.get("DSH_HOME", DEFAULT_HOME)) / "dsh-pet" / "pet")
    parser.add_argument("--name", default="my-pet")
    parser.add_argument("--video-api", action="store_true", help="use the saved video API Key for all three actions")
    parser.add_argument("--model", choices=("wan2.7-i2v-2026-04-25", "wanx2.1-vace-plus"),
                        default="wan2.7-i2v-2026-04-25")
    args = parser.parse_args()
    if args.image:
        if args.video_api:
            print(create_video_pack(args.image, args.output, args.name, load_key(APP_ROOT), print,
                                    model=args.model))
        else:
            print(create_pack(args.image, args.output, args.name))
    else:
        launch_gui()


if __name__ == "__main__":
    main()
