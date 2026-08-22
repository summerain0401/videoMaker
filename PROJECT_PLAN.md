# 可插拔长视频生产架构

## 当前状态

架构重构已落地为四层：

1. LLM 内容层：topic → copy → script → storyboard，Codex 默认，DeepSeek API 可替换。
2. 图片生成层：统一 storyboard → 临时 ImageTask，ImageGen 默认，万相 API 可替换。
3. Azure 语音层：唯一 TTS，固定项目音色，网络错误在 Azure 内重试。
4. 公共生产层：候选审核、字幕、运镜、SFX、三段 BGM、渲染、QA。

## 不变量

- `project.json.providers` 是唯一配置事实源，活动 run 期间禁止修改。
- run 保存完整 provider 快照；项目内不允许混用 LLM 或图片模型。
- 模型产物先进入候选区；topic/copy/script/storyboard/images 固定人工确认点。
- 正式 `storyboard.json` 只表达语义，不携带任何模型请求字段。
- 图片适配器只做 ImageTask → 模型请求 → PNG，不负责业务规则。
- Azure、渲染、QA 无人工提升步骤，运行成功即进入完成状态。

## 阶段依赖

```text
topic → copy → script ─────→ voice ──┐
                  └→ storyboard → images ─→ render → qa
```

script 提升后 voice 与 storyboard 同时解锁；render 必须等待 voice 和 images。

## 扩展 provider

新增 LLM 时实现与 `CodexProvider`/`DeepSeekProvider` 相同的 `generate(stage, task, destination)`；新增图片模型时实现 `generate(tasks)`。随后仅注册名称，不修改 workflow、正式 schema 或渲染器。智谱目前只保留这一扩展约定，不提供虚假适配器。

## 迁移

001/002 已完成确定性迁移：旧两层分镜归档，新 `storyboard.json` 合并句子覆盖、角色、情绪、景别和 segment，并剥离最终图片 Prompt；topic/copy 从 brief、metadata、script 回填且标记 `source: migration`。历史图片保留原路径，不伪造来源。
