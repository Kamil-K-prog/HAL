from datetime import UTC, datetime
from typing import Any, Literal, get_args

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from hal.core.errors import FrameworkError
from hal.core.identity import ModelExecutionIdentity
from hal.core.umf import (
    _REGISTRY,
    Asset,
    AssetKind,
    AssetPart,
    AssetRepresentation,
    AssetRepresentationKind,
    ChatData,
    ChatMetadata,
    CloudRef,
    CompressionCheckpoint,
    CompressionStrategy,
    Event,
    GenerationFinishReason,
    GenerationMetadata,
    Message,
    MessagePart,
    PendingToolCall,
    ReasoningPart,
    StructuredDataPart,
    TextPart,
    ToolCallPart,
    ToolCallStatus,
    ToolResultPart,
    TurnState,
    TurnStatus,
    UnknownPart,
    UsageStats,
    register_type,
)


class TestRegisterTypeDecorator:
    """Тесты для декоратора register_type и реестра _REGISTRY."""

    def test_registered_standard_parts(self) -> None:
        expected_tags = {
            "text",
            "reasoning",
            "asset",
            "structured_data",
            "tool_call",
            "tool_result",
            "unknown",
        }
        assert expected_tags.issubset(_REGISTRY.keys())
        assert _REGISTRY["text"] is TextPart
        assert _REGISTRY["unknown"] is UnknownPart

    def test_missing_type_field_raises(self) -> None:
        with pytest.raises(TypeError, match="must declare a `type` field"):

            @register_type
            class InvalidNoType(BaseModel):
                foo: str

    def test_multi_value_literal_raises(self) -> None:
        with pytest.raises(TypeError, match="must be Literal\\[<single tag>\\]"):

            @register_type
            class InvalidMultiType(BaseModel):
                type: Any = "foo"

    def test_duplicate_tag_registration_raises(self) -> None:
        with pytest.raises(ValueError, match="already registered"):

            @register_type
            class DuplicateText(BaseModel):
                type: Literal["text"] = "text"


class TestAssets:
    """Тесты моделей CloudRef, AssetRepresentation и Asset."""

    def test_cloud_ref_defaults(self) -> None:
        ref = CloudRef(provider_id="google")
        assert ref.provider_id == "google"
        assert ref.cloud_id is None
        assert ref.uri is None
        assert ref.expires_at is None
        assert ref.metadata == {}

    def test_cloud_ref_custom(self) -> None:
        expires = datetime(2026, 1, 1, tzinfo=UTC)
        ref = CloudRef(
            provider_id="openai",
            cloud_id="file-123",
            uri="https://api.openai.com/v1/files/file-123",
            expires_at=expires,
            metadata={"purpose": "assistants"},
        )
        assert ref.cloud_id == "file-123"
        assert ref.expires_at == expires
        assert ref.metadata["purpose"] == "assistants"

    def test_asset_representation_defaults(self) -> None:
        now = datetime.now(UTC)
        rep = AssetRepresentation(
            kind="description",
            text="Картинка кота",
            model_identity="gemini-2.5-flash",
            content_sha256="abc123hash",
        )
        assert rep.kind == "description"
        assert rep.text == "Картинка кота"
        assert rep.language == "ru"
        assert rep.params == {}
        assert rep.created_at.tzinfo == UTC
        assert rep.created_at >= now

    def test_asset_representation_kinds(self) -> None:
        expected = {"description", "transcription", "ocr", "extracted_text"}
        assert set(get_args(AssetRepresentationKind)) == expected

    def test_asset_defaults(self) -> None:
        asset = Asset(
            id="ast_1",
            kind="image",
            storage_uri="file:///tmp/img.png",
            mime_type="image/png",
            sha256="deadbeef",
        )
        assert asset.size_bytes == 0
        assert asset.status == "materialized"
        assert asset.representations == {}
        assert asset.cloud_refs == {}

    def test_asset_negative_size_raises(self) -> None:
        with pytest.raises(ValidationError):
            Asset(
                id="ast_1",
                kind="document",
                storage_uri="file:///tmp/doc.pdf",
                mime_type="application/pdf",
                sha256="hash",
                size_bytes=-1,
            )

    def test_asset_kinds(self) -> None:
        expected = {"image", "audio", "video", "document"}
        assert set(get_args(AssetKind)) == expected


class TestMessagePartsAndUnknownPart:
    """Тесты частей сообщений и Инварианта I9 (перехват неизвестных частей)."""

    def test_text_part(self) -> None:
        part = TextPart(text="Привет", cache_control="ephemeral")
        assert part.type == "text"
        assert part.text == "Привет"
        assert part.cache_control == "ephemeral"

    def test_reasoning_part(self) -> None:
        part = ReasoningPart(text="Думаю...", signature="sig_123", provider_id="google")
        assert part.type == "reasoning"
        assert part.signature == "sig_123"
        assert part.provider_id == "google"

    def test_tool_call_part(self) -> None:
        part = ToolCallPart(
            call_id="call_abc",
            name="get_weather",
            args={"city": "Moscow"},
            provider_extensions={"thought_signature": "sig"},
        )
        assert part.type == "tool_call"
        assert part.call_id == "call_abc"
        assert part.args["city"] == "Moscow"
        assert part.provider_extensions["thought_signature"] == "sig"

    def test_tool_result_part_with_error(self) -> None:
        error = FrameworkError(
            code="API_ERROR",
            category="transport_error",
            user_message="Connection failed",
        )
        part = ToolResultPart(
            call_id="call_abc",
            name="get_weather",
            text="Ошибка",
            error=error,
        )
        assert part.type == "tool_result"
        assert part.error is not None
        assert part.error.code == "API_ERROR"

    def test_structured_data_part(self) -> None:
        part = StructuredDataPart(schema_name="UserCard", data={"name": "Alice"})
        assert part.type == "structured_data"
        assert part.schema_name == "UserCard"
        assert part.data == {"name": "Alice"}

    def test_unknown_part_direct_construction(self) -> None:
        part = UnknownPart(
            original_type="future_modal",
            raw_payload={"type": "future_modal", "v": 1},
        )
        assert part.type == "unknown"
        assert part.original_type == "future_modal"
        assert part.raw_payload == {"type": "future_modal", "v": 1}

    def test_invariant_i9_unknown_type_coercion(self) -> None:
        """Инвариант I9: неизвестный тип при десериализации заворачивается в UnknownPart."""
        adapter = TypeAdapter(MessagePart)
        raw_payload = {"type": "hologram_3d", "resolution": "8k", "fps": 120}

        coerced = adapter.validate_python(raw_payload)
        assert isinstance(coerced, UnknownPart)
        assert coerced.type == "unknown"
        assert coerced.original_type == "hologram_3d"
        assert coerced.raw_payload == raw_payload

    def test_invariant_i9_roundtrip_no_double_wrapping(self) -> None:
        """Повторный round-trip сериализованного UnknownPart не должен оборачиваться дважды."""
        adapter = TypeAdapter(MessagePart)
        unknown = UnknownPart(
            original_type="quantum_state",
            raw_payload={"type": "quantum_state", "qubits": 4},
        )

        dumped = unknown.model_dump()
        restored = adapter.validate_python(dumped)

        assert isinstance(restored, UnknownPart)
        assert restored.original_type == "quantum_state"
        assert restored.raw_payload == {"type": "quantum_state", "qubits": 4}


class TestTelemetryAndMessages:
    """Тесты статистики, метаданных, сообщений и событий."""

    def test_usage_stats_validations(self) -> None:
        usage = UsageStats(input_tokens=100, output_tokens=50, total_tokens=150)
        assert usage.reasoning_tokens == 0
        assert usage.cached_input_tokens == 0

        with pytest.raises(ValidationError):
            UsageStats(input_tokens=-1, output_tokens=10, total_tokens=9)

    def test_generation_finish_reason_literals(self) -> None:
        expected = {"tool_call", "max_output_limit", "safeguard_triggered", "turn_completed"}
        assert set(get_args(GenerationFinishReason)) == expected

    def test_generation_metadata_defaults(self) -> None:
        ident = ModelExecutionIdentity(
            provider_id="openai",
            model_id="gpt-4o",
            api_surface="openai_chat",
        )
        meta = GenerationMetadata(
            execution_identity=ident,
            finish_reason="turn_completed",
            latency_ms=250,
        )
        assert meta.usage is None
        assert meta.finish_reason == "turn_completed"
        assert meta.latency_ms == 250
        assert meta.provider_extensions == {}

    def test_generation_metadata_negative_latency_raises(self) -> None:
        ident = ModelExecutionIdentity(
            provider_id="openai",
            model_id="gpt-4o",
            api_surface="openai_chat",
        )
        with pytest.raises(ValidationError):
            GenerationMetadata(execution_identity=ident, latency_ms=-5)

    def test_message_creation_and_defaults(self) -> None:
        now = datetime.now(UTC)
        msg = Message(
            id="msg_1",
            role="assistant",
            parts=[TextPart(text="Привет!")],
        )
        assert msg.id == "msg_1"
        assert msg.role == "assistant"
        assert len(msg.parts) == 1
        assert msg.timestamp >= now
        assert msg.metadata is None

    def test_event_creation(self) -> None:
        event = Event(
            id="evt_1",
            type="model_switch",
            payload={"from": "gpt-4o", "to": "gemini-2.5-pro"},
            related_message_ids=["msg_1"],
        )
        assert event.type == "model_switch"
        assert event.payload["to"] == "gemini-2.5-pro"
        assert event.related_message_ids == ["msg_1"]


class TestTurnStateAndChatData:
    """Тесты состояния хода, компрессии и корневого контейнера ChatData."""

    def test_turn_state_and_pending_tool_call(self) -> None:
        ident = ModelExecutionIdentity(
            provider_id="openai",
            model_id="gpt-4o",
            api_surface="openai_chat",
        )
        call = PendingToolCall(
            call_id="call_1",
            turn_id="trn_1",
            execution_identity=ident,
            assistant_message_id="msg_1",
            name="calculator",
            args_hash="hash_123",
            status="pending",
        )
        state = TurnState(
            turn_id="trn_1",
            execution_identity=ident,
            status="generating",
            pending_tool_calls=[call],
        )
        assert state.turn_id == "trn_1"
        assert state.status == "generating"
        assert len(state.pending_tool_calls) == 1
        assert state.pending_tool_calls[0].status == "pending"

    def test_status_literals_coverage(self) -> None:
        expected_tool_status = {
            "pending",
            "executing",
            "completed",
            "failed",
            "cancelled",
            "denied",
        }
        assert set(get_args(ToolCallStatus)) == expected_tool_status

        expected_turn_status = {
            "generating",
            "awaiting_tool_results",
            "awaiting_model",
            "committing",
            "completed",
            "failed",
            "cancelled",
        }
        assert set(get_args(TurnStatus)) == expected_turn_status

        expected_comp_strategy = {"truncate_old_tools", "llm_summary", "hybrid", "sliding_window"}
        assert set(get_args(CompressionStrategy)) == expected_comp_strategy

    def test_compression_checkpoint_counts_validation(self) -> None:
        with pytest.raises(ValidationError):
            CompressionCheckpoint(
                checkpoint_id="cmp_1",
                compressed_range_start="msg_1",
                compressed_range_end="msg_5",
                compressed_messages=[],
                original_message_count=-1,
                original_token_count=100,
                compressed_token_count=50,
                strategy="truncate_old_tools",
            )

    def test_chat_data_roundtrip_serialization(self) -> None:
        """Полный round-trip тест снимка сессии ChatData -> JSON -> ChatData."""
        ident = ModelExecutionIdentity(
            provider_id="google",
            model_id="gemini-2.5-pro",
            api_surface="google_genai",
        )
        asset = Asset(
            id="ast_1",
            kind="image",
            storage_uri="mem://img.png",
            mime_type="image/png",
            size_bytes=1024,
            sha256="img_sha",
            representations={
                "desc": AssetRepresentation(
                    kind="description",
                    text="Тестовый график",
                    model_identity="gemini-2.5-flash",
                    content_sha256="img_sha",
                )
            },
            cloud_refs={
                "google": CloudRef(provider_id="google", cloud_id="files/123"),
            },
        )
        messages = [
            Message(
                id="msg_1",
                role="user",
                parts=[
                    TextPart(text="Посчитай и посмотри на фото"),
                    AssetPart(asset=asset),
                ],
            ),
            Message(
                id="msg_2",
                role="assistant",
                parts=[
                    ReasoningPart(text="Надо вызвать калькулятор", signature="sig_g"),
                    ToolCallPart(call_id="call_1", name="add", args={"a": 2, "b": 2}),
                ],
                metadata=GenerationMetadata(
                    execution_identity=ident,
                    usage=UsageStats(input_tokens=100, output_tokens=40, total_tokens=140),
                    finish_reason="tool_call",
                ),
            ),
            Message(
                id="msg_3",
                role="tool",
                parts=[
                    ToolResultPart(call_id="call_1", name="add", text="4"),
                    # Проверяем I9 внутри реального списка сообщений
                    UnknownPart(
                        original_type="neuro_sensor",
                        raw_payload={"type": "neuro_sensor", "level": 99},
                    ),
                ],
            ),
        ]
        events = [
            Event(id="evt_1", type="session_start"),
        ]
        active_turn = TurnState(
            turn_id="trn_1",
            execution_identity=ident,
            status="awaiting_model",
            pending_tool_calls=[
                PendingToolCall(
                    call_id="call_1",
                    turn_id="trn_1",
                    execution_identity=ident,
                    assistant_message_id="msg_2",
                    name="add",
                    args_hash="hash",
                    status="completed",
                    result_message_id="msg_3",
                )
            ],
        )

        chat_data = ChatData(
            metadata=ChatMetadata(
                conversation_id="conv_123",
                active_model_identity=ident,
            ),
            messages=messages,
            events=events,
            active_turn=active_turn,
        )

        # 1. Сериализация в JSON
        json_str = chat_data.model_dump_json()
        assert isinstance(json_str, str)
        assert "conv_123" in json_str
        assert "neuro_sensor" in json_str

        # 2. Десериализация из JSON
        restored = ChatData.model_validate_json(json_str)

        # 3. Полное соответствие исходному объекту
        assert restored == chat_data
        assert isinstance(restored.messages[2].parts[1], UnknownPart)
        assert restored.messages[2].parts[1].original_type == "neuro_sensor"
