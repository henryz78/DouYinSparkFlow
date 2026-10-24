"""界面、CLI 与聊天工作线程共享的配置。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from urllib.parse import urlsplit

DEFAULT_PROMPT = (
    "用自然、日常的中文与对方聊天，像平时发消息一样直接、简短，不用客服腔或书面总结。"
    "认真接住对方的话题，通常回复一到两句，能一句说清就不扩写；不反复复述，不频繁追问。"
    "尽量少用语气助词，尤其是‘呀、啦、呢、哟、哦、呐、嘛、哒、哈’；不用连续感叹号、波浪号或刻意卖萌。"
    "少用‘哈哈、嘿嘿’，不必每条都加称呼或 emoji，不机械附和，不无端热情。"
    "根据对话关系和上下文调整语气，不编造自己的经历、线下行为、承诺或与对方的关系。"
    "不主动提及 AI、模型或技术身份，不使用‘作为 AI’等开场；如果对方直接询问身份，简短如实回答，不冒充账号本人。"
    "收到表情、emoji 或视频分享时自然接话；只依据可读标签、标题和上下文，不声称看过未观看的视频或识别了图像。"
)


@dataclass
class ProviderConfig:
    id: str = "deepseek"
    name: str = "DeepSeek"
    kind: str = "deepseek"
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    api_key: str = field(default="", repr=False)


@dataclass
class AIConfig:
    providers: list[ProviderConfig] = field(default_factory=lambda: [ProviderConfig()])
    active_provider: str = "deepseek"
    system_prompt: str = DEFAULT_PROMPT
    poll_interval: int = 5
    cooldown: int = 15
    context_turns: int = 10
    max_tokens: int = 512
    max_reply_chars: int = 500
    request_timeout: int = 30
    stickers: list[str] = field(default_factory=list)  # 允许 AI 发送的抖音原生表情包名称，空表示不发
    enabled: bool = True  # 陪聊总开关；关掉后好友名单照样保留
    personas: list[dict] = field(default_factory=list)  # 性格预设：{"name": 名称, "prompt": 语气描述}
    default_persona: str = ""  # 没单独指定性格的好友用这个；空表示只用 system_prompt

    def persona_prompt(self, name):
        """好友指定的性格；没指定或已被删掉就退回默认性格，都没有返回空串。"""
        found = {p["name"]: p["prompt"] for p in self.personas}
        return found.get(name) or found.get(self.default_persona, "")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_value(cls, value):
        if isinstance(value, str):
            value = json.loads(value or "{}")
        if not isinstance(value, dict):
            raise ValueError("AI_CHAT 必须是 JSON 对象")
        default = cls()
        providers = value.get("providers", default.to_dict()["providers"])
        if not isinstance(providers, list) or not providers:
            raise ValueError("至少需要一个 AI 服务")
        fields = ProviderConfig.__dataclass_fields__
        default.providers = [
            ProviderConfig(**{k: str(v or "").strip() for k, v in p.items() if k in fields})
            for p in providers if isinstance(p, dict)
        ]
        for key in ("active_provider", "system_prompt"):
            if key in value:
                setattr(default, key, str(value[key] or ""))
        if "stickers" in value:
            names = value["stickers"]
            if not isinstance(names, list):
                raise ValueError("stickers 必须是表情包名称列表")
            default.stickers = [n for n in dict.fromkeys(str(n).strip() for n in names) if n][:30]
        if "enabled" in value:
            default.enabled = bool(value["enabled"])
        if "personas" in value:
            default.personas = cls.clean_personas(value["personas"])
        if "default_persona" in value:
            default.default_persona = str(value["default_persona"] or "").strip()
        limits = {
            "poll_interval": (2, 120), "cooldown": (0, 3600),
            "context_turns": (1, 30), "max_tokens": (32, 4096),
            "max_reply_chars": (20, 2000), "request_timeout": (5, 120),
        }
        for key, (lo, hi) in limits.items():
            if key in value:
                number = int(value[key])
                if not lo <= number <= hi:
                    raise ValueError(f"{key} 应在 {lo} 到 {hi} 之间")
                setattr(default, key, number)
        return default

    @staticmethod
    def clean_personas(items):
        if not isinstance(items, list) or len(items) > 12:
            raise ValueError("性格最多 12 个")
        out = []
        for item in items:
            name = str(item.get("name") or "").strip() if isinstance(item, dict) else ""
            prompt = str(item.get("prompt") or "").strip() if isinstance(item, dict) else ""
            if not 1 <= len(name) <= 12 or not 1 <= len(prompt) <= 600:
                raise ValueError("性格名称 1 到 12 个字，描述 1 到 600 个字")
            if any(name == o["name"] for o in out):
                raise ValueError(f"性格名称重复：{name}")
            out.append({"name": name, "prompt": prompt})
        return out

    def selected(self):
        ids = [p.id for p in self.providers]
        if len(ids) != len(set(ids)) or any(not i for i in ids):
            raise ValueError("AI 服务标识不能为空或重复")
        provider = next((p for p in self.providers if p.id == self.active_provider), None)
        if provider is None:
            raise ValueError("请选择一个 AI 服务")
        parsed = urlsplit(provider.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("API 地址应是 http:// 或 https:// 开头的服务地址")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("API 地址不能包含账号、密码、查询参数或片段")
        if not provider.api_key:
            raise ValueError("请填写所选 AI 服务的 API Key")
        if not provider.model:
            raise ValueError("请填写模型名称")
        if not self.system_prompt.strip():
            raise ValueError("陪聊角色提示词不能为空")
        return provider
