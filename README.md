# AI-pet 0.11

AI-pet 是一款桌面宠物工具。Windows 版本已可运行；macOS 已加入适配代码，理论上可运行，但尚未经过真实 Mac 验证。它支持透明置顶桌宠、待机动画、点击回应、拖动和角色切换，也可以从角色图片制作包含待机呼吸、眨眼、点击回应三个动作的新桌宠。

本项目基于 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 的独立桌面运行模式制作。介绍、展示或分发 AI-pet 时，请一并保留原作者及项目地址。AI-pet 新增了图片制包界面、视频 API 生成入口和以下预设。

## 内置预设

| 名称 | 来源 | 动作 |
| --- | --- | --- |
| `dafeiyu` | 来自原项目 [dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 的原版桌宠，在 AI-pet 中以此名称显示 | 使用原项目动画 |
| `gemini` | 为 AI-pet 导入的角色素材 | 待机呼吸、眨眼、点击回应 |
| `whitedragon` | 为 AI-pet 导入的角色素材 | 待机呼吸、眨眼、点击回应 |

启动桌宠后，右键桌宠，选择 **设置 → 自定义桌宠**，即可切换这三个预设。菜单中的勾选标记表示当前角色。

## 安装与运行

请先安装 Python 3.11 或更新版本、Node.js 22.12 或更新版本，以及 [FFmpeg](https://ffmpeg.org/)；制作界面还需要 Python 的 Tkinter。macOS 可先在终端运行 `python3 -m tkinter`，检查是否能打开测试窗口。

### Windows

从 GitHub 获取源码后，在项目目录执行：

```powershell
python -m pip install -r requirements.txt
npm ci --prefix runtime
```

双击 `start-pet.bat` 启动已有桌宠。首次启动可能下载 Electron，耗时取决于网络。双击 `start.bat` 打开角色制作界面；制作完成后程序会尝试启动或刷新桌宠。运行窗口不要关闭；需要查看启动信息时使用 `start-pet.bat`。

### macOS（理论上可运行，待实机验证）

从 GitHub 获取源码后，在项目目录的“终端”运行：

```bash
bash setup-macos.command
bash start-pet.command
```

`setup-macos.command` 会检查 Python、Tkinter、Node.js 和 FFmpeg，创建本地 `.venv/`，安装 Python 与 Node 依赖。之后可运行 `bash start.command` 打开角色制作界面。首次启动可能下载与你的 Intel 或 Apple Silicon Mac 对应的 Electron。若希望双击 `.command` 文件启动，先在项目目录运行 `chmod +x *.command`。

macOS 的桌面动画依赖 Electron 播放带透明通道的 WebM；当前未在真实 Mac 上完成三个预设的画面与交互验收。如果遇到黑底，应检查 Electron 视频解码，并参考[上游的 macOS 透明 MOV 素材说明](https://github.com/PC2005-cloud/dsh-pet/blob/main/dsh-pet/README.md)进行转码和播放格式适配。

本项目保存了运行所需的 `runtime/lib/` 构建文件；`runtime/node_modules/` 是本机安装结果，不应提交到仓库。Windows 和 macOS 应分别安装各自平台的依赖，不能直接复制另一台电脑的 `node_modules/`。

## 制作新桌宠

1. Windows 打开 `start.bat`，macOS 运行 `bash start.command`，选择正面、全身、轮廓清楚的 PNG/JPG/WebP 图片。透明 PNG 效果最稳定；纯色背景图片支持自动抠像。三视图可用于准备素材和核对角色一致性，当前界面仍以单张正面图片制作动作。
2. 填写角色名称，确认输出目录。默认目录是 `data/dsh-pet/pet/`。
3. 选择 **本地生成三个基础动作（免费）**，或配置视频 API 后选择 **用视频 API 制作三个动作**。
4. 制作完成后，在桌宠右键菜单 **设置 → 自定义桌宠** 中选择新角色。

本地模式对原图进行轻微形变。视频模式使用阿里云百炼视频模型，生成三段绿幕视频，再自动抠像、裁切、对齐脚底并转换为带透明通道的 WebM。可在程序内保存或清除“视频 API Key”，并通过界面按钮打开[阿里云视频生成相关页面](https://www.aliyun.com/benefit/ai/aistar?clubBiz=subTask..12934056..10274..)。页面可能提供免费额度或免费模型，具体以账号和服务页面为准；生成三个动作也可能产生费用。

视频模式会将角色参考图片提交到视频服务。Windows 使用 DPAPI 将 API Key 保存在本机 `data/api_key.dpapi`；macOS 将 Key 保存在当前用户的系统钥匙串，项目目录不生成密钥文件。仅保存 Key 不会提交视频任务。点击生成按钮后仍会询问确认。下载的视频和任务记录存放在 `data/video-cache/`。

复杂背景和不稳定的绿幕可能导致抠像失败；视频模型也可能改变角色的细节。请在发布角色包前检查三个动作及角色一致性。AI-pet 0.11 的制作界面只生成待机呼吸、眨眼、点击回应。

## 自行添加新动作

0.11 的制作界面固定生成上述三个基础动作；要为已有的自定义桌宠增加其他动作，可以手动扩展角色包。先把新动作制作成 **640×360、带透明通道的 VP9 WebM**（绿幕 MP4 可使用项目中的 `video_postprocess.py` 抠像转换），放入 `data/dsh-pet/pet/<名称>-animation/`。然后编辑同目录下的 `<名称>-config.json`：将文件名去掉 `.webm` 后加入 `animations.idle`，新动作就会参与待机播放；加入 `animations.clicks`，就会参与点击回应。保存配置后退出并重新启动 AI-pet，检查动画是否正确显示、脚底是否对齐。请先备份配置与素材，且不要将新动作加入未准备好对应文件的列表。

## 文件位置

| 内容 | 路径 |
| --- | --- |
| 原版 `dafeiyu` 动画 | `runtime/assets/webm/` |
| `gemini`、`whitedragon` 的透明动画 | `data/dsh-pet/pet/<名称>-animation/` |
| 角色配置 | `data/dsh-pet/pet/<名称>-config.json` |
| 本机导入的原始视频与参考图 | `data/imported-video/<名称>/` |
| 视频 API 任务与下载缓存 | `data/video-cache/` |

若要隐藏某个角色，将其配置里的 `display` 设为 `none`；通常直接通过右键菜单切换更方便。内部目录名、环境变量 `DSH_HOME`、部分 HTTP 路由和协议字段仍沿用 dsh-pet 的技术标识，以保持运行兼容；这些名称不代表本项目的对外名称。

## 来源与许可

AI-pet 新增代码采用 [MIT 许可](LICENSE)。运行核心和 `dafeiyu` 原版动画来自 [dsh-pet 原项目](https://github.com/PC2005-cloud/dsh-pet)；上游代码的版权声明保留在 [runtime/LICENSE](runtime/LICENSE)。上游 README 对动画、提示词、源视频另有“允许开源使用，禁止商用”的说明，并要求二次创作在介绍、展示、分发时附上原作者 GitHub 地址；请阅读[原项目许可说明](https://github.com/PC2005-cloud/dsh-pet#%E8%AE%B8%E5%8F%AF)。

`gemini` 与 `whitedragon` 是本项目导入的角色素材，透明动画随仓库提供。代码的 MIT 许可不自动覆盖角色素材；详情见[角色与素材说明](ASSET_NOTICE.md)。

## 当前版本

AI-pet 0.11 的 Windows 桌面功能已在开发环境验证；macOS 已加入启动脚本和钥匙串支持，理论上可运行，但尚待真实 Mac 上检查窗口、三个预设与动画透明度。云端视频生成需要用户自行配置 API Key。遇到启动或生成问题，请记录终端报错、所选模型和复现步骤；不要上传 API Key 或包含密钥的本机配置文件。
