# 交接文档（给下一个会话）

> 更新：2026-08-12 ｜ 目标：把「从文案到听书长视频」的项目状态完整交给新会话，避免重复踩坑。

## 1. 项目一句话

本地自动化流水线：文案 → 配音 → 画面 → 合成 → 交付，对标 YouTube 频道《认知书页》的 13–18 分钟听书解读长视频（16:9 横屏）。第一条《金钱的艺术》已迭代到「画面叙事 + Azure 正式语音」样片阶段。

## 2. 当前状态（先读这个）

- ✅ **M2 文案 AI 化**：`write_long_copy.py`（DeepSeek 五段式完整脚本起草 + 结构校验/回喂重试 + 人工定稿）；当前 `copy/long/script.txt` 为 AI 起草稿（旧手写稿备份 `script.txt.bak`）。
- ✅ **M3 画面叙事化**：正文零文字卡、文案交给配音+逐句字幕；`write_storyboard.py` 分镜（19 块 80 拍，`--refine` 拆超长拍）；`write_image_art.py --story` 生成卡点画面到 `assets/long/scenes/`（当前 44 张，覆盖样片块）；引擎检测到分镜即进入叙事模式（删除 JSON 回退文字卡模式）。
- ✅ **视觉样片 v4**：`output/long/long_money_v2_visual_sample.mp4`——全亮（无压暗、vignette PI/7）、运镜明显增强（缩放 0.40、视差 ±14）、无进度条/阶段徽章、字幕固定 36px 单行（长句拆连续事件）、片头 00_0/00_1 明亮版、封面图 `assets/long/cover.png`。
- ✅ **M4 语音（部分）**：Azure 正式语音已接入（`tts_azure.py`，`TTS_SOURCE=azure`），当前声音 `zh-CN-Xiaochen:DragonHDFlashLatestNeural`（晓辰成熟知性女声）；edge-tts（`tts_edge.py`，免费无密钥）与 Piper（本地男声）保留，三选一随时切换。最近测试样片（块 00–01）用 Azure 晓辰配音，响度 -14.3 dB。
- ⏳ **待办**：渲染更长样片/全片；补全剩余卡点画面（约 58 拍未生成）；主角一致性（参考图图生图）；封面标题文字；BGM 混音；节奏对齐/提示音效。

## 3. 环境速查

- **必须用捆绑 Python**：`/Users/spring/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`
- **ffmpeg 8.1**（`/opt/homebrew/bin/ffmpeg`）：无 drawtext/libass，文字全部 Pillow 渲染 PNG 再 overlay。
- **TTS 四选一**（环境变量 `TTS_SOURCE`）：`piper`（本地男声，需提权）/ `edge`（微软 Edge 在线，免费无密钥，依赖 `edge-tts` 库）/ `azure`（正式 API，需密钥）/ `system`（系统 say）。
- **密钥与配置（项目根 .env，已 gitignore）**：`DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`IMAGE_MODEL`（默认 wan2.7-image）、`AZURE_SPEECH_KEY`、`AZURE_REGION`（或 `REST_API_URL` 解析区域）、`AZURE_VOICE`。
- **注意**：`.env` 解析器已容忍 `KEY = 值` 的空格写法，但新配置建议统一无空格。

## 4. 两条流水线

### 短视频（旧，保留）
- 入口 `pipeline/build.py`；文案源 `copy/voiceover.txt`；产物 `output/short/ai_3steps_demo.mp4`；素材 `assets/short/`、音频 `audio/short/`。

### 长视频 V2（主攻，叙事模式）

```bash
# 分镜 → 卡点画面 → 抽帧
python3 pipeline/write_storyboard.py
python3 pipeline/write_storyboard.py --refine        # 拆超长拍（>12s）
python3 pipeline/write_image_art.py --story          # 生成卡点画面（wan2.7-image）
python3 pipeline/build_long.py --frames              # 抽帧验收（m3n_*.jpg）

# 渲染（声音三选一）
TTS_SOURCE=azure python3 pipeline/build_long.py --blocks 0,1   # Azure 晓辰
TTS_SOURCE=edge  python3 pipeline/build_long.py --blocks 0,1   # Edge 男声
python3 pipeline/build_long.py --blocks 0,1 --no-tts           # 静音快速看画面
python3 pipeline/build_long.py --pilot / 全片
```

- 产物：`output/long/long_money_v2_visual_sample.mp4`、`output/long/long_money_v2.mp4`（全片）、`long_summary.json`、`script/storyboard_long.csv`。
- 画面命名：`assets/long/scenes/{块:02d}_{拍}.png`；阶段页用「后续内容块首张卡点画面」做背景；`assets/long/art/` 已不再被渲染引用（保留存档）。
- 封面图：`python3 pipeline/write_image_art.py --force --only COVER` → `assets/long/cover.png`。

## 5. 文案格式（copy/long/script.txt）

`# TITLE`（书名/钩子/voice）、`# PHASE 01–05`（阶段页）、`# CARD`/`# QUOTE`/`# TABLE 左 | 右`/`# STEPS`（内容块 + voice：整段口播）、`# END`。改文案时保持结构一致，时长由配音自动计算。

## 6. 已知坑与经验

- `.env` 等号两侧空格可容忍（解析器已修），新配置建议无空格。
- 配音缓存名 = 配置 + 文本哈希（如 `blk00_azurezh-CN-Xiaochen:DragonHDFlashLatestNeural_ae922fb9.wav`），换文案/音色不会误用旧缓存；过期缓存可删。
- edge-tts 为非官方接口，若失效回退 Piper 或 Azure；Azure 免费层输出限 mp3（适配器已转 wav），密钥/区域缺失会明确报错。
- 生图默认 `wan2.7-image`（经济版）；`IMAGE_MODEL=wan2.7-image-pro` 可切旗舰。
- zoompan 输出尺寸必须偶数（1920x1080）；禁用 rotate / 逐帧 noise（极慢）。
- 分镜文件迁移用两阶段（临时名）防覆盖；`--refine` 只拆已有卡点图的拍。
- 渲染耗时：块 00 约 5–8 分钟、全片约 40–75 分钟；`--frames` 秒级出抽帧。

## 7. 待办（按优先级）

1. 用 Azure 声音渲染更长样片（块 00–03 或更多）确认节奏与运镜。
2. 补全剩余卡点画面（约 58 拍，wan2.7-image，成本低）后跑全片。
3. 主角一致性（参考图图生图）——接口已预留（`write_image_art` 的 `ref_images`）。
4. 封面标题文字 / 视频标题（标题公式见 report.pdf）。
5. BGM 混音（`audio/long/music.wav` 已存在，音量 0.25）；节奏对齐/提示音效。
6. 响度微调（当前 -14.3 dB 已达标）。

## 8. 关键决策记录

- 规格：16:9 1920x1080、30fps、13–18 分钟目标；五段式 3800–4500 字。
- 视觉：画面叙事优先（人物+故事+卡点），正文零文字卡；暖色温馨明亮；全亮无压暗；运镜明显增强；无进度条/阶段徽章；字幕 36px 单行贴底。
- 语音：Azure 正式语音（晓辰成熟知性女声）为当前主用；edge-tts 免费备选；Piper 本地兜底。
- 生图：通义万相 wan2.7-image（经济版）；插画底图 art/ 停止引用（历史资产）。
- 运营：标题公式/灵魂提问已入文案结构；封面已生成，标题文字待做。

## 9. 参考文件

- `PROJECT_PLAN.md`、`README.md`、`report.pdf`（频道分析）
- `copy/long/script.txt`（当前口播稿）、`script/storyboard_narrative.json`（分镜）
- `output/long/long_money_v2_visual_sample.mp4`（最新样片）
