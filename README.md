# videoMaker 目录说明

判断原则：**源文件与昂贵生成物保留；廉价中间层删了也会自动重跑**。

## 保留（当前项目正在使用，不要删）

| 路径 | 说明 |
|---|---|
| `pipeline/` | 全部构建/起草/生图脚本 |
| `copy/` | 文案源：长视频 `copy/long/script.txt`、短视频 `voiceover.txt` |
| `script/storyboard_narrative.json` | 当前叙事分镜（63 拍 + 字幕表） |
| `assets/long/art/` | 历史插画底图（TITLE/END/S1-S5，已不再被渲染引用，保留存档） |
| `assets/long/scenes/` | 叙事卡点画面（当前 44 张：样片块细化后） |
| `audio/long/voice/` | Piper 配音缓存（生成贵，保留复用） |
| `audio/long/music.wav` | 背景乐（用户提供，混音用） |
| `output/long/long_money_v2_pilot.mp4` | V2 样段（参考） |
| `output/short/ai_3steps_demo.mp4` | 短视频样片（参考） |

## 自动重新生成（看到文件多不用管，删了也能再跑出来）

| 目录/文件 | 重新生成命令 |
|---|---|
| `assets/long/layers/` | `python3 pipeline/build_long.py --frames` 或渲染 |
| `output/preview/`（抽帧） | `python3 pipeline/build_long.py --frames` |
| `audio/long/tmp/`、`audio/short/tmp/` | 渲染/构建时自动 |
| `output/long/vs2_*.mp4`（分块中间） | 渲染时自动 |
| `output/short/scene_S*.mp4`、`concat.mp4` | `python3 pipeline/build.py` |
| `assets/short/`、`audio/short/` | `python3 pipeline/build.py` |

## 常用命令速查

```bash
# 叙事分镜 → 卡点画面 → 抽帧验收
python3 pipeline/write_storyboard.py --check script/storyboard_narrative.json
python3 pipeline/write_storyboard.py --refine   # 拆超长拍（单拍>12s 自动拆半）
python3 pipeline/write_image_art.py --story
python3 pipeline/build_long.py --frames

# 视觉样片（只渲染指定块、跳过语音）
python3 pipeline/build_long.py --blocks 0,1,2,3 --no-tts

# 视觉样片（微软女声 edge-tts，免费无需密钥）
TTS_SOURCE=edge python3 pipeline/build_long.py --blocks 0,1,2

# 长视频渲染（需提权，Piper）
python3 pipeline/build_long.py --pilot    # 样段
python3 pipeline/build_long.py            # 全片
```

生图模型默认 `wan2.7-image`（经济版），可用 `IMAGE_MODEL` 切换为
`wan2.7-image-pro`。

视觉说明：画面不叠加压暗层、vignette 已减弱（全亮）；运镜为明显增强档
（缩放 0.40、视差 ±14px）；阶段页背景 = 后续内容块首张卡点画面（保持
故事连续），不再使用 art/ 抽象底图；无进度条与阶段徽章；字幕为底部单行
（字号自适应，贴近画面底部）。

语音：`TTS_SOURCE=edge` 使用微软 Edge 在线语音（免费、无需密钥，
首次需 `pip install edge-tts`；非官方接口，失效可回退 Piper 或 Azure
正式 API）；默认男声 `zh-CN-YunyangNeural`（成熟专业），`AZURE_VOICE`
可换 `zh-CN-YunxiNeural` 等。

Azure 正式语音（需密钥，免费层 50 万字符/月）：
`TTS_SOURCE=azure`，`.env` 配置 `AZURE_SPEECH_KEY`、`AZURE_REGION`
（可回退 `REST_API_URL` 解析）、`AZURE_VOICE`（声音名，如
`zh-CN-Xiaochen:DragonHDFlashLatestNeural` 成熟知性女声）。与 edge/Piper
共存，随时用 `TTS_SOURCE` 切换。

封面图：`python3 pipeline/write_image_art.py --force --only COVER`
→ `assets/long/cover.png`（16:9 暖色书籍主题、无文字、留白给标题）。

字幕：固定 36px 单行，长句自动拆成连续字幕事件；背景浅色半透明。
