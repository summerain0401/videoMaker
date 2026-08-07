# AI 实战 · 三步路径（样片文案）

## 定位

- 主题：AI 教育 / AI 实战
- 目标观众：想学 AI 但不知从哪开始的普通人
- 视频形态：9:16 竖屏（1080x1920），约 45 秒，动态排版 + 口播
- 核心主张：AI 不是学出来的，是用出来的

## 结构（钩子 → 三步 → 号召）

1. 开场钩子（S1）：抛出痛点「想学 AI 不知从哪开始」，给出承诺「三步实战路径」。
2. 第一步（S2）：选对场景——从写周报、做表格、做 PPT 等真实任务切入。
3. 第二步（S3）：提问公式——角色 + 任务 + 细节 + 要求。
4. 第三步（S4）：沉淀模板——把固定流程变成自己的 AI 模板库。
5. 结尾（S5）：金句「AI 不是学出来的，是用出来的」+ 关注引导。

## 迭代方向

- 换音色 / 语速：运行前设置环境变量 `TTS_VOICE=语音名`、`TTS_RATE=语速`；
  例如 `TTS_VOICE=Tingting python3 pipeline/build.py`。系统里的中文音色
  （含苹果「个人语音」录制的专属音色）都可直接选用。
- 换文案：直接改写 `copy/voiceover.txt`，分镜表与字幕会自动重算。
- 换配色：调整 `pipeline/build.py` 中每个场景的 `grad` 与 `accent`。
- 加 AI 图片素材：把生成的 9:16 竖屏底图命名为
  `assets/ai/bg_S1.png` … `assets/ai/bg_S5.png`，重跑流水线即自动使用，
  无需改动其他环节。

## 文案工作流（AI 起草 + 人工定稿）

文案是整个视频的内容基础，推荐这样协作：

1. 在 `copy/brief.md` 填写本次主题与要求（模板已就绪）。
2. 运行 `python3 pipeline/write_copy.py --provider deepseek`（或 `kimi`），
   AI 生成草稿到 `copy/draft_时间戳.txt`，并自动做格式与时长检查。
3. 人工修改草稿——这是最值得花时间的环节，定稿质量决定成片质量。
4. 确认后运行 `python3 pipeline/write_copy.py --provider deepseek --accept`，
   把定稿同步到 `copy/voiceover.txt`（旧版自动备份）。
5. 运行 `python3 pipeline/build.py` 生成成片。

平台与密钥：DeepSeek 用 `DEEPSEEK_API_KEY`，Kimi 用 `KIMI_API_KEY`；
模型名可用 `--model` 覆盖，接口地址可用环境变量 `COPY_BASE_URL` 覆盖。

## 长视频文案工作流（V2 · AI 起草 + 人工定稿）

主攻方向（16:9 听书解读长视频，五段式标记格式）用独立的起草工具：

1. 在 `copy/long/brief.md` 填写本次书目、痛点与素材要点（模板已就绪）。
2. 运行 `python3 pipeline/write_long_copy.py --provider deepseek`，
   DeepSeek 起草五段式完整脚本（含 # CARD / # QUOTE / # TABLE / # STEPS
   视觉标记与 voice：口播）到 `copy/long/draft_时间戳.txt`，自动做结构校验，
   不通过会回喂模型重试；密钥自动读取项目根 `.env` 的 `DEEPSEEK_API_KEY`。
3. 人工审阅修改草稿——重点核对书中事实，定稿质量决定成片质量。
4. 确认后运行 `python3 pipeline/write_long_copy.py --accept`，
   严格校验通过后定稿到 `copy/long/script.txt`（旧版自动备份 script.txt.bak）。
5. 后续出片：`python3 pipeline/build_long.py --pilot`（样段）/ 全片。

离线检查任意文案文件：`python3 pipeline/write_long_copy.py --check 文件路径`。

## 长视频 AI 插画底图（M3）

引擎按 `assets/long/art/` 下的文件自动加载插画底图（存在即用，缺失回退
程序化质感底图）：`TITLE.png`、`END.png`、`S1.png`…`S5.png`（对应五个阶段）。

```bash
# 补齐缺失槽位（密钥自动读 .env 的 DASHSCOPE_API_KEY）
python3 pipeline/write_image_art.py
python3 pipeline/write_image_art.py --force        # 全部重新生成
python3 pipeline/write_image_art.py --only S1      # 只生成指定槽位
```

环境变量：`DASHSCOPE_API_KEY`（必填）、`DASHSCOPE_BASE_URL`（默认
`https://dashscope.aliyuncs.com`，可用百炼业务空间专属域名）、
`IMAGE_MODEL`（默认 `wan2.7-image-pro`）、`IMAGE_THINKING`（默认开）。

快速抽帧验收（跳过 TTS 与合成，约 1–3 分钟，19 块 × 3 帧到
`output/preview/m3_*.jpg`）：

```bash
python3 pipeline/build_long.py --frames
```

## 长视频叙事模式（M3 v2 · 画面讲卡点）

主视觉改为画面叙事：正文不渲染文字卡，文案由配音 + 底部逐句字幕承载；
每块口播由 AI 切成 3-5 个卡点，每个卡点一张「插画叙事」画面（人物+故事），
引擎按卡点切换画面。存在 `script/storyboard_narrative.json` 即自动进入
叙事模式，删除该文件即回退文字卡模式。

```bash
# 1. 生成分镜（DeepSeek，每配音块 3-5 拍 + 逐句字幕表）
python3 pipeline/write_storyboard.py
python3 pipeline/write_storyboard.py --check script/storyboard_narrative.json

# 2. 生成卡点画面（wan2.7-image-pro，密钥读 .env）
python3 pipeline/write_image_art.py --story                 # 全部
python3 pipeline/write_image_art.py --story --beats 00_0 02_0   # 只生成指定拍

# 3. 抽帧验收（叙事模式每拍 2 帧，含字幕版）
python3 pipeline/build_long.py --frames
```

画面命名：`assets/long/scenes/{块:02d}_{拍}.png`（如 `02_0.png`）；
阶段页用 `assets/long/art/S1-S5.png`，首尾页用 `TITLE.png` / `END.png`。
本片每拍独立人物统一画风；主角一致性（参考图图生图）为下一条片预留。
