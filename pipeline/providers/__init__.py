"""Provider registries for the production workflow."""

from .image import AntigravityImageProvider, ImageGenProvider, WanxiangProvider
from .llm import AntigravityLLMProvider, CodexProvider, DeepSeekProvider


LLM_PROVIDERS = {
    "antigravity": AntigravityLLMProvider,
    "codex": CodexProvider,
    "deepseek": DeepSeekProvider,
}
IMAGE_PROVIDERS = {
    "antigravity": AntigravityImageProvider,
    "imagegen": ImageGenProvider,
    "wanxiang": WanxiangProvider,
}


def make_llm(config, root):
    name = config.get("name")
    if name not in LLM_PROVIDERS:
        raise ValueError(f"未知 LLM provider：{name}")
    return LLM_PROVIDERS[name](config, root)


def make_image(config, root):
    name = config.get("name")
    if name not in IMAGE_PROVIDERS:
        raise ValueError(f"未知图片 provider：{name}")
    return IMAGE_PROVIDERS[name](config, root)
