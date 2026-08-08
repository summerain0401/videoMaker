# 交接文档（给下一个会话）

> 更新：2026-08-06 ｜ 目标：把「从文案到听书长视频」的项目状态完整交给新会话，避免重复踩坑。

## 1. 项目一句话

本地自动化流水线：文案 → 配音 → 画面 → 合成 → 交付，对标 YouTube 频道《认知书页》的 13–18 分钟听书解读长视频（16:9 横屏）。第一条样片《金钱的艺术》已跑到 V2 样段阶段。

## 2. 当前状态（先读这个）

- ✅ **长视频 V2 引擎**（`pipeline/build_long.py`）已实现：Piper 本地神经男声、全程运镜、视差装饰层、文字淡入滑动、xfade 转场、丰富元素（书卡/徽章/对比表/阶梯图/复利曲线/环形图）、`--pilot` 模式。
- ✅ **V2 样段已交付**：`output/long/long_money_v2_pilot.mp4`（181 秒，前 5 个镜头）。
- ✅ **M2 文案 AI 化完成**：`pipeline/write_long_copy.py`（DeepSeek 五段式完整脚本起草 + 结构校验/回喂重试 + `--accept` 定稿）；当前 `copy/long/script.txt` 为 AI 起草稿（旧手写稿备份 `script.txt.bak`）。
- ✅ **M3 视觉升级完成**：阶段配色/徽章/插画位 bug 修复、书卡跟随脚本、逐词浮现/视差/转场映射/进度条随时间跟随、程序化质感底图；通义万相 `wan2.7-image-pro` 插画已生成到 `assets/long/art/`（TITLE/END/S1-S5）。
- ✅ **M3 v2 画面叙事化**：画面讲卡点（正文零文字卡、配音+逐句字幕）；分镜 `script/storyboard_narrative.json`（19 块 80 拍，经 `--refine` 拆超长拍）；`write_image_art.py --story` 生成卡点画面到 `assets/long/scenes/`（当前 44 张，覆盖样片块）；引擎检测到分镜即进入叙事模式（删除 JSON 回退文字卡）。
- 🎬 **视觉样片 v2**：`output/long/long_money_v2_visual_sample.mp4`（块 00-03、静音轨）；已修复暗度（去掉 55% 压暗层、vignette PI/7，画面全亮）、运镜明显增强（缩放 0.40、视差 ±14）、移除 art/ 底图引用（阶段页改用后续卡点画面）；生图模型默认 `wan2.7-image`（经济版）。
- 🖼 **快速抽帧验收**：`python3 pipeline/build_long.py --frames`（约 1–3 分钟，19 块 × 3 帧到 `output/preview/m3_*.jpg`，跳过 TTS）。
- ⏳ **全片未渲染**：19 个镜头、约 9–10 分钟。等用户对样段反馈确认后再跑。
- ⏳ **用户尚未反馈样段观感**（音色/运镜/元素/转场四方面）。
- ⚠️ **必须做的事**：跑全片前确认旧女声缓存不在生效目录——已统一移到 `archive/audio_old/`（含 `blk*_systemTingting190*`、旧稿 `.aiff`/lead/tail 等），确认无用后可整目录删除；Piper 缓存（`audio/long/voice/blk*_piperls1.15*`）已就位，00–04 块可直接复用。
- 📄 用户提供的频道深度报告在根目录 `report.pdf`，项目规划在 `PROJECT_PLAN.md`。

## 3. 环境速查

- **必须用捆绑 Python**（Pillow/piper/g2pw/torch 都装在这里）：
  `/Users/spring/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`
- **运行构建需要提权**（`require_escalated`）：Piper 的 PyTorch 共享内存在沙盒内被禁；`say` 也需要系统权限。
- **ffmpeg 8.1**（`/opt/homebrew/bin/ffmpeg`）：**没有 drawtext / libass / subtitles**，所有文字用 Pillow 生成 PNG 层再 overlay。
- **Piper 中文男声**：模型在 `assets/piper/zh_CN-chaowen-medium.onnx`，拼音模型 `assets/piper/g2pW/`（已下载）。
- **系统中文音色**：只有 Tingting 可用（Eddy/Reed 等男声需要联网服务，本环境失效）。
- **API 密钥全部未设置**：`OPENAI_API_KEY` / `DEEPSEEK_API_KEY` / `KIMI_API_KEY` / 火山 / 通义 / 硅基流动等都没有。网络已开启但外部 API 仍需用户提供密钥。

## 4. 两条流水线

### 短视频（旧，保留）
- 入口：`pipeline/build.py`；文案源 `copy/voiceover.txt`；输出 `output/short/ai_3steps_demo.mp4`。
- 用法：`TTS_VOICE=Tingting python3 pipeline/build.py`。

### 长视频 V2（主攻方向）
- 入口：`pipeline/build_long.py`；文案源 `copy/long/script.txt`；视觉元素 `pipeline/long_visuals.py`；Piper 适配 `pipeline/tts_piper.py`。
- 用法：
  ```bash
  python3 pipeline/build_long.py --pilot   # 前 5 个块，评审用
  python3 pipeline/build_long.py           # 全片
  ```
- 环境变量：`TTS_SOURCE=piper|system`（默认 piper）、`PIPER_LENGTH_SCALE`（默认 1.15，越大越慢）、`TTS_VOICE`/`TTS_RATE`（system 模式）。
- 生图环境变量（`.env`）：`DASHSCOPE_API_KEY`（必填）、`DASHSCOPE_BASE_URL`（百炼业务空间专属域名，可带 `/api/v1` 后缀）、`IMAGE_MODEL`（默认 `wan2.7-image-pro`）、`IMAGE_THINKING`（默认开）。
- 背景乐：**不自动生成**；把用户音乐放进 `audio/long/user_music.mp3|wav|m4a`（或 `music.*`）自动混音（音量 0.25，循环），否则纯人声。
- AI 插画位：`assets/long/art/S1.png … S5.png`、`TITLE.png`、`END.png`，存在则用作背景并自动压暗，否则程序化渐变。
- 产物：`output/long/long_money_v2.mp4`（全片）、`output/long/long_money_v2_pilot.mp4`、`script/storyboard_long.csv`、`output/long/long_summary.json`。

## 5. 文案格式（copy/long/script.txt）

```text
# TITLE                     → 片头标题页
## 书名                      → 显示行
voice：口播文本              → 配音（必须）

# PHASE 01 · 开场共情        → 阶段过渡页（4 秒，无配音）

# CARD 标题                  → 文字卡，## 行逐条点亮
# QUOTE                      → 羊皮纸金句卡（配音前自动留 1 秒停顿）
# TABLE 左列 | 右列           → 对比表，## 行按“左 | 右”分行
# STEPS 标题                  → 阶梯图，## 行按顺序点亮
# END                        → 结尾页
```

注意：`# CARD`、`# TABLE`、`# STEPS` 的 `##` 行数与内容会映射到画面；改文案时保持结构一致即可，时长全部按配音自动计算。`# CARD` 标题含「复利」会自动画复利曲线。

## 6. 已知坑与经验

- **zoompan 输出尺寸必须是偶数**（1920x1080）：用 2000x1125 会走慢速路径（5 秒画面 21 秒，约 4 倍慢）。
- **不要用 rotate 动态尺寸**：角度表达式加自动输出尺寸会每帧重建缓冲，非常慢；当前版本已移除 rotate，靠缓推/缓拉/横移 + 视差漂移制造动感。
- **不要加逐帧 noise 滤镜**（`allf=t+u`）：极慢，已移除，只用 vignette。
- **音频缓存**：命名含配置（如 `blk00_piperls1.15.wav`），存在则跳过合成。**注意别把不同音色的缓存混用**（这次就发生过，已修正）。
- **TTS 时长守卫**：某段合成时长 < 字数/4 的一半会抛错，用于抓断音。
- **xfade 转场**：视频用 xfade、音频用 acrossfade，offset 公式 `offset_k = 前 k+1 段时长和 - (k+1)*0.5`；阶段页用 zoomin 冲击转场。
- **渲染耗时**：全片约 9–10 分钟成片，TTS（g2pw 每段 20–60 秒）+ 场景渲染（约 1 倍速）+ xfade 重编码，预计 30–40 分钟。
- **提权审批**：Piper 合成必须在沙盒外跑（torch 共享内存），这是硬性要求。

## 7. 待办（按优先级）

1. **先问用户样段反馈**：音色（Piper 男声 vs 云 TTS 男声）、运镜强度（样段是旧参数，代码已调到 0.18 缩放/±14px 漂移）、画面元素、转场。
2. **确认旧缓存已隔离后跑全片**：旧女声缓存已移至 `archive/audio_old/`（确认无用可整目录删除），然后 `python3 pipeline/build_long.py`（提权）。
3. **全片质检**：ffprobe 时长/分辨率、volumedetect 响度、抽帧检查元素、相邻帧差验证运镜、完整解码。
4. **更新文档**：V2 上线后把 `PROJECT_PLAN.md`（§6/§12）和 `copy/script.md` 同步成新引擎说明。
5. **可选后续**：文案扩到 4000 字（现 2490 字 → 全片仅约 9–10 分钟，目标 13–18 分钟）；云 TTS 男声（火山/CosyVoice，需密钥）；AI 插画底图（硅基流动/通义万相，需密钥，文件放 `assets/long/art/`）；苹果个人语音。

## 8. 关键决策记录

- 规格：16:9 横屏 1920x1080、30fps、13–18 分钟目标。
- 第一条样片书目：《金钱的艺术》（Morgan Housel），原创解读文案，不复制原文。
- 配音：先用本地 Piper 男声（用户拍板）；云 TTS 和苹果个人语音为后续路线。
- 画面：程序化元素为主，AI 插画位预留。
- 音乐：用户提供才用，不自动生成。
- 运营手法（标题公式、灵魂提问）已在文案结构里体现，尚未做封面/标题自动生成。

## 9. 参考文件

- `PROJECT_PLAN.md` — 项目规划（含《认知书页》目标形态解构 §12）
- `report.pdf` — 用户提供的频道深度报告（五段式公式、SOP、运营）
- `copy/long/script.txt` — 当前口播稿（五段式）
- `output/long/long_money_v2_pilot.mp4` — 待评审样段
