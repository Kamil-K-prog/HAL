import hashlib
import json
from datetime import UTC, datetime
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from hal.core.errors import (
    AssetStorageError,
    ConfigurationError,
    ContextPreparationError,
    DuplicateMessageError,
    ErrorCategory,
    FrameworkError,
    HalCancellationError,
    HalError,
    HalTimeoutError,
    HistoryValidationError,
    InvalidTurnStateError,
    ModelSwitchMidTurnError,
    PolicyDeniedError,
    ProviderResponseError,
    RateLimitError,
    ToolExecutionError,
    TransportError,
    TurnInProgressError,
    UnsupportedCapabilityError,
    UnsupportedMediaError,
    VersionConflictError,
)
from hal.core.identity import ModelExecutionIdentity, SwitchReasonCode
from hal.core.ids import IdFactory


class TestIdFactory:
    """Тесты для IdFactory."""

    def test_prefix_constants(self) -> None:
        assert IdFactory.PREFIX_MESSAGE == "msg"
        assert IdFactory.PREFIX_TOOL_CALL == "call"
        assert IdFactory.PREFIX_EVENT == "evt"
        assert IdFactory.PREFIX_TURN == "trn"
        assert IdFactory.PREFIX_COMPRESSION == "cmp"
        assert IdFactory.PREFIX_ASSET == "ast"

    def test_generate_unprefixed(self) -> None:
        factory = IdFactory()
        id_str = factory.generate()
        assert isinstance(id_str, str)
        assert len(id_str) == 26
        assert "_" not in id_str
        assert IdFactory.validate(id_str) is True

    @pytest.mark.parametrize(
        "prefix",
        [
            IdFactory.PREFIX_MESSAGE,
            IdFactory.PREFIX_TOOL_CALL,
            IdFactory.PREFIX_EVENT,
            IdFactory.PREFIX_TURN,
            IdFactory.PREFIX_COMPRESSION,
            IdFactory.PREFIX_ASSET,
            "custom",
        ],
    )
    def test_generate_prefixed(self, prefix: str) -> None:
        factory = IdFactory()
        id_str = factory.generate(prefix=prefix)
        assert id_str.startswith(f"{prefix}_")
        assert len(id_str) == len(prefix) + 1 + 26
        assert IdFactory.validate(id_str) is True

    def test_generate_with_explicit_timestamp(self) -> None:
        factory = IdFactory()
        dt = datetime(2025, 6, 15, 12, 0, 0, 500000, tzinfo=UTC)
        id_str = factory.generate(timestamp=dt)
        extracted = IdFactory.extract_timestamp(id_str)
        assert extracted == dt

    def test_generate_with_prefix_and_timestamp(self) -> None:
        factory = IdFactory()
        dt = datetime(2025, 8, 20, 18, 45, 30, 250000, tzinfo=UTC)
        id_str = factory.generate(prefix=IdFactory.PREFIX_TURN, timestamp=dt)
        assert id_str.startswith("trn_")
        assert IdFactory.validate(id_str) is True
        extracted = IdFactory.extract_timestamp(id_str)
        assert extracted == dt

    def test_generate_uniqueness(self) -> None:
        factory = IdFactory()
        generated = [factory.generate() for _ in range(1000)]
        assert len(set(generated)) == 1000

    def test_generate_chronological_ordering(self) -> None:
        factory = IdFactory()
        dt1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        dt2 = datetime(2025, 1, 1, 10, 0, 1, tzinfo=UTC)
        id1 = factory.generate(prefix="msg", timestamp=dt1)
        id2 = factory.generate(prefix="msg", timestamp=dt2)
        assert id1 < id2

    def test_extract_timestamp_unprefixed(self) -> None:
        factory = IdFactory()
        dt = datetime(2024, 12, 31, 23, 59, 59, 999000, tzinfo=UTC)
        id_str = factory.generate(timestamp=dt)
        extracted = IdFactory.extract_timestamp(id_str)
        assert extracted == dt

    def test_extract_timestamp_prefixed(self) -> None:
        factory = IdFactory()
        dt = datetime(2024, 12, 31, 23, 59, 59, 999000, tzinfo=UTC)
        id_str = factory.generate(prefix="evt", timestamp=dt)
        extracted = IdFactory.extract_timestamp(id_str)
        assert extracted == dt

    def test_extract_timestamp_empty_prefix_raises(self) -> None:
        factory = IdFactory()
        raw_ulid = factory.generate()
        invalid_id = f"_{raw_ulid}"
        with pytest.raises(ValueError, match="Empty prefix in ID"):
            IdFactory.extract_timestamp(invalid_id)

    @pytest.mark.parametrize(
        "invalid_id",
        [
            "",
            "invalid_ulid_string",
            "msg_not_a_valid_ulid_string",
            "msg_12345",
            "msg_01ARZ3NDEKTSV4RRFFQ69G5FAV_extra",
        ],
    )
    def test_extract_timestamp_invalid_raises(self, invalid_id: str) -> None:
        with pytest.raises(ValueError):
            IdFactory.extract_timestamp(invalid_id)

    @pytest.mark.parametrize(
        "invalid_id",
        [
            "",
            "_01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "invalid",
            "msg_invalid",
            "msg_",
            "12345",
            "msg_01ARZ3NDEKTSV4RRFFQ69G5FAV_extra",
        ],
    )
    def test_validate_invalid_cases(self, invalid_id: str) -> None:
        assert IdFactory.validate(invalid_id) is False


class TestModelExecutionIdentity:
    """Тесты для ModelExecutionIdentity и связанных типов."""

    def test_creation_with_defaults(self) -> None:
        identity = ModelExecutionIdentity(
            provider_id="openai",
            model_id="gpt-4o",
            api_surface="chat_completions",
        )
        assert identity.provider_id == "openai"
        assert identity.model_id == "gpt-4o"
        assert identity.api_surface == "chat_completions"
        assert identity.provider_instance_id == "default"
        assert identity.profile_id is None
        assert identity.configuration_fingerprint == "default"

    def test_creation_with_all_fields(self) -> None:
        identity = ModelExecutionIdentity(
            provider_id="google",
            provider_instance_id="asia-northeast1",
            model_id="gemini-2.5-pro",
            api_surface="generate_content",
            profile_id="coding-profile",
            configuration_fingerprint="abc123hash",
        )
        assert identity.provider_id == "google"
        assert identity.provider_instance_id == "asia-northeast1"
        assert identity.model_id == "gemini-2.5-pro"
        assert identity.api_surface == "generate_content"
        assert identity.profile_id == "coding-profile"
        assert identity.configuration_fingerprint == "abc123hash"

    def test_missing_required_fields_raises(self) -> None:
        with pytest.raises(ValidationError):
            ModelExecutionIdentity(provider_id="openai")  # type: ignore[call-arg]

    def test_frozen_immutability(self) -> None:
        identity = ModelExecutionIdentity(
            provider_id="openai",
            model_id="gpt-4o",
            api_surface="chat_completions",
        )
        with pytest.raises(ValidationError):
            identity.model_id = "gpt-4o-mini"  # type: ignore[misc]

    def test_equality_and_hashability(self) -> None:
        id1 = ModelExecutionIdentity(
            provider_id="openai",
            model_id="gpt-4o",
            api_surface="chat_completions",
        )
        id2 = ModelExecutionIdentity(
            provider_id="openai",
            model_id="gpt-4o",
            api_surface="chat_completions",
        )
        id3 = ModelExecutionIdentity(
            provider_id="openai",
            model_id="gpt-4o-mini",
            api_surface="chat_completions",
        )
        assert id1 == id2
        assert hash(id1) == hash(id2)
        assert id1 != id3
        assert len({id1, id2, id3}) == 2

    def test_fingerprint_none_and_empty(self) -> None:
        assert ModelExecutionIdentity.get_configuration_fingerprint(None) == "default"
        assert ModelExecutionIdentity.get_configuration_fingerprint({}) == "default"

    def test_fingerprint_deterministic_and_sorted_keys(self) -> None:
        cfg1 = {"temperature": 0.7, "max_tokens": 1000}
        cfg2 = {"max_tokens": 1000, "temperature": 0.7}

        fp1 = ModelExecutionIdentity.get_configuration_fingerprint(cfg1)
        fp2 = ModelExecutionIdentity.get_configuration_fingerprint(cfg2)

        assert len(fp1) == 64
        assert fp1 == fp2

        expected_hash = hashlib.sha256(
            json.dumps(cfg1, sort_keys=True, default=str).encode()
        ).hexdigest()
        assert fp1 == expected_hash

    def test_fingerprint_different_values(self) -> None:
        fp1 = ModelExecutionIdentity.get_configuration_fingerprint({"temp": 0.5})
        fp2 = ModelExecutionIdentity.get_configuration_fingerprint({"temp": 0.7})
        assert fp1 != fp2

    def test_fingerprint_non_serializable_types(self) -> None:
        class CustomObj:
            def __str__(self) -> str:
                return "custom-representation"

        cfg = {"obj": CustomObj(), "dt": datetime(2025, 1, 1, tzinfo=UTC)}
        fp = ModelExecutionIdentity.get_configuration_fingerprint(cfg)
        assert len(fp) == 64

    def test_switch_reason_codes(self) -> None:
        expected = {
            "user_request",
            "config_change",
            "context_limit",
            "provider_error",
            "capability_fallback",
        }
        assert set(get_args(SwitchReasonCode)) == expected


class TestFrameworkError:
    """Тесты для модели FrameworkError."""

    def test_framework_error_defaults(self) -> None:
        err = FrameworkError(
            code="TEST_ERROR",
            category="validation_error",
            user_message="Validation failed",
        )
        assert err.code == "TEST_ERROR"
        assert err.category == "validation_error"
        assert err.retryable is False
        assert err.user_message == "Validation failed"
        assert err.diagnostic_context == {}

    def test_framework_error_custom_fields(self) -> None:
        err = FrameworkError(
            code="CUSTOM_CODE",
            category="timeout_error",
            retryable=True,
            user_message="Timed out",
            diagnostic_context={"timeout_seconds": 30},
        )
        assert err.code == "CUSTOM_CODE"
        assert err.category == "timeout_error"
        assert err.retryable is True
        assert err.user_message == "Timed out"
        assert err.diagnostic_context == {"timeout_seconds": 30}

    def test_framework_error_serialization(self) -> None:
        err = FrameworkError(
            code="NETWORK_ERROR",
            category="transport_error",
            retryable=True,
            user_message="Connection lost",
            diagnostic_context={"host": "api.example.com"},
        )
        dumped = err.model_dump()
        assert dumped == {
            "code": "NETWORK_ERROR",
            "category": "transport_error",
            "retryable": True,
            "user_message": "Connection lost",
            "diagnostic_context": {"host": "api.example.com"},
        }
        json_data = json.loads(err.model_dump_json())
        assert json_data == dumped

    def test_framework_error_invalid_category(self) -> None:
        with pytest.raises(ValidationError):
            FrameworkError(
                code="BAD_CATEGORY",
                category="non_existent_category",
                user_message="Test",
            )

    def test_error_category_literal_values(self) -> None:
        expected = {
            "validation_error",
            "policy_denied",
            "tool_execution_error",
            "timeout_error",
            "cancellation_error",
            "transport_error",
            "rate_limit_error",
            "provider_response_error",
            "capability_error",
            "asset_storage_error",
            "concurrency_error",
            "internal_error",
        }
        assert set(get_args(ErrorCategory)) == expected


class TestHalErrorHierarchy:
    """Тесты для иерархии исключений HalError."""

    def test_hal_error_base_defaults(self) -> None:
        err = HalError()
        assert isinstance(err, Exception)
        assert err.code == "INTERNAL_ERROR"
        assert err.category == "internal_error"
        assert err.retryable is False
        assert err.user_message == "Error occurred, check logs"
        assert err.diagnostic_context == {}
        assert str(err) == "Error occurred, check logs"

    def test_hal_error_custom_arguments(self) -> None:
        err = HalError(
            user_message="Custom failure",
            retryable=True,
            diagnostic_context={"attempt": 3},
            code="CUSTOM_FAIL",
            category="transport_error",
        )
        assert err.code == "CUSTOM_FAIL"
        assert err.category == "transport_error"
        assert err.retryable is True
        assert err.user_message == "Custom failure"
        assert err.diagnostic_context == {"attempt": 3}
        assert str(err) == "Custom failure"

    def test_hal_error_diagnostic_context_copied(self) -> None:
        orig_context: dict[str, Any] = {"key": "initial"}
        err = HalError("message", diagnostic_context=orig_context)
        orig_context["key"] = "mutated"
        assert err.diagnostic_context["key"] == "initial"

    def test_hal_error_to_framework_error(self) -> None:
        err = HalError(
            user_message="Something went wrong",
            retryable=True,
            diagnostic_context={"info": 123},
            code="TEST_CODE",
            category="tool_execution_error",
        )
        fe = err.to_framework_error()
        assert isinstance(fe, FrameworkError)
        assert fe.code == "TEST_CODE"
        assert fe.category == "tool_execution_error"
        assert fe.retryable is True
        assert fe.user_message == "Something went wrong"
        assert fe.diagnostic_context == {"info": 123}

    def test_hal_error_from_framework_error_unknown_code(self) -> None:
        fe = FrameworkError(
            code="UNKNOWN_EXTERNAL_CODE",
            category="transport_error",
            retryable=True,
            user_message="Unknown error occurred",
            diagnostic_context={"detail": "debug"},
        )
        err = HalError.from_framework_error(fe)
        assert type(err) is HalError
        assert err.code == "UNKNOWN_EXTERNAL_CODE"
        assert err.category == "transport_error"
        assert err.retryable is True
        assert err.user_message == "Unknown error occurred"
        assert err.diagnostic_context == {"detail": "debug"}

    def test_all_subclasses_registered(self) -> None:
        import hal.core.errors as err_mod

        subclasses = [
            getattr(err_mod, name)
            for name in dir(err_mod)
            if isinstance(getattr(err_mod, name), type)
            and issubclass(getattr(err_mod, name), HalError)
            and getattr(err_mod, name) is not HalError
        ]
        assert len(subclasses) == 18
        for sc in subclasses:
            assert sc.default_code in HalError._registry
            assert HalError._registry[sc.default_code] is sc

    @pytest.mark.parametrize(
        ("cls", "expected_code", "expected_category", "expected_retryable"),
        [
            (TurnInProgressError, "TURN_IN_PROGRESS", "concurrency_error", False),
            (InvalidTurnStateError, "INVALID_TURN_STATE", "concurrency_error", False),
            (ModelSwitchMidTurnError, "MODEL_SWITCH_MID_TURN", "concurrency_error", False),
            (VersionConflictError, "HISTORY_VERSION_CONFLICT", "concurrency_error", True),
            (DuplicateMessageError, "DUPLICATE_MESSAGE_ID", "validation_error", False),
            (HistoryValidationError, "UMF_INVARIANT_VIOLATION", "validation_error", False),
            (ContextPreparationError, "CONTEXT_PREPARATION_FAILED", "validation_error", False),
            (ConfigurationError, "INVALID_CONFIGURATION", "validation_error", False),
            (UnsupportedCapabilityError, "UNSUPPORTED_CAPABILITY", "capability_error", False),
            (UnsupportedMediaError, "UNSUPPORTED_MEDIA_TYPE", "capability_error", False),
            (AssetStorageError, "ASSET_STORAGE_FAILED", "asset_storage_error", True),
            (ToolExecutionError, "TOOL_EXECUTION_FAILED", "tool_execution_error", False),
            (PolicyDeniedError, "POLICY_DENIED", "policy_denied", False),
            (TransportError, "NETWORK_TRANSPORT_ERROR", "transport_error", True),
            (RateLimitError, "PROVIDER_RATE_LIMIT", "rate_limit_error", True),
            (ProviderResponseError, "PROVIDER_RESPONSE_ERROR", "provider_response_error", False),
            (HalTimeoutError, "OPERATION_TIMEOUT", "timeout_error", True),
            (HalCancellationError, "OPERATION_CANCELLED", "cancellation_error", False),
        ],
    )
    def test_concrete_subclass_defaults_and_roundtrip(
        self,
        cls: type[HalError],
        expected_code: str,
        expected_category: ErrorCategory,
        expected_retryable: bool,
    ) -> None:
        inst = cls()
        assert isinstance(inst, HalError)
        assert isinstance(inst, Exception)
        assert inst.code == expected_code
        assert inst.category == expected_category
        assert inst.retryable is expected_retryable
        assert len(inst.user_message) > 0
        assert inst.diagnostic_context == {}

        # Roundtrip via FrameworkError
        fe = inst.to_framework_error()
        assert isinstance(fe, FrameworkError)
        assert fe.code == expected_code
        assert fe.category == expected_category
        assert fe.retryable is expected_retryable
        assert fe.user_message == inst.user_message
        assert fe.diagnostic_context == inst.diagnostic_context

        restored = HalError.from_framework_error(fe)
        assert type(restored) is cls
        assert restored.code == expected_code
        assert restored.category == expected_category
        assert restored.retryable is expected_retryable
        assert restored.user_message == inst.user_message
        assert restored.diagnostic_context == inst.diagnostic_context

    def test_version_conflict_error_context(self) -> None:
        err = VersionConflictError(expected=10, actual=15)
        assert err.diagnostic_context == {"expected": 10, "actual": 15}
        assert err.retryable is True

        err2 = VersionConflictError(
            expected=5,
            actual=6,
            diagnostic_context={"session_id": "sess_123"},
            user_message="Custom conflict message",
        )
        assert err2.diagnostic_context == {
            "session_id": "sess_123",
            "expected": 5,
            "actual": 6,
        }
        assert err2.user_message == "Custom conflict message"

        err3 = VersionConflictError(diagnostic_context={"extra": "data"})
        assert err3.diagnostic_context == {"extra": "data"}

        # Roundtrip preserves context
        fe = err.to_framework_error()
        restored = HalError.from_framework_error(fe)
        assert isinstance(restored, VersionConflictError)
        assert restored.diagnostic_context == {"expected": 10, "actual": 15}

    def test_history_validation_error_context(self) -> None:
        issues = ["missing role", "invalid content structure"]
        err = HistoryValidationError(issues=issues)
        assert err.diagnostic_context == {"issues": issues}
        assert err.category == "validation_error"

        err2 = HistoryValidationError(
            issues=issues,
            diagnostic_context={"turn_id": "trn_1"},
            user_message="Validation error occurred",
        )
        assert err2.diagnostic_context == {"turn_id": "trn_1", "issues": issues}
        assert err2.user_message == "Validation error occurred"

        err3 = HistoryValidationError(diagnostic_context={"debug": True})
        assert err3.diagnostic_context == {"debug": True}

        # Roundtrip preserves context
        fe = err.to_framework_error()
        restored = HalError.from_framework_error(fe)
        assert isinstance(restored, HistoryValidationError)
        assert restored.diagnostic_context == {"issues": issues}

    def test_dynamic_subclass_registration(self) -> None:
        custom_code = "DYNAMIC_CUSTOM_CODE_FOR_TEST"
        try:

            class DynamicCustomError(HalError):
                default_code = custom_code
                default_category = "internal_error"

            assert custom_code in HalError._registry
            assert HalError._registry[custom_code] is DynamicCustomError

            fe = FrameworkError(
                code=custom_code,
                category="internal_error",
                user_message="Dynamic error message",
            )
            restored = HalError.from_framework_error(fe)
            assert isinstance(restored, DynamicCustomError)
            assert restored.user_message == "Dynamic error message"
        finally:
            HalError._registry.pop(custom_code, None)


class TestPackageExports:
    """Тесты реэкспорта через hal.core и корневой hal."""

    def test_hal_core_exports(self) -> None:
        import hal.core

        expected_symbols = {
            "AssetStorageError",
            "ConfigurationError",
            "ContextPreparationError",
            "DuplicateMessageError",
            "ErrorCategory",
            "FrameworkError",
            "HalCancellationError",
            "HalError",
            "HalTimeoutError",
            "HistoryValidationError",
            "IdFactory",
            "InvalidTurnStateError",
            "ModelExecutionIdentity",
            "ModelSwitchMidTurnError",
            "PolicyDeniedError",
            "ProviderResponseError",
            "RateLimitError",
            "SwitchReasonCode",
            "ToolExecutionError",
            "TransportError",
            "TurnInProgressError",
            "UnsupportedCapabilityError",
            "UnsupportedMediaError",
            "VersionConflictError",
        }
        assert set(hal.core.__all__) == expected_symbols
        for symbol in expected_symbols:
            assert hasattr(hal.core, symbol)

    def test_hal_root_exports(self) -> None:
        import hal

        expected_symbols = {
            "AssetStorageError",
            "ConfigurationError",
            "ContextPreparationError",
            "DuplicateMessageError",
            "ErrorCategory",
            "FrameworkError",
            "HalCancellationError",
            "HalError",
            "HalTimeoutError",
            "HistoryValidationError",
            "IdFactory",
            "InvalidTurnStateError",
            "ModelExecutionIdentity",
            "ModelSwitchMidTurnError",
            "PolicyDeniedError",
            "ProviderResponseError",
            "RateLimitError",
            "SwitchReasonCode",
            "ToolExecutionError",
            "TransportError",
            "TurnInProgressError",
            "UnsupportedCapabilityError",
            "UnsupportedMediaError",
            "VersionConflictError",
        }
        assert set(hal.__all__) == expected_symbols
        for symbol in expected_symbols:
            assert hasattr(hal, symbol)

