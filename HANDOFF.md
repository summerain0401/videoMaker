# 交接文档（给下一个会话）

> 更新：2026-08-13 ｜ 目标：把「从文案到听书长视频」的项目状态完整交给新会话，避免重复踩坑。

## 1. 项目一句话

本地自动化流水线：文案 → 分镜 → 画面 → 配音 → 合成 → 交付，对标 YouTube 频道《认知书页》的 13–18 分钟听书解读长视频（16:9 横屏，1920x1080/30fps）。仓库只做长视频，按项目制组织：每个项目一个目录（`projects/001_金钱的艺术`、`projects/002_…`），脚本用 `PROJECT`（默认 `001`）/`--project` 定位。短视频已全部移除，今后另开项目。

## 2. 当前状态（先读这个）

- ✅ **目录重组（本轮）**：长视频资产全部迁入 `projects/001_金钱的艺术/`（`input/` 文案与分镜、`assets/` 卡点画面/历史底图、`audio/` 配音缓存与背景乐、`output/` 成片与报告）；新增 `pipeline/proj.py` 统一解析项目路径；短视频代码/素材/文档章节已清除。
- ✅ **M2 文案 AI 化**：`write_long_copy.py`（DeepSeek 五段式完整脚本起草 + 结构校验/回喂重试 + 人工定稿）；当前 `projects/001_金钱的艺术/input/script.txt` 为 AI 起草稿（旧稿备份 `script.txt.bak`）。
- ✅ **M3 画面叙事化**：正文零文字卡、文案交给配音+逐句字幕；`write_storyboard.py` 分镜（19 块 80 拍，`--refine` 拆超长拍）；`write_image_art.py --story` 生成卡点画面到项目 `assets/scenes/`（当前 44 张，覆盖样片块）；引擎检测到分镜即进入叙事模式（删除 JSON 回退文字卡模式）。
- ✅ **视觉样片 v4**：`projects/001_金钱的艺术/output/long_money_v2_visual_sample.mp4`——全亮（无压暗、vignette PI/7）、运镜明显增强（缩放 0.40、视差 ±14）、无进度条/阶段徽章、字幕固定 36px 单行（长句拆连续事件）、片头 00_0/00_1 明亮版。
- ✅ **M4 语音（部分）**：Azure 正式语音已接入（`tts_azure.py`，`TTS_SOURCE=azure`），当前声音 `zh-CN-Xiaochen:DragonHDFlashLatestNeural`（晓辰成熟知性女声）；edge-tts（`tts_edge.py`，免费无密钥）与 Piper（本地男声）保留，三选一随时切换。最近测试样片（块 00–01）用 Azure 晓辰配音，响度 -14.3 dB。
- ✅ **生图基调控制**：提示词分层（不变底线 + 项目 `visual_style` 变体 + 负面清单）；`--tone-check` 输出风险报告（001 现有 44 张中 19 张被标记，其中 09_0/07_0/00_6 客观偏暗）；`write_storyboard.py --warm` 暖化重写分镜提示词；`--force` 重绘自动追加提亮指令。
- ✅ **2D Q 版流水线**：`write_chibi_prompts.py`（LLM 按块批量解析：旁白驱动情绪映射 + 角色库 + 装配英文 final prompt，输出 `input/storyboard_output.json`）；`write_image_art.py --chibi`（`negative_prompt` 全禁文字/贴纸/图表）；`assets/characters.json` 全局角色库 + 项目 `input/characters.json` 覆盖扩展。
- ✅ **样片修复（本轮）**：画面无文字（文字留给字幕与后期）；情绪以口播为准（自动矛盾检测回喂）；块内卡点硬切 + 块间 0.3s 方向型转场（去 dissolve 防叠影）；构图主体上 2/3 + 底部 1/3 字幕安全区。块 0–1 样片已用新规则重绘重渲（65.87s）。
- ✅ **v2.0 合成层（本轮）**：全屏铺满（禁白边 + 底部 15% 渐变遮罩替代实色底条）；字幕思源黑体 Heavy 48px 粗体描边 + 金额黄/情绪珊瑚红高亮；Ken Burns 5% 轻微档（修复 `zoompan d=1` 静止 bug，t1→t5 帧差 10.36 已验证）；情绪主题背景色板（冷灰蓝/暖杏金/中性，warm 6:cool 11 分布）；收尾 CTA 口播兜底强制 young_pro。
- ✅ **v3 精修（本轮）**：字幕按标点切句 + 避头尾 + ≤15 字/屏 + 事件硬切换（无重影）；CTA 强制积极蓄势表情；对比拍双角色（`secondary_character_id`，frugal_girl+stressed_worker）；底部实条彻底移除（full-bleed + 仅渐变遮罩）；运镜统一 1.0→1.08（帧差 22.39）；关键词 SFX 自动挂载（coin/calc，ffmpeg 合成，`SFX=0` 关闭）。
- ✅ **封面移除（本轮）**：封面工具与素材已全部移除，封面由独立 Agent 负责（本仓库不再包含封面相关代码/产物）。
- ⏳ **待办**：001 暖化重绘（待你从 tone_report.md 勾选，推荐至少 09_0/07_0/00_6）；渲染更长样片/全片；补全剩余卡点画面（约 58 拍未生成）；主角一致性（参考图图生图）；节奏对齐/提示音效。

## 3. 环境速查

- **必须用捆绑 Python**：`/Users/spring/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`
- **ffmpeg 8.1**（`/opt/homebrew/bin/ffmpeg`）：无 drawtext/libass，文字全部 Pillow 渲染 PNG 再 overlay。
- **项目定位**：环境变量 `PROJECT`（默认 `001`），脚本 `--project` 可覆盖；匹配 `projects/{id}_*` 前缀，改名后缀不影响。
- **TTS 三选一**（环境变量 `TTS_SOURCE`）：`piper`（本地男声，需提权）/ `edge`（微软 Edge 在线，免费无密钥，依赖 `edge-tts` 库）/ `azure`（正式 API，需密钥）。
- **密钥与配置（项目根 .env，已 gitignore）**：`DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`IMAGE_MODEL`（默认 wan2.7-image）、`AZURE_SPEECH_KEY`、`AZURE_REGION`（或 `REST_API_URL` 解析区域）、`AZURE_VOICE`。
- **注意**：`.env` 解析器已容忍 `KEY = 值` 的空格写法，但新配置建议统一无空格。

## 4. 长视频流水线（项目制）

```bash
# 分镜 → 卡点画面 → 抽帧（默认项目 001）
python3 pipeline/write_storyboard.py
python3 pipeline/write_storyboard.py --refine        # 拆超长拍（>12s）
python3 pipeline/write_image_art.py --story          # 生成卡点画面（wan2.7-image）
python3 pipeline/build_long.py --frames              # 抽帧验收（m3n_*.jpg）

# 渲染（声音三选一）
TTS_SOURCE=azure python3 pipeline/build_long.py --blocks 0,1   # Azure 晓辰
TTS_SOURCE=edge  python3 pipeline/build_long.py --blocks 0,1   # Edge 男声
python3 pipeline/build_long.py --blocks 0,1 --no-tts           # 静音快速看画面
python3 pipeline/build_long.py --pilot / 全片

# 基调质检与暖化重绘
python3 pipeline/write_image_art.py --tone-check                       # 风险报告
python3 pipeline/write_storyboard.py --warm --check                    # 阴郁拍清单
python3 pipeline/write_storyboard.py --warm --beats 09_0 07_0          # 暖化提示词
python3 pipeline/write_image_art.py --story --force --beats 09_0 07_0  # 重绘

# 2D Q 版流水线
python3 pipeline/write_chibi_prompts.py --blocks 0                     # 试点解析+装配
python3 pipeline/write_chibi_prompts.py --check                        # 离线校验
python3 pipeline/write_image_art.py --chibi --beats 00_0 00_1          # Q 版生图
python3 pipeline/write_image_art.py --chibi --force                    # 全量覆盖重绘

# 新项目示例
PROJECT=002 python3 pipeline/write_long_copy.py --book 《书名》 --author 作者
```

- 产物：项目 `output/long_money_v2_visual_sample.mp4`、全片 `long_money_v2.mp4`、`long_summary.json`、`storyboard_long.csv`。
- 字幕字体：`assets/fonts/SourceHanSansCN-Heavy.otf`（思源黑体 Heavy，OFL 免费商用；缺失回退 Hiragino W6）。
- 音效：`audio/tmp/sfx_coin.wav` / `sfx_calc.wav`（ffmpeg lavfi 合成缓存，可删重建）。
- 画面命名：项目 `assets/scenes/{块:02d}_{拍}.png`；阶段页用「后续内容块首张卡点画面」做背景；项目 `assets/art/` 为历史底图存档，渲染不再引用。
- 封面：由独立 Agent 负责，本仓库不包含封面工具与素材。
- 背景乐：`music.wav`（或 mp3/m4a）放项目 `audio/` 自动混音（0.25 音量 + loudnorm -14 LUFS）。

## 5. 文案格式（项目 input/script.txt）

`# TITLE`（书名/钩子/voice）、`# PHASE 01–05`（阶段页）、`# CARD`/`# QUOTE`/`# TABLE 左 | 右`/`# STEPS`（内容块 + voice：整段口播）、`# END`。改文案时保持结构一致，时长由配音自动计算。

## 6. 已知坑与经验

- `.env` 等号两侧空格可容忍（解析器已修），新配置建议无空格。
- 配音缓存名 = 配置 + 文本哈希（如 `blk00_azurezh-CN-Xiaochen:DragonHDFlashLatestNeural_ae922fb9.wav`），换文案/音色不会误用旧缓存；过期缓存可删。
- edge-tts 为非官方接口，若失效回退 Piper 或 Azure；Azure 免费层输出限 mp3（适配器已转 wav），密钥/区域缺失会明确报错。
- 生图默认 `wan2.7-image`（经济版）；`IMAGE_MODEL=wan2.7-image-pro` 可切旗舰。
- zoompan 输出尺寸必须偶数（1920x1080）；禁用 rotate / 逐帧 noise（极慢）。
- 分镜文件迁移用两阶段（临时名）防覆盖；`--refine` 只拆已有卡点图的拍。
- 渲染耗时：块 00 约 5–8 分钟、全片约 40–75 分钟；`--frames` 秒级出抽帧。
- 目录重组后旧路径（`copy/long/`、`assets/long/`、`audio/long/`、`output/long/`、`script/`）已废弃；如需回看旧提交用 `git show`。

## 7. 待办（按优先级）

1. 用 Azure 声音渲染更长样片（块 00–03 或更多）确认节奏与运镜。
2. 001 全量 2D Q 版重绘：块 0/2 已跑通，等其余块解析+装配（17 块）+ `--chibi --force` 重绘全部 74 张 → `--tone-check` 复检 → 全片渲染。
3. 旧暖色中文模式 `--story` 保留为回退；`assets/art/` 历史底图不动。
4. 主角一致性（参考图图生图）——接口已预留（`write_image_art` 的 `ref_images`）。
5. 封面（独立 Agent 另行开发，本仓库不维护）。
6. 节奏对齐/提示音效（BGM `music.wav` 已随项目迁移，音量 0.25）。
7. 响度微调（当前 -14.3 dB 已达标）。

## 8. 关键决策记录

- 规格：16:9 1920x1080、30fps、13–18 分钟目标；五段式 3800–4500 字。
- 视觉：画面叙事优先（人物+故事+卡点），正文零文字卡；暖色温馨明亮；全亮无压暗；运镜明显增强；无进度条/阶段徽章；字幕 36px 单行贴底。
- 语音：Azure 正式语音（晓辰成熟知性女声）为当前主用；edge-tts 免费备选；Piper 本地兜底。
- 生图：通义万相 wan2.7-image（经济版）；插画底图 art/ 停止引用（历史资产）。
- 基调：提示词分层（不变底线 + 项目 visual_style 变体 + 负面清单）；`--tone-check` 亮度<150/暖度<10/暗部占比>25% 判定风险，人工勾选后暖化重绘。
- 2D Q 版：画面无文字/贴纸/图表（文字留给字幕与后期）；情绪以旁白为准（矛盾自动检测）；角色库全局+项目双层；构图底部 1/3 字幕安全区；块内硬切、块间 0.3s 方向型转场。
- v2.0：底部 15% 渐变遮罩（0→0.4）替代字幕灰条；字幕 48px Heavy + 关键词高亮；Ken Burns 5%（`KENZOOM` 可调）；情绪主题背景色板（`tone.theme_for`）；CTA 收尾兜底。
- v3：字幕按标点切句/避头尾/≤15字/硬切换；CTA 积极表情；对比双角色；full-bleed 无底部实条；运镜 1.0→1.08；关键词 SFX（coin/calc）。
- 目录：项目制（数字前缀 + 中文名），输入/中间产物/产出分层；短视频移出本仓库另开项目。
- 封面：由独立 Agent 负责，本仓库不包含封面工具与素材。
- 运营：标题公式/灵魂提问已入文案结构（标题公式参考 report.pdf）。

## 9. 参考文件

- `PROJECT_PLAN.md`、`README.md`、`docs/长视频工作流.md`、`report.pdf`（频道分析）
- `projects/001_金钱的艺术/input/script.txt`（当前口播稿）、`input/storyboard_narrative.json`（分镜）
- `projects/001_金钱的艺术/output/long_money_v2_visual_sample.mp4`（最新样片）
