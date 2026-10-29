"""
Спецификация стандарта УФС v2
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, BeforeValidator, Field

from hal.core.errors import FrameworkError
from hal.core.identity import ModelExecutionIdentity

AssetRepresentationKind = Literal[
    "description",  # Сгенерированное моделью описание
    "transcription",  # Расшифровка
    "ocr",
    "extracted_text",  # Если достаём текст из документов программными методами, без OCR
]

AssetKind = Literal["image", "audio", "video", "document"]

ToolCallStatus = Literal["pending", "executing", "completed", "failed", "cancelled", "denied"]

TurnStatus = Literal[
    "generating",
    "awaiting_tool_results",
    "awaiting_model",
    "committing",
    "completed",
    "failed",
    "cancelled",
]

CompressionStrategy = Literal[
    "truncate_old_tools",  # Вычищаем старые результаты тулов
    "llm_summary",  # Заменяем контекст на саммари LLM
    # Заменяем старые ReAct на саммари LLM. В отличие от llm_summary, не суммаризирует всё
    "hybrid",
    # Подаём в контекст последние N сообщений
    # (нецелесообразно, теряется кэш и контекст из начала)
    "sliding_window",
]

GenerationFinishReason = Literal[
    "tool_call",  # Модель решила вызвать инструмент
    "max_output_limit",  # Упирание в лимит генерации токенов
    "safeguard_triggered",  # На стороне провайдера сработали фильтры
    # От провайдера пришёл последний чанк, но модель не вызвала ни один инструмент
    # (значит, модель выдала итоговое сообщение на этом ходу)
    "turn_completed",
]

MessageRole = Literal["system", "user", "assistant", "tool"]

_REGISTRY: dict[str, type[BaseModel]] = dict()


def register_type[T: BaseModel](cls: type[T]) -> type[T]:
    """Декоратор: регистрирует Part-класс по значению его `type`-поля."""
    field = cls.model_fields.get("type")
    if field is None:
        raise TypeError(f"{cls.__name__} must declare a `type` field")

    tags = get_args(field.annotation)
    if len(tags) != 1:
        raise TypeError(f"{cls.__name__}.type must be Literal[<single tag>]")
    tag: str = tags[0]

    if tag in _REGISTRY:
        raise ValueError(f"Tag {tag!r} already registered by {_REGISTRY[tag].__name__}.")

    _REGISTRY[tag] = cls
    return cls


# === Медиа-ассеты ===
class CloudRef(BaseModel):
    provider_id: str
    cloud_id: str | None = None
    uri: str | None = None
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetRepresentation(BaseModel):
    kind: AssetRepresentationKind
    text: str
    model_identity: str  # кто сгенерировал описание
    language: str = "ru"
    content_sha256: str  # хэш исходного файла для проверки актуальности кэша
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    params: dict[str, Any] = Field(default_factory=dict)


class Asset(BaseModel):
    id: str  # ast_xxx
    kind: AssetKind
    storage_uri: str  # file://..., mem://..., s3://...
    mime_type: str
    size_bytes: int = Field(default=0, ge=0)
    sha256: str
    status: Literal["pending", "materialized", "uploaded", "expired", "failed"] = "materialized"
    representations: dict[str, AssetRepresentation] = Field(default_factory=dict)
    cloud_refs: dict[str, CloudRef] = Field(default_factory=dict)


# === Части сообщений ===
@register_type
class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str
    cache_control: Literal["ephemeral"] | None = None  # Маркер для Prompt Caching


@register_type
class ReasoningPart(BaseModel):
    type: Literal["reasoning"] = "reasoning"
    text: str = ""
    signature: str | None = None  # Криптографическая подпись (напр. Gemini thought_signature)
    provider_id: str | None = None


@register_type
class AssetPart(BaseModel):
    type: Literal["asset"] = "asset"
    asset: Asset


@register_type
class StructuredDataPart(BaseModel):
    """Типизированный JSON-ответ при использовании Structured Outputs (response_schema)."""

    type: Literal["structured_data"] = "structured_data"
    schema_name: str
    data: dict[str, Any]


@register_type
class ToolCallPart(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    call_id: str  # call_xxx
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    provider_extensions: dict[str, Any] = Field(
        default_factory=dict
    )  # Изолированные метаданные провайдера


@register_type
class ToolResultPart(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    call_id: str
    name: str
    text: str
    error: FrameworkError | None = None
    assets: list[Asset] = Field(default_factory=list)


@register_type
class UnknownPart(BaseModel):
    """Защитный контейнер для прямой совместимости при загрузке более новых версий схемы (I9)."""

    type: Literal["unknown"] = "unknown"
    original_type: str
    raw_payload: dict[str, Any]


def _transform_unknown_type(data: Any) -> Any:
    if isinstance(data, dict):
        type = data.get("type")
        if isinstance(type, str) and type not in _REGISTRY:
            return {
                "type": "unknown",
                "original_type": type,
                "raw_payload": data,
            }
    return data


MessagePart = Annotated[
    Annotated[
        TextPart
        | ReasoningPart
        | AssetPart
        | StructuredDataPart
        | ToolCallPart
        | ToolResultPart
        | UnknownPart,
        Field(discriminator="type"),
    ],
    BeforeValidator(_transform_unknown_type),
]


# === Телеметрия, события и сообщения ===
class UsageStats(BaseModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)  # Поддержка Context Caching
    total_tokens: int = Field(ge=0)


class GenerationMetadata(BaseModel):
    execution_identity: ModelExecutionIdentity
    usage: UsageStats | None = None
    finish_reason: GenerationFinishReason | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    provider_extensions: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    """Каноническое сообщение диалога (УФС 2.0)."""

    id: str  # msg_xxx
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    role: MessageRole
    parts: list[MessagePart] = Field(default_factory=list)
    metadata: GenerationMetadata | None = None


class Event(BaseModel):
    """Аудиторское/техническое событие (хранится отдельно от messages)."""

    id: str  # evt_xxx
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    type: Literal[
        "model_switch",
        "compression_anchor",
        "session_start",
        "session_fork",
        "error",
        "tool_registration",
        "context_overflow",
        "user_edit",
        "regeneration",
        "cancellation",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)
    related_message_ids: list[str] = Field(default_factory=list)


# === Состояние хода ===
class PendingToolCall(BaseModel):
    call_id: str
    turn_id: str
    execution_identity: ModelExecutionIdentity
    assistant_message_id: str
    name: str
    args_hash: str
    status: ToolCallStatus
    result_message_id: str | None = None


class TurnState(BaseModel):
    turn_id: str  # trn_xxx
    execution_identity: ModelExecutionIdentity
    status: TurnStatus
    pending_tool_calls: list[PendingToolCall] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CompressionCheckpoint(BaseModel):
    checkpoint_id: str  # cmp_xxx
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    compressed_range_start: str
    compressed_range_end: str
    compressed_messages: list[Message]
    original_message_count: int = Field(ge=0)
    original_token_count: int = Field(ge=0)
    compressed_token_count: int = Field(ge=0)
    strategy: CompressionStrategy
    compression_params: dict[str, Any] = Field(default_factory=dict)


class ChatMetadata(BaseModel):
    schema_version: Literal["2.0"] = "2.0"
    conversation_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    active_model_identity: ModelExecutionIdentity | None = None
    compression_checkpoints: list[CompressionCheckpoint] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


# === Контейнер ===
class ChatData(BaseModel):
    """Полный сериализуемый снимок состояния сессии."""

    metadata: ChatMetadata
    messages: list[Message] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    active_turn: TurnState | None = None
