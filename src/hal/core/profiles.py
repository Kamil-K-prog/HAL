from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

TaskType = Literal["chat", "embedding", "classification", "image_gen", "audio_gen", "video_gen"]

ModalityType = Literal["text", "image", "audio", "video", "document"]

RoleSequence = Literal[  # Какие последовательности ролей используются в нативном формате
    "openai", "google", "anthropic", "generic"
]

ReasoningPolicy = Literal[  # Как компилировать ризонинг-блоки
    "preserve_same_provider",  # Оставить нативные мысли только от того же провайдера
    "strip",  # Очистить все ризонинг-блоки из предыдущих ходов
    "transform_to_text",  # Перевести ризонинг-блоки в текстовые блоки
]

APISurface = Literal[
    "openai_chat", "openai_responses", "google_genai", "anthropic_messages", "jev_grpc"
]


class RetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_attempts: int = Field(default=3, ge=1)
    initial_backoff_sec: float = Field(default=5.0, gt=0)
    max_backoff_sec: float = Field(default=60, gt=0)
    backoff_multiplier: float = Field(default=2, ge=1)
    jitter: bool = True
    retryable_status_codes: tuple[int, ...] = (408, 429, 500, 502, 503, 504)

    @model_validator(mode="after")
    def validate_retry_policy(self) -> Self:
        if self.max_backoff_sec < self.initial_backoff_sec:
            raise ValueError("max_backoff_sec must be >= initial_backoff_sec")
        return self


class ProviderConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_id: str
    provider_instance_id: str = "default"
    base_url: str | None = None
    api_key_env_var: str | None = None
    timeout_sec: float = Field(default=60.0, gt=0)
    default_headers: dict[str, str] = Field(default_factory=dict)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)


class ModelCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_types: set[TaskType] = Field(min_length=1)
    supports_streaming: bool = True
    supports_tools: bool = False
    supports_parallel_tool_calls: bool = False
    supports_strict_tool_schema: bool = False
    supports_structured_output: bool = False
    supports_prompt_caching: bool = False
    input_modalities: set[ModalityType] = Field(min_length=1, default={"text"})
    output_modalities: set[ModalityType] = Field(min_length=1, default={"text"})


class ModelLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_context_tokens: int = Field(default=128_000, gt=0)
    max_output_tokens: int = Field(default=4_096, gt=0)
    reserve_output_tokens: int = Field(default=1_024, ge=0)
    max_inline_asset_bytes: int = Field(default=15 * 1024 * 1024, ge=0)
    allowed_mime_types: set[str] | None = None

    @model_validator(mode="after")
    def validate_max_context_tokens(self) -> Self:
        if self.max_output_tokens + self.reserve_output_tokens >= self.max_context_tokens:
            msg = "max_output_tokens + reserve_output_tokens must be < max_context_tokens"
            raise ValueError(msg)
        return self


class CompatibilityRules(BaseModel):
    model_config = ConfigDict(frozen=True)

    role_sequence_policy: RoleSequence = "openai"
    reasoning_policy: ReasoningPolicy = "preserve_same_provider"
    preserve_thoughts_in_react: bool = True  # Сохранять ли мысли во время текущего ReAct
    require_thought_signature_on_tools: bool = False  # Подпись вызовов инструментов (Gemini)
    disallowed_generation_params: set[str] = Field(default_factory=set)


class ModelProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_id: str
    model_id: str  # ID в API
    model_name: str | None = None  # Человекочитаемое имя
    provider_id: str
    api_surface: APISurface = "openai_chat"
    capabilities: ModelCapabilities
    limits: ModelLimits = Field(default_factory=ModelLimits)
    compatibility: CompatibilityRules = Field(default_factory=CompatibilityRules)
    tokenizer_id: str = "cl100k_base"

    @model_validator(mode="after")
    def calculate_model_name_if_not_exists(self) -> Self:
        if not self.model_name:
            object.__setattr__(self, "model_name", self.model_id.replace("-", " "))
        return self

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False)

    @classmethod
    def from_yaml(cls, yaml_data: str) -> ModelProfile:
        raw_data = yaml.safe_load(yaml_data)
        return cls.model_validate(raw_data)

    @classmethod
    def from_file(cls, file_path: str | Path) -> ModelProfile:
        with open(file_path, encoding="utf-8") as f:
            loaded_data = yaml.safe_load(f)
            return cls.model_validate(loaded_data)
