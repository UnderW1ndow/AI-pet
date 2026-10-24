"""Wanx 2.1 VACE image-reference video generation for AI-pet."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable

import requests
from PIL import Image

from video_api import _download_video

MODEL = "wanx2.1-vace-plus"
BASE = "https://dashscope.aliyuncs.com/api/v1"
PROMPTS = {
    "待机呼吸": "固定镜头，完整正面全身，一位白发紫眼、双角、浅紫色龙翼和卷曲龙尾、穿白色荷叶边礼服的可爱动漫龙少女，与参考图的脸、服饰、发型、翅膀、尾巴完全一致。纯亮绿色绿幕背景，无地面无影子。只做轻微自然呼吸，头发和翅膀轻轻起伏，双脚固定，首尾回到同一姿势。无其他人物、文字、镜头运动。",
    "眨眼": "固定镜头，完整正面全身，严格保持参考图的白发紫眼双角龙少女、白色礼服、浅紫色龙翼和尾巴。纯亮绿色绿幕背景，无地面无影子。身体和双脚保持原位，双眼自然闭合后睁开一次，首尾为睁眼原姿势。无变脸、转身、其他人物、文字和镜头运动。",
    "点击回应": "固定镜头，完整正面全身，严格保持参考图的白发紫眼双角龙少女、白色礼服、浅紫色龙翼和尾巴。纯亮绿色绿幕背景，无地面无影子。像被轻轻点了一下，开心地小幅歪头、抬手并轻微弹跳，然后回到原姿势；双脚回到原位。无变脸、转身、其他人物、文字和镜头运动。",
}


def _safe_json(response: requests.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok:
        raise RuntimeError(f"视频 API 请求失败（HTTP {response.status_code}，{data.get('code', '')}）：{data.get('message', response.text[:300])}")
    return data


def _headers(key: str, *, submit: bool = False) -> dict[str, str]:
    result = {"Authorization": f"Bearer {key}"}
    if submit:
        result.update({"Content-Type": "application/json", "X-DashScope-Async": "enable",
                       "X-DashScope-OssResourceResolve": "enable"})
    return result


def make_reference(base: Image.Image, target: Path) -> None:
    if base.size != (640, 360):
        raise ValueError("VACE 参考图需要 640×360 的标准桌宠画布。")
    background = Image.new("RGB", base.size, (0, 255, 0))
    background.paste(base.convert("RGBA"), mask=base.getchannel("A"))
    background.resize((1280, 720), Image.Resampling.LANCZOS).save(target)


def upload_reference(file: Path, key: str) -> str:
    policy_response = requests.get(BASE + "/uploads", params={"action": "getPolicy", "model": MODEL},
                                   headers=_headers(key), timeout=30)
    policy = _safe_json(policy_response).get("data", {})
    host = str(policy.get("upload_host", ""))
    if not host.startswith("https://") or not policy.get("upload_dir"):
        raise RuntimeError("视频 API 未返回有效的临时上传地址。")
    object_key = str(policy["upload_dir"]).rstrip("/") + "/" + file.name
    fields = {
        "OSSAccessKeyId": (None, policy["oss_access_key_id"]),
        "Signature": (None, policy["signature"]),
        "policy": (None, policy["policy"]),
        "x-oss-object-acl": (None, policy["x_oss_object_acl"]),
        "x-oss-forbid-overwrite": (None, policy["x_oss_forbid_overwrite"]),
        "key": (None, object_key),
        "success_action_status": (None, "200"),
    }
    with file.open("rb") as stream:
        fields["file"] = (file.name, stream, "image/png")
        uploaded = requests.post(host, files=fields, timeout=120)
    if uploaded.status_code != 200:
        raise RuntimeError(f"参考图上传失败（HTTP {uploaded.status_code}）：{uploaded.text[:300]}")
    return "oss://" + object_key


def generate_three(base: Image.Image, key: str, cache_root: Path,
                   progress: Callable[[str], None] = lambda _: None,
                   *, poll_interval: float = 15, max_wait: float = 2400) -> dict[str, Path]:
    cache_root.mkdir(parents=True, exist_ok=True)
    reference_bytes = base.tobytes()
    fingerprint = hashlib.sha256(MODEL.encode() + reference_bytes).hexdigest()[:24]
    folder = cache_root / ("vace-" + fingerprint)
    folder.mkdir(parents=True, exist_ok=True)
    reference_file = folder / "reference.png"
    if not reference_file.exists():
        make_reference(base, reference_file)
    results: dict[str, Path] = {}
    pending: dict[str, str] = {}
    reference_url: str | None = None
    # Submit all missing tasks first so model processing can run concurrently.
    for title, prompt in PROMPTS.items():
        clip = folder / f"{title}.mp4"
        state_file = folder / f"{title}.json"
        if clip.exists() and clip.stat().st_size >= 10_000:
            results[title] = clip
            progress(f"{title}：复用已下载的视频")
            continue
        state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
        task_id = state.get("task_id")
        if task_id and time.time() - state.get("submitted_at", 0) > 23 * 3600:
            raise RuntimeError(f"{title} 的任务查询已过期。任务记录保留在 {state_file}。")
        if not task_id:
            if reference_url is None:
                progress("正在上传 VACE 参考图")
                reference_url = upload_reference(reference_file, key)
            progress(f"{title}：提交 VACE 生成任务")
            payload = {"model": MODEL,
                       "input": {"function": "image_reference", "prompt": prompt,
                                 "ref_images_url": [reference_url]},
                       "parameters": {"obj_or_bg": ["obj"], "size": "1280*720",
                                      "duration": 5, "prompt_extend": False, "watermark": False}}
            response = requests.post(BASE + "/services/aigc/video-generation/video-synthesis",
                                     json=payload, headers=_headers(key, submit=True), timeout=90)
            data = _safe_json(response)
            task_id = data.get("output", {}).get("task_id")
            if not isinstance(task_id, str) or not task_id:
                raise RuntimeError(f"{title} 未返回任务 ID：{data.get('code', '')} {data.get('message', '')}")
            state_file.write_text(json.dumps({"task_id": task_id, "submitted_at": time.time(), "model": MODEL},
                                             ensure_ascii=False), encoding="utf-8")
        pending[title] = task_id
    deadline = time.monotonic() + max_wait
    while pending:
        if time.monotonic() > deadline:
            raise TimeoutError("VACE 视频仍在生成，任务 ID 已保存；下次运行可继续查询。")
        for title, task_id in list(pending.items()):
            progress(f"VACE 生成中：{', '.join(pending)}")
            response = requests.get(BASE + "/tasks/" + task_id, headers=_headers(key), timeout=60)
            data = _safe_json(response)
            output = data.get("output", {})
            status = output.get("task_status")
            if status == "SUCCEEDED":
                url = output.get("video_url")
                if not isinstance(url, str):
                    raise RuntimeError(f"{title} 任务已完成，但没有视频地址。")
                progress(f"{title}：下载视频")
                clip = folder / f"{title}.mp4"
                _download_video(url, clip)
                results[title] = clip
                del pending[title]
            elif status in ("FAILED", "CANCELED", "UNKNOWN"):
                raise RuntimeError(f"{title} 生成失败（{status}）：{output.get('code', '')} {output.get('message', '')}")
            elif status not in ("PENDING", "RUNNING"):
                raise RuntimeError(f"{title} 返回未知任务状态：{status}")
        if pending:
            time.sleep(poll_interval)
    return {title: results[title] for title in PROMPTS}
