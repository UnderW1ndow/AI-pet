"""Turn green-screen video API results into aligned, transparent pet clips."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from statistics import median

from PIL import Image, ImageChops


def remove_green_fringe(frame: Image.Image) -> Image.Image:
    """Suppress chroma spill without dulling white and violet character art."""
    red, green, blue, alpha = frame.convert("RGBA").split()
    neutral = ImageChops.lighter(red, blue)
    spill = ImageChops.subtract(green, neutral)
    opacity = spill.point(lambda value: max(0, 255 - value * 5))
    alpha = ImageChops.multiply(alpha, opacity)
    green = ImageChops.darker(green, neutral.point(lambda value: min(255, value + 8)))
    return Image.merge("RGBA", (red, green, blue, alpha))


def convert_video(source: Path, target: Path, ffmpeg: str = "ffmpeg", *, pingpong: bool = True) -> None:
    with tempfile.TemporaryDirectory(prefix="ai-pet-video-") as temporary:
        folder = Path(temporary)
        frames_dir = folder / "frames"
        frames_dir.mkdir()
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                   "-vf", "fps=15,scale=640:360:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=640:360:(ow-iw)/2:(oh-ih)/2:color=0x00ff00,colorkey=0x00ff00:0.22:0.10,format=rgba",
                   "-frames:v", "120", str(frames_dir / "%04d.png")]
        subprocess.run(command, check=True, capture_output=True, text=True)
        paths = sorted(frames_dir.glob("*.png"))
        if len(paths) < 2:
            raise RuntimeError("视频 API 返回的视频帧不足，无法生成桌宠动作。")
        frames = [remove_green_fringe(Image.open(path)) for path in paths]
        candidates = []
        for frame in frames:
            bbox = frame.getchannel("A").point(lambda value: 255 if value > 45 else 0).getbbox()
            # Video models sometimes produce a few noisy transition frames at
            # the start. Skip frames whose background still covers the canvas.
            if bbox and (bbox[2] - bbox[0]) < 600 and (bbox[3] - bbox[1]) < 340:
                candidates.append((frame, bbox))
        if candidates:
            typical_width = median(b[2] - b[0] for _, b in candidates)
            typical_height = median(b[3] - b[1] for _, b in candidates)
            candidates = [(frame, box) for frame, box in candidates
                          if (box[2] - box[0]) <= typical_width * 1.45
                          and (box[3] - box[1]) <= typical_height * 1.25]
        usable = [frame for frame, _ in candidates]
        boxes = [box for _, box in candidates]
        if len(boxes) < max(2, len(frames) * .6):
            raise RuntimeError("绿幕抠像后角色消失。请换一张轮廓清晰的图片重试。")
        box = (min(b[0] for b in boxes), min(b[1] for b in boxes),
               max(b[2] for b in boxes), max(b[3] for b in boxes))
        bw, bh = box[2] - box[0], box[3] - box[1]
        if bw < 24 or bh < 24 or bw > 625 or bh > 345:
            raise RuntimeError("生成视频的背景不够纯绿，无法可靠提取角色。请重试或使用本地生成。")
        factor = min(220 / bw, 270 / bh)
        size = (max(1, round(bw * factor)), max(1, round(bh * factor)))
        output = folder / "output"
        output.mkdir()
        # Ping-pong playback returns smoothly to the first pose. Use one common
        # crop and scale for every frame so the character does not jitter.
        playback = usable + list(reversed(usable[1:-1])) if pingpong else usable
        for index, frame in enumerate(playback):
            cut = frame.crop(box).resize(size, Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (640, 360))
            canvas.alpha_composite(cut, ((640 - size[0]) // 2, 306 - size[1]))
            canvas.save(output / f"{index:04d}.png")
        encode = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-framerate", "15",
                  "-i", str(output / "%04d.png"), "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                  "-auto-alt-ref", "0", "-crf", "35", "-b:v", "0", str(target)]
        subprocess.run(encode, check=True, capture_output=True, text=True)
