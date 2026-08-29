# 语义分镜与 ImageTask 边界

## 正式分镜

`input/storyboard.json` 是 provider-neutral 正式资产。一拍只允许包含：

```json
{
  "beat_idx": 0,
  "sentence_ids": [0, 1],
  "start_char": 0,
  "end_char": 42,
  "visual_description": "人物在清晨工作台前重新审视自己的选择",
  "character_ids": ["young_pro"],
  "shot": "medium",
  "emotion": "reflective",
  "segment": "hook"
}
```

禁止写入 `provider`、`model`、`final_image_prompt`、`negative_prompt`、API 参数或模型专有语法。句子必须按顺序且恰好覆盖一次，块号/拍号唯一连续，`segment` 只能为 `hook / insight / action`。

## 临时 ImageTask

`pipeline/workflow_contracts.py` 在运行图片阶段时，统一合并：

- 项目 `visual_style`；
- 拍的语义画面、景别、情绪；
- `assets/characters.json` 的角色身份描述与一致性 anchor；
- 16:9、1920×1080、字幕安全区，以及结构化文字策略；
- 公共 negative prompt。

生成的 ImageTask 只存在于 run 目录：

```json
{
  "key": "02_1",
  "block_idx": 2,
  "beat_idx": 1,
  "prompt": "...",
  "negative_prompt": "...",
  "rule_manifest": {
    "text_mode": "useful_in_scene",
    "prompt_sources": {"...": "..."}
  },
  "size": [1920, 1080],
  "output_path": ".../assets/scenes/candidates/run_x/02_1.png",
  "reference_images": []
}
```

图片适配器只负责把该任务翻译为 ImageGen 或万相请求并返回 PNG。它不得修改语义约束、角色规则、目录结构或正式分镜，也不得在失败时切换 provider。`rule_manifest.prompt_sources` 能确定性重建 `prompt`；任何额外或加严限制都会导致校验失败。

## 验收

`workflow.py verify <run_id> images` 至少检查：任务是否齐全、规则溯源是否一致、文件能否解码、画幅是否为 16:9，以及候选图片是否高相似。人物一致性、画面语义、文字是否确有必要且克制、整体美术风格仍属于提升前的人工验收内容。
