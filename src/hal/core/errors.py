"""
Смотри markdowns/errors_map.md для пояснений по типам ошибок
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

ErrorCategory = Literal[
    "validation_error",  # Невалидные аргументы тула или нарушение инвариантов UMF
    "policy_denied",  # Отказ HITL или нарушение ToolPolicy / RunPolicy
    "tool_execution_error",  # Исключение внутри пользовательской функции инструмента
    "timeout_error",  # Превышение тайм-аута тула или сетевого запроса
    "cancellation_error",  # Прерывание по CancellationToken
    "transport_error",  # Сетевой сбой, DNS, обрыв сокета
    "rate_limit_error",  # HTTP 429 Quota / Rate Limit
    "provider_response_error",  # HTTP 4xx/5xx или некорректный формат ответа провайдера
    "capability_error",  # Запрошена неподдерживаемая возможность (UnsupportedCapabilityError)
    "asset_storage_error",  # Ошибка чтения/записи файла или загрузки в облако
    "concurrency_error",  # TurnInProgressError / VersionConflictError / ModelSwitchMidTurnError
    "internal_error",  # Общие ошибки (для HalError)
]


class FrameworkError(BaseModel):
    """Каноническая сериализуемая модель ошибки фреймворка."""

    code: str  # Машиночитаемый код, напр. "TOOL_ARG_SCHEMA_MISMATCH"
    category: ErrorCategory
    retryable: bool = False
    user_message: str  # Безопасный текст без секретов и путей ОС (для UI и промпта LLM)
    diagnostic_context: dict[str, Any] = Field(default_factory=dict)


class HalError(Exception):
    default_code: ClassVar[str] = "INTERNAL_ERROR"
    default_category: ClassVar[ErrorCategory] = "internal_error"
    default_retryable: ClassVar[bool] = False
    default_user_message: ClassVar[str] = "Error occurred, check logs"

    _registry: ClassVar[dict[str, type[HalError]]] = {}

    def __init__(
        self,
        user_message: str | None = None,
        *,
        retryable: bool | None = None,
        diagnostic_context: dict[str, Any] | None = None,
        code: str | None = None,
        category: ErrorCategory | None = None,
    ) -> None:
        self.code = code if code is not None else self.default_code
        self.category = category if category is not None else self.default_category
        self.retryable = retryable if retryable is not None else self.default_retryable
        self.user_message = user_message if user_message is not None else self.default_user_message
        self.diagnostic_context = dict(diagnostic_context) if diagnostic_context is not None else {}
        super().__init__(self.user_message)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.default_code != HalError.default_code:
            HalError._registry[cls.default_code] = cls

    @classmethod
    def from_framework_error(cls, error: FrameworkError) -> HalError:
        return HalError._registry.get(error.code, HalError)(
            user_message=error.user_message,
            retryable=error.retryable,
            diagnostic_context=error.diagnostic_context,
            code=error.code,
            category=error.category,
        )

    def to_framework_error(self) -> FrameworkError:
        return FrameworkError(
            code=self.code,
            category=self.category,
            retryable=self.retryable,
            user_message=self.user_message,
            diagnostic_context=self.diagnostic_context,
        )


class TurnInProgressError(HalError):
    default_code = "TURN_IN_PROGRESS"
    default_category = "concurrency_error"
    default_retryable = False
    default_user_message = "Can't run turns in parallel! You must wait for turn to finish."


class InvalidTurnStateError(HalError):
    default_code = "INVALID_TURN_STATE"
    default_category = "concurrency_error"
    default_retryable = False
    default_user_message = "Error occurred while mutating turn state."


class ModelSwitchMidTurnError(HalError):
    default_code = "MODEL_SWITCH_MID_TURN"
    default_category = "concurrency_error"
    default_retryable = False
    default_user_message = (
        "I'm sorry, Dave. I'm afraid I can't do that.\n"
        "Can't switch model mid-turn, wait for it to finish."
    )


class VersionConflictError(HalError):
    default_code = "HISTORY_VERSION_CONFLICT"
    default_category = "concurrency_error"
    default_retryable = True
    default_user_message = "You are working with old version of history. Changes are not committed."

    def __init__(
        self,
        user_message: str | None = None,
        *,
        expected: int | None = None,
        actual: int | None = None,
        diagnostic_context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        context = dict(diagnostic_context) if diagnostic_context else {}
        if expected is not None:
            context["expected"] = expected
        if actual is not None:
            context["actual"] = actual
        super().__init__(user_message=user_message, diagnostic_context=context, **kwargs)


class DuplicateMessageError(HalError):
    default_code = "DUPLICATE_MESSAGE_ID"
    default_category = "validation_error"
    default_retryable = False
    default_user_message = "Message with this ID already exists in the session history."


class HistoryValidationError(HalError):
    default_code = "UMF_INVARIANT_VIOLATION"
    default_category = "validation_error"
    default_retryable = False
    default_user_message = "Conversation history is corrupted or violates format rules."

    def __init__(
        self,
        user_message: str | None = None,
        *,
        issues: list[Any] | None = None,
        diagnostic_context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        context = dict(diagnostic_context) if diagnostic_context else {}
        if issues is not None:
            context["issues"] = issues
        super().__init__(user_message, diagnostic_context=context, **kwargs)


class ContextPreparationError(HalError):
    default_code = "CONTEXT_PREPARATION_FAILED"
    default_category = "validation_error"
    default_retryable = False
    default_user_message = "Failed to prepare conversation history for the selected model."


class ConfigurationError(HalError):
    default_code = "INVALID_CONFIGURATION"
    default_category = "validation_error"
    default_retryable = False
    default_user_message = "Framework configuration is invalid or missing required settings."


class UnsupportedCapabilityError(HalError):
    default_code = "UNSUPPORTED_CAPABILITY"
    default_category = "capability_error"
    default_retryable = False
    default_user_message = "The selected model does not support this feature."


class UnsupportedMediaError(HalError):
    default_code = "UNSUPPORTED_MEDIA_TYPE"
    default_category = "capability_error"
    default_retryable = False
    default_user_message = "The selected model does not support this file or media type."


class AssetStorageError(HalError):
    default_code = "ASSET_STORAGE_FAILED"
    default_category = "asset_storage_error"
    default_retryable = True
    default_user_message = "Failed to read, save, or upload media file."


class ToolExecutionError(HalError):
    default_code = "TOOL_EXECUTION_FAILED"
    default_category = "tool_execution_error"
    default_retryable = False
    default_user_message = "Tool execution failed due to an internal error in the tool function."


class PolicyDeniedError(HalError):
    default_code = "POLICY_DENIED"
    default_category = "policy_denied"
    default_retryable = False
    default_user_message = "Action was denied by security policy or rejected by user."


class TransportError(HalError):
    default_code = "NETWORK_TRANSPORT_ERROR"
    default_category = "transport_error"
    default_retryable = True
    default_user_message = "Network connection failed while communicating with the AI provider."


class RateLimitError(HalError):
    default_code = "PROVIDER_RATE_LIMIT"
    default_category = "rate_limit_error"
    default_retryable = True
    default_user_message = (
        "Too many requests or quota exceeded for the AI provider. Please wait and try again."
    )


class ProviderResponseError(HalError):
    default_code = "PROVIDER_RESPONSE_ERROR"
    default_category = "provider_response_error"
    default_retryable = False
    default_user_message = "The AI provider returned an unexpected error or invalid response."


class HalTimeoutError(HalError):
    default_code = "OPERATION_TIMEOUT"
    default_category = "timeout_error"
    default_retryable = True
    default_user_message = "The operation took too long and timed out."


class HalCancellationError(HalError):
    default_code = "OPERATION_CANCELLED"
    default_category = "cancellation_error"
    default_retryable = False
    default_user_message = "The operation was cancelled by the user."
