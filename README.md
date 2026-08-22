# videoMaker（长视频制作流水线）

本仓库只做 **16:9 听书解读长视频**（1920x1080 / 30fps / H.264+AAC / -14 LUFS）。
生产按项目组织：每个项目一个目录（数字前缀 + 中文名），内部按「输入 /
中间产物 / 产出」分层；脚本用 `PROJECT` 环境变量（默认 `001`）或
`--project` 参数定位项目。当前有 `001_金钱的艺术` 与 `002_百万富翁快车道`
两个进行中项目；未显式指定时仍默认 `001`。

## 项目目录结构

```
projects/001_金钱的艺术/
├── project.json    # 元数据（id/title/author/status）
├── input/          # brief/script、叙事分镜、最终输出分镜、Codex 候选资产
├── assets/         # scenes/（卡点画面）、art/（历史底图存档）、layers/（渲染中间层）
├── audio/          # voice/（配音缓存）、music.wav（背景乐）、tmp/（合成中间）
└── output/         # 成片 mp4、long_summary.json、storyboard_long.csv、preview/（抽帧）
```

判断原则：**源文件与昂贵生成物保留**（文案、分镜、卡点画面、配音缓存、
背景乐、成片）；**廉价中间层删了也会自动重跑**（layers/、preview/、
tmp/、vs2_* 分块），已由 `.gitignore` 排除，不入版本库。

## 默认：Codex 原生制作（无需 API 密钥）

日常新片在 Codex 中调用 `$video-maker-production`。技能使用 ChatGPT Plus / Codex
的文本能力和内置 ImageGen，不设置 `OPENAI_API_KEY`，也不会调用 OpenAI API。它会以
可恢复的 run 保存候选文案、分镜和图片；文案定稿、分镜提升、图片替换均须人工确认。

本地接口只做路径、状态与离线校验：

```bash
# 一次制作任务（默认项目 001）；输出 run_id 和所有候选路径
python3 pipeline/codex_jobs.py init
python3 pipeline/codex_jobs.py status <run_id>

# Codex 写入候选资产后，由技能或人工执行
python3 pipeline/codex_jobs.py verify-copy <run_id>
python3 pipeline/codex_jobs.py promote <run_id> copy
python3 pipeline/codex_jobs.py verify-storyboard <run_id>
python3 pipeline/codex_jobs.py promote <run_id> storyboard
# 叙事分镜确认后，生成并校验最终版 storyboard_output.json
python3 pipeline/write_chibi_prompts.py --from-plan <codex_output_plan.json> --out <candidate_storyboard_output.json>
python3 pipeline/codex_jobs.py verify-output <run_id>
python3 pipeline/codex_jobs.py promote <run_id> output
python3 pipeline/codex_jobs.py image-targets <run_id> --beats 00_0 00_1
python3 pipeline/codex_jobs.py verify-images <run_id>
python3 pipeline/write_image_art.py --tone-check --scene-dir <candidate_images_dir>
python3 pipeline/codex_jobs.py promote <run_id> images
```

候选 JSON、候选图片和任务状态均不入库。`promote` 默认拒绝覆盖正式资产；明确要替换
已有文件时才附加 `--replace`，并会先保留带 run_id 的备份。

## 常用命令速查

```bash
# 叙事分镜 → 卡点画面 → 抽帧验收
python3 pipeline/write_storyboard.py --check projects/001_金钱的艺术/input/storyboard_narrative.json
python3 pipeline/write_storyboard.py --refine        # 拆超长拍（单拍>12s 自动拆半）
python3 pipeline/write_image_art.py --story          # 生成卡点画面
python3 pipeline/build_long.py --frames              # 快速抽帧（跳过语音与合成）

# 视觉样片（只渲染指定块、跳过语音）
python3 pipeline/build_long.py --blocks 0,1,2,3 --no-tts

# 画面可读性质检（亮度/暗部）与项目风格变体
python3 pipeline/write_image_art.py --tone-check                     # 风险报告 → output/tone_report.md
python3 pipeline/write_image_art.py --story --force --beats 09_0 07_0  # 保留色彩叙事，仅提升可读性

# 最终输出分镜（默认 Codex 原生：本地语义计划 + 角色库 + 英文 Prompt 装配）
python3 pipeline/write_chibi_prompts.py --from-plan output_plan.json
python3 pipeline/write_chibi_prompts.py --check    # 离线校验
python3 pipeline/write_image_art.py --chibi --force --beats 00_0 00_1  # 2D Q 版生图

# 长视频渲染（Piper 需提权；可用 TTS_SOURCE=edge/azure 切换）
python3 pipeline/build_long.py --pilot               # 样段
python3 pipeline/build_long.py                       # 全片
TTS_SOURCE=azure python3 pipeline/build_long.py --blocks 0,1

# 项目切换（新项目：PROJECT=002 … 或 --project 002）
PROJECT=002 python3 pipeline/write_long_copy.py --book 《书名》 --author 作者
```

文档职责：本文件负责入口与架构；`docs/长视频工作流.md` 负责操作细节；
`HANDOFF.md` 只记录当前项目状态；`PROJECT_PLAN.md` 只记录里程碑与路线图。

## 关键说明

- **画面叙事**：正文不渲染文字卡，文案由配音 + 底部逐句字幕承载；每块
  口播切成 3-5 个卡点，每个卡点一张「插画叙事」画面（人物+故事）。
- **视觉**：画面 1920×1080 full-bleed；运镜统一 1.0→1.08、面部锚点
  (50%,35%) 与 X 轴 2.5% 缓移；阶段页沿用后续内容块首张卡点画面；无进度条、
  阶段徽章或底部实条；字幕为思源 Heavy 48px、单屏 ≤15 字并带明黄关键词高亮。
- **API 后备**：DeepSeek 与万相命令及 `.env` 密钥均完整保留；只有明确执行
  `write_long_copy.py --provider deepseek`、`write_storyboard.py` 或
  `write_image_art.py` 时才会调用这些外部服务。默认 Codex 流程不读它们。
- **基调控制**：提示词分层 = 拍提示词 + 不变底线（主体可读、曝光均衡、禁止文字/水印）+
  项目 `visual_style` 变体（`project.json`，防视频间雷同）+ 负面清单；色彩与天气服务
  叙事，可使用冷暖与中性色。`--tone-check` 仅按亮度与暗部占比报告风险；`--force`
  重绘只提升可读性，不改写既定色彩叙事。
- **最终输出分镜**：`storyboard_narrative.json` 只负责叙事节奏与句子覆盖；Codex
  将角色、英文动作、情绪和 segment 写成候选本地计划，
  `write_chibi_prompts.py --from-plan` 装配为 `storyboard_output.json`。该文件才是
  默认图片阶段的唯一正式输入；未带 `--from-plan` 的 DeepSeek 解析仅是 API 后备。
- **转场**：块内卡点硬切（Ken Burns 运镜保留），块间 0.3s 方向型 xfade
  （不用 dissolve/fade 家族，避免人脸叠影）。
- **V5 合成引擎**：块内硬切、块间方向型 xfade；字幕分词、词组保护、明黄高亮
  弹跳；对比拍严格二人制；coin/calc/reveal 三类 SFX；素材约定
  `audio/music_seg{1,2,3}.{mp3,wav}`（开场
  Lofi / 理论新古典 / 总结原声，缺失段回退 `music.wav`）；段边界按拍 segment
  （hook/insight/action，LLM 精标 + 关键词兜底）自动计算；混音——BGM 基准
  -16dB、人声段 sidechaincompress 避让 6–9dB（release 0.8s 平滑回升）、
  EQ 1k–3.5k 下压 2.5dB + lowpass 8k、段间 0.3s 淡入淡出。
- **语音**：`TTS_SOURCE=piper|edge|azure` 三选一；当前主用 Azure 晓辰
  成熟知性女声（`zh-CN-Xiaochen:DragonHDFlashLatestNeural`），`.env` 配
  `AZURE_SPEECH_KEY` / `AZURE_REGION` / `AZURE_VOICE`。
- **封面**：由独立 Agent 负责，本仓库不包含封面工具与素材。
- **背景乐**：优先三段素材，缺段回退 `music.wav`（或 mp3/m4a）；基准
  `volume=0.16`，再做 ducking/EQ 与 loudnorm -14 LUFS；完全不放则纯人声。
