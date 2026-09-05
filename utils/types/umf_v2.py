"""Унифицированный формат сообщений (УФС/UMF) версии 2.0.

Модели этого модуля не зависят от SDK провайдеров. Они описывают намерение
клиента и состояние локальных/облачных представлений данных; адаптеры моделей
отвечают за перевод этих структур в конкретный API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Provider = Literal["openai", "anthropic", "genai", "custom"]
ApiKind = Literal["chat_completions", "responses", "messages", "generate_content", "custom"]
AssetKind = Literal["image", "audio", "video", "document"]

__all__ = [
    "ApiKind",
    "Asset",
    "AssetKind",
    "AssetPart",
    "CacheEntry",
    "ChatData",
    "ChatMetadata",
    "CloudObject",
    "ContentPart",
    "GenerationMetadata",
    "Integrity",
    "Message",
    "ModelSelection",
    "ModelSwitchPart",
    "Provider",
    "ReasoningPart",
    "TextPart",
    "ToolCall",
    "ToolCallPart",
    "ToolResult",
    "ToolResultPart",
    "UMFConfig",
    "Usage",
]


class UMFModel(BaseModel):
    """Общие настройки доменных объектов УФС."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ModelSelection(UMFModel):
    """Выбранная связка провайдер-модель для следующего хода."""

    provider: Provider
    model: str
    api: ApiKind
    reasoning_enabled: bool = True
    parameters: dict[str, Any] = Field(default_factory=dict)


class Integrity(UMFModel):
    """Доказательства целостности файла, вычисленные при помещении в кэш."""

    algorithm: Literal["sha256"] = "sha256"
    digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    verified_at: datetime | None = None


class CacheEntry(UMFModel):
    """Локальная копия ассета и её состояние."""

    path: str
    size_bytes: int = Field(ge=0)
    created_at: datetime
    last_verified_at: datetime | None = None
    integrity: Integrity | None = None


class CloudObject(UMFModel):
    """Копия ассета у провайдера с данными для повторной загрузки."""

    provider: Provider
    object_id: str | None = None
    uri: str | None = None
    filename: str | None = None
    uploaded_at: datetime
    expires_at: datetime | None = None
    status: Literal["active", "expired", "pending", "failed"] = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def has_reference(self) -> CloudObject:
        if self.status in {"active", "expired"} and not self.object_id and not self.uri:
            raise ValueError("cloud object must contain object_id or uri")
        return self


class Asset(UMFModel):
    """Медиафайл или PDF в УФС.

    `inline_base64` используется только для небольших объектов. Провайдерские
    ссылки являются кэшем и могут быть заменены адаптером после истечения TTL.
    """

    id: str
    kind: AssetKind
    mime_type: str
    filename: str | None = None
    size_bytes: int = Field(ge=0)
    cache: CacheEntry | None = None
    integrity: Integrity | None = None
    inline_base64: str | None = None
    cloud_objects: list[CloudObject] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TextPart(UMFModel):
    type: Literal["text"] = "text"
    text: str


class AssetPart(UMFModel):
    type: Literal["asset"] = "asset"
    assets: list[Asset] = Field(min_length=1)


class ReasoningPart(UMFModel):
    type: Literal["reasoning"] = "reasoning"
    text: str | None = None
    encrypted: str | None = None
    provider: Provider | None = None
    signature: str | None = None
    item_id: str | None = None

    @model_validator(mode="after")
    def has_reasoning_payload(self) -> ReasoningPart:
        if not self.text and not self.encrypted and not self.signature:
            raise ValueError("reasoning must contain text, encrypted data, or signature")
        return self


class ToolCall(UMFModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    namespace: str | None = None


class ToolCallPart(UMFModel):
    type: Literal["tool_call"] = "tool_call"
    call: ToolCall


class ToolResult(UMFModel):
    id: str
    name: str | None = None
    output: str | dict[str, Any] | list[Any] | None = None
    is_error: bool = False
    assets: list[Asset] = Field(default_factory=list)


class ToolResultPart(UMFModel):
    type: Literal["tool_result"] = "tool_result"
    result: ToolResult


class ModelSwitchPart(UMFModel):
    """Явное событие смены модели между ходами диалога."""

    type: Literal["model_switch"] = "model_switch"
    previous: ModelSelection | None = None
    selected: ModelSelection
    reason: str | None = None


ContentPart = Annotated[
    TextPart
    | AssetPart
    | ReasoningPart
    | ToolCallPart
    | ToolResultPart
    | ModelSwitchPart,
    Field(discriminator="type"),
]


class Usage(UMFModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class GenerationMetadata(UMFModel):
    provider: Provider
    model: str
    api: ApiKind
    finish_reason: str | None = None
    usage: Usage | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    response_id: str | None = None


class Message(UMFModel):
    id: str
    created_at: datetime
    role: Literal["system", "user", "assistant", "tool", "event"]
    content: list[ContentPart] = Field(default_factory=list)
    name: str | None = None
    metadata: GenerationMetadata | None = None


class UMFConfig(UMFModel):
    default_model: ModelSelection | None = None
    reasoning_enabled: bool = True
    retain_reasoning: Literal["full", "encrypted", "none"] = "encrypted"
    inline_asset_limit_bytes: int = Field(default=20 * 1024 * 1024, ge=0)


class ChatMetadata(UMFModel):
    version: Literal["2.0"] = "2.0"
    conversation_id: str
    created_at: datetime
    updated_at: datetime
    config: UMFConfig = Field(default_factory=UMFConfig)
    active_model: ModelSelection | None = None

    @model_validator(mode="after")
    def initialize_active_model(self) -> ChatMetadata:
        if self.active_model is None:
            object.__setattr__(self, "active_model", self.config.default_model)
        return self


class ChatData(UMFModel):
    """Корневой сериализуемый контейнер истории УФС 2.0."""

    metadata: ChatMetadata
    messages: list[Message] = Field(default_factory=list)

    def switch_model(
        self,
        selection: ModelSelection,
        *,
        event_id: str,
        created_at: datetime,
        reason: str | None = None,
    ) -> Message:
        """Выбрать модель для следующего хода и записать событие в историю.

        Событие является границей обычных ходов. Проверка того, что активный
        ReAct-цикл завершён, относится к оркестратору, поскольку только он
        владеет состоянием исполнения инструментов.
        """

        previous = self.metadata.active_model
        event = Message(
            id=event_id,
            created_at=created_at,
            role="event",
            content=[
                ModelSwitchPart(
                    previous=previous,
                    selected=selection,
                    reason=reason,
                )
            ],
        )
        self.messages.append(event)
        self.metadata.active_model = selection
        self.metadata.updated_at = created_at
        return event
