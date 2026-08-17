# videoMaker（长视频制作流水线）

本仓库只做 **16:9 听书解读长视频**（1920x1080 / 30fps / H.264+AAC / -14 LUFS）。
生产按项目组织：每个项目一个目录（数字前缀 + 中文名），内部按「输入 /
中间产物 / 产出」分层；脚本用 `PROJECT` 环境变量（默认 `001`）或
`--project` 参数定位项目。当前项目：`projects/001_金钱的艺术`。

## 项目目录结构

```
projects/001_金钱的艺术/
├── project.json    # 元数据（id/title/author/status）
├── input/          # brief.md、script.txt(.bak)、draft_*.txt、storyboard_narrative.json
├── assets/         # scenes/（卡点画面）、art/（历史底图存档）、layers/（渲染中间层）
├── audio/          # voice/（配音缓存）、music.wav（背景乐）、tmp/（合成中间）
└── output/         # 成片 mp4、long_summary.json、storyboard_long.csv、preview/（抽帧）
```

判断原则：**源文件与昂贵生成物保留**（文案、分镜、卡点画面、配音缓存、
背景乐、成片）；**廉价中间层删了也会自动重跑**（layers/、preview/、
tmp/、vs2_* 分块），已由 `.gitignore` 排除，不入版本库。

## 常用命令速查

```bash
# 叙事分镜 → 卡点画面 → 抽帧验收
python3 pipeline/write_storyboard.py --check projects/001_金钱的艺术/input/storyboard_narrative.json
python3 pipeline/write_storyboard.py --refine        # 拆超长拍（单拍>12s 自动拆半）
python3 pipeline/write_image_art.py --story          # 生成卡点画面
python3 pipeline/build_long.py --frames              # 快速抽帧（跳过语音与合成）

# 视觉样片（只渲染指定块、跳过语音）
python3 pipeline/build_long.py --blocks 0,1,2,3 --no-tts

# 生图基调控制（暖色底线 + 阴郁风险质检）
python3 pipeline/write_image_art.py --tone-check                     # 风险报告 → output/tone_report.md
python3 pipeline/write_storyboard.py --warm --check                  # 列出阴郁风险拍（不调 API）
python3 pipeline/write_storyboard.py --warm --beats 09_0 07_0        # 暖化指定拍提示词（DeepSeek）
python3 pipeline/write_image_art.py --story --force --beats 09_0 07_0  # 暖化重绘

# 2D Q 版插画流水线（LLM 解析 + 角色库 + 英文 Prompt 装配 + 负面词）
python3 pipeline/write_chibi_prompts.py            # 全量解析+装配（按块批量）
python3 pipeline/write_chibi_prompts.py --blocks 0  # 试点只解析块 0
python3 pipeline/write_chibi_prompts.py --check    # 离线校验
python3 pipeline/write_image_art.py --chibi --force --beats 00_0 00_1  # 2D Q 版生图

# 长视频渲染（Piper 需提权；可用 TTS_SOURCE=edge/azure 切换）
python3 pipeline/build_long.py --pilot               # 样段
python3 pipeline/build_long.py                       # 全片
TTS_SOURCE=azure python3 pipeline/build_long.py --blocks 0,1

# 项目切换（新项目：PROJECT=002 … 或 --project 002）
PROJECT=002 python3 pipeline/write_long_copy.py --book 《书名》 --author 作者
```

详细流程见 `docs/长视频工作流.md`；交接与规划见 `HANDOFF.md`、
`PROJECT_PLAN.md`。

## 关键说明

- **画面叙事**：正文不渲染文字卡，文案由配音 + 底部逐句字幕承载；每块
  口播切成 3-5 个卡点，每个卡点一张「插画叙事」画面（人物+故事）。
- **视觉**：画面不压暗、vignette 减弱（全亮）；运镜明显增强档（缩放
  0.40、视差 ±14px）；阶段页背景 = 后续内容块首张卡点画面（故事连续）；
  无进度条与阶段徽章；字幕固定 36px 单行、贴底、浅色底。
- **生图**：默认 `wan2.7-image`（经济版），`IMAGE_MODEL` 可切
  `wan2.7-image-pro`；密钥走 `.env` 的 `DASHSCOPE_API_KEY`。
- **基调控制**：提示词分层 = 拍提示词 + 不变底线（暖色明亮、禁止冷色/灰暗）+
  项目 `visual_style` 变体（`project.json`，防视频间雷同）+ 负面清单；
  `--tone-check` 按亮度/暖度/暗部占比输出风险报告，勾选后 `--warm --beats`
  暖化提示词再重绘；`--force` 重绘自动追加提亮暖化指令。
- **2D Q 版**：`write_chibi_prompts.py` 按块批量 LLM 解析（旁白驱动情绪、
  主题一致性、角色库 `assets/characters.json` + 项目 `input/characters.json`
  覆盖扩展）→ 装配英文 final prompt（2D chibi 底模 + 暖色 + 变体 + 角色 +
  动作 + 景别 + 16:9）；画面一律无文字/贴纸/图表（负面词全禁，文字留给引擎
  字幕与后期）；构图固定主体上 2/3、底部 1/3 字幕安全区。
- **转场**：块内卡点硬切（Ken Burns 运镜保留），块间 0.3s 方向型 xfade
  （不用 dissolve/fade 家族，避免人脸叠影）。
- **v2.0 合成层**：画面 1920×1080 全屏铺满（禁白边/相框，底部 15% 半透明
  渐变遮罩替代实色底条）；字幕思源黑体 Heavy 48px 粗体 + 描边投影 +
  金额黄色/情绪转折珊瑚红高亮；Ken Burns 5% 轻微缓推（修复 d=1 静止 bug）；
  情绪主题背景色板（焦虑/困境→冷灰蓝，启发/希望→暖杏金，中性奶油）；
  收尾 CTA 口播强制绑定核心主角。
- **v3 精修**：字幕按标点切句 + 避头尾法则 + 单屏 ≤15 字直接切屏 + 事件
  硬切换（无淡出重叠）；CTA 收尾强制积极自信蓄势待发表情；对比拍强制两套
  不同角色（`secondary_character_id`，防撞脸）；底部彻底无实条（full-bleed，
  仅渐变遮罩）；运镜统一 1.0→1.08 缓推；关键词音效自动挂载
  （工资到账→金币叮、打车/算账→计算器键音，ffmpeg 合成，`SFX=0` 关闭）。
- **语音**：`TTS_SOURCE=piper|edge|azure` 三选一；当前主用 Azure 晓辰
  成熟知性女声（`zh-CN-Xiaochen:DragonHDFlashLatestNeural`），`.env` 配
  `AZURE_SPEECH_KEY` / `AZURE_REGION` / `AZURE_VOICE`。
- **封面**：由独立 Agent 负责，本仓库不包含封面工具与素材。
- **背景乐**：`music.wav`（或 mp3/m4a）放入项目 `audio/` 即自动混音
  （0.25 音量 + loudnorm -14 LUFS）；不放则纯人声。
