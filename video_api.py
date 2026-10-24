"""Alibaba Cloud Model Studio (Beijing) image-to-video task client.

The public GUI calls this module only after the user starts a paid-capable
generation. Task ids and downloaded MP4s are cached so retrying after an
interruption does not silently submit the same paid task again.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from PIL import Image

MODEL = "wan2.7-i2v-2026-04-25"
BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
PROMPTS = {
    "待机呼吸": "固定镜头，纯正绿色背景，角色保持正面站立与原图一致。仅有轻微自然的呼吸起伏，头发和服装轻微跟随，不转身、不移动脚底、不改变脸、服饰或比例。首尾姿势一致，适合循环播放。",
    "眨眼": "固定镜头，纯正绿色背景，角色保持正面站立与原图一致。双眼自然闭合再睁开一次，身体和脚底保持不动，不转身、不改变脸、服饰或比例。首尾保持睁眼原姿势，适合循环播放。",
    "点击回应": "固定镜头，纯正绿色背景，角色保持正面站立与原图一致。被轻轻点击后，角色做一次小幅弹跳和歪头回应，随后回到原位，不转身、不离开画面、不改变脸、服饰或比例。首尾姿势一致。",
}
DURATIONS = {"待机呼吸": 3, "眨眼": 2, "点击回应": 3}


def reference_data_uri(base: Image.Image) -> str:
    # The API does not accept an alpha channel. Its green background can be
    # removed again after generation if the model preserves the chroma field.
    frame = Image.new("RGB", base.size, (0, 255, 0))
    frame.paste(base.convert("RGBA"), mask=base.getchannel("A"))
    stream = io.BytesIO()
    frame.save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def _json_request(url: str, key: str, *, body: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    if body is not None:
        headers.update({"Content-Type": "application/json", "X-DashScope-Async": "enable"})
    request = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None,
                                     headers=headers, method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read(8192).decode("utf-8", "replace"))
            code = detail.get("code", "HTTP error")
            message = detail.get("message", "")
        except Exception:
            code, message = "HTTP error", ""
        raise RuntimeError(f"视频 API 请求失败（{error.code}，{code}）：{message}") from None


def _download_video(url: str, target: Path) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError("视频 API 返回了无效的下载链接。")
    temp = target.with_suffix(".downloading")
    limit = 150 * 1024 * 1024
    try:
        with urllib.request.urlopen(url, timeout=120) as response, temp.open("wb") as output:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > limit:
                    raise RuntimeError("生成的视频超过 150 MB，已停止下载。")
                output.write(chunk)
        if total < 10_000:
            raise RuntimeError("生成的视频文件过小，可能并非有效 MP4。")
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


def generate_three(base: Image.Image, key: str, cache_root: Path,
                   progress: Callable[[str], None] = lambda _: None,
                   *, poll_interval: float = 15.0, max_wait: float = 1800.0) -> dict[str, Path]:
    """Generate and cache three MP4 clips, resuming known task ids on retry."""
    reference = reference_data_uri(base)
    fingerprint = hashlib.sha256((MODEL + reference).encode("ascii")).hexdigest()[:24]
    folder = cache_root / fingerprint
    folder.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path] = {}
    for title in PROMPTS:
        clip = folder / f"{title}.mp4"
        state_file = folder / f"{title}.json"
        if clip.exists() and clip.stat().st_size >= 10_000:
            progress(f"{title}：复用已下载的视频")
            result[title] = clip
            continue
        state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
        task_id = state.get("task_id")
        if task_id and time.time() - state.get("submitted_at", 0) > 23 * 3600:
            raise RuntimeError(f"{title} 的任务已超过查询有效期；请先移除旧任务记录，再重新提交。")
        if not task_id:
            progress(f"{title}：提交视频生成任务")
            payload = {
                "model": MODEL,
                "input": {
                    "prompt": PROMPTS[title],
                    "negative_prompt": "镜头移动、背景变化、角色变脸、身体变形、多余肢体、脚底漂移、文字、水印",
                    "media": [{"type": "first_frame", "url": reference},
                              {"type": "last_frame", "url": reference}],
                },
                "parameters": {"resolution": "720P", "duration": DURATIONS[title],
                               "prompt_extend": False, "watermark": False},
            }
            response = _json_request(BASE_URL + "/services/aigc/video-generation/video-synthesis", key, body=payload)
            task_id = response.get("output", {}).get("task_id")
            if not isinstance(task_id, str) or not task_id:
                raise RuntimeError(f"{title} 未返回任务 ID：{response.get('code', '未知错误')} {response.get('message', '')}")
            state = {"task_id": task_id, "submitted_at": time.time(), "model": MODEL}
            state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        deadline = time.monotonic() + max_wait
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(f"{title} 仍在生成，任务 ID 已保留；下次点击可继续查询。")
            progress(f"{title}：等待视频任务完成")
            response = _json_request(BASE_URL + "/tasks/" + urllib.parse.quote(task_id), key)
            output = response.get("output", {})
            status = output.get("task_status")
            if status == "SUCCEEDED":
                video_url = output.get("video_url")
                if not isinstance(video_url, str):
                    raise RuntimeError(f"{title} 已完成，但没有返回视频地址。")
                progress(f"{title}：下载生成的视频")
                _download_video(video_url, clip)
                result[title] = clip
                break
            if status in ("FAILED", "CANCELED", "UNKNOWN"):
                raise RuntimeError(f"{title} 生成失败（{status}）：{output.get('code', '')} {output.get('message', '')}")
            if status not in ("PENDING", "RUNNING"):
                raise RuntimeError(f"{title} 返回了未知状态：{status}")
            time.sleep(poll_interval)
    return result
