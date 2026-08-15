# 2D Q版插画分镜生成流水线技术规范

本文档定义了将中文财商分镜脚本自动转换为统一2D Q版插画Prompts的核心架构、数据规范与装配逻辑。

---

## 1. 架构概览

流水线采用三层解耦架构，分离风格渲染、角色实体与动态场景：

```
[原始文案 / 分镜JSON] 
       │
       ▼
[LLM 分镜解析器] ──(提取动作/道具 + 动态分配角色ID)
       │
       ▼
[Prompt 装配引擎] ──(注入全局2D底模 + 读取 characters.json 角色预设)
       │
       ▼
[生图 API 集成层] ──(附加负面提示词与尺寸参数，批量生成资产)

```

---

## 2. 核心数据结构与配置

### 2.1 角色预设库 (`characters.json`)

管理全局常驻与扩展角色，角色定义仅包含外貌、服装与标志物，严禁包含动作与情绪。

```json
{
  "young_pro": {
    "role_name": "核心主角/年轻上班族",
    "prompt": "cute 2D chibi 25yo male, messy black hair, round gold glasses, dark navy business suit, red tie"
  },
  "frugal_girl": {
    "role_name": "实操主角/年轻女性",
    "prompt": "cute 2D chibi 20yo female, high ponytail, pink hair tie, oversized beige knit sweater"
  },
  "author_morgan": {
    "role_name": "智者/财经导师",
    "prompt": "cute 2D chibi middle-aged male scholar, neat brown hair, round glasses, brown vest with necktie"
  },
  "mentor_buffett": {
    "role_name": "长线投资者/老者",
    "prompt": "cute 2D chibi wise elderly investor, fluffy white hair, round glasses, gentle smile, green knit vest"
  },
  "stressed_debtor": {
    "role_name": "过度消费/投机反面角色",
    "prompt": "cute 2D chibi male office worker, rumpled gray suit, loosened necktie, dark eye circles, sweating"
  },
  "none": {
    "role_name": "无主体/纯概念金融道具",
    "prompt": ""
  }
}

```

### 2.2 输出分镜数据结构规范 (`storyboard_output.json`)

```json
{
  "style_id": "2D_CHIBI_VECTOR_FINANCE",
  "block_idx": 0,
  "head": "CARD 认知差",
  "beats": [
    {
      "beat_idx": 0,
      "shot": "medium",
      "original_cn": "年轻人在暖阳下看着手机里的存款数字，神情轻松笃定。",
      "character_id": "young_pro",
      "action_props_en": "looking at phone screen showing high savings balance with a relieved smile, sitting at clean desk with morning sunlight",
      "final_image_prompt": "2D cute chibi kawaii anime illustration, flat vector graphic art, bold clean outlines, vibrant pastel colors, clean minimalist studio background, cute 2D chibi 25yo male, messy black hair, round gold glasses, dark navy business suit, red tie, looking at phone screen showing high savings balance with a relieved smile, sitting at clean desk with morning sunlight, medium shot, --ar 16:9"
    }
  ]
}

```

---

## 3. Prompt 装配引擎规范

### 3.1 装配公式

$$\text{Final Prompt} = \text{Global 2D Style} + \text{Character Base} + \text{Action \& Props (EN)} + \text{Shot \& Aspect Ratio}$$

### 3.2 提示词模板常量定义

```python
GLOBAL_2D_STYLE_PREFIX = (
    "2D cute chibi kawaii anime illustration, flat vector graphic art, "
    "bold clean outlines, vibrant pastel colors, simple minimalist studio background"
)

NEGATIVE_PROMPT = (
    "photorealistic, realistic, 3D render, dark gritty shadows, realistic human anatomy, "
    "complex detailed environment, photographic textures, text, watermark, signature, blurry"
)

```

---

## 4. LLM 结构化提取模块

### 4.1 System Prompt 规范

```markdown
你是财商视频分镜翻译与角色指派引擎。你的任务是将中文叙事分镜转换为结构化的英文动作描述与角色绑定。

【执行规则】：
1. 角色分配：根据分镜上下文，从候选列表 [young_pro, frugal_girl, author_morgan, mentor_buffett, stressed_debtor, none] 中选取唯一的 character_id。
2. 动作提炼：提取为纯动作、面部表情、交互金融道具（如 gold coins, piggy bank, credit card, k-line chart），禁止包含画风、渲染、材质词汇。
3. 语种规范：action_props 必须输出为紧凑、无多余修饰词的英文从句。

【输出 JSON Schema】：
{
  "character_id": "string",
  "action_props": "string"
}

```

---
