from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from hal.core.profiles import (
    APISurface,
    CompatibilityRules,
    ModalityType,
    ModelCapabilities,
    ModelLimits,
    ModelProfile,
    ProviderConfig,
    ReasoningPolicy,
    RetryPolicy,
    RoleSequence,
    TaskType,
)


class TestRetryPolicy:
    """Тесты для модели RetryPolicy."""

    def test_retry_policy_defaults(self) -> None:
        policy = RetryPolicy()
        assert policy.max_attempts == 3
        assert policy.initial_backoff_sec == 5.0
        assert policy.max_backoff_sec == 60.0
        assert policy.backoff_multiplier == 2
        assert policy.jitter is True
        assert policy.retryable_status_codes == (408, 429, 500, 502, 503, 504)

    def test_retry_policy_custom_values(self) -> None:
        policy = RetryPolicy(
            max_attempts=5,
            initial_backoff_sec=1.5,
            max_backoff_sec=120.0,
            backoff_multiplier=3,
            jitter=False,
            retryable_status_codes=(503,),
        )
        assert policy.max_attempts == 5
        assert policy.initial_backoff_sec == 1.5
        assert policy.max_backoff_sec == 120.0
        assert policy.backoff_multiplier == 3
        assert policy.jitter is False
        assert policy.retryable_status_codes == (503,)

    @pytest.mark.parametrize("invalid_attempts", [0, -1])
    def test_retry_policy_invalid_max_attempts(self, invalid_attempts: int) -> None:
        with pytest.raises(ValidationError):
            RetryPolicy(max_attempts=invalid_attempts)

    @pytest.mark.parametrize("invalid_backoff", [0.0, -1.0])
    def test_retry_policy_invalid_initial_backoff(self, invalid_backoff: float) -> None:
        with pytest.raises(ValidationError):
            RetryPolicy(initial_backoff_sec=invalid_backoff)

    def test_retry_policy_max_backoff_less_than_initial_raises(self) -> None:
        with pytest.raises(ValidationError, match="max_backoff_sec must be >= initial_backoff_sec"):
            RetryPolicy(initial_backoff_sec=10.0, max_backoff_sec=5.0)

    def test_retry_policy_immutability(self) -> None:
        policy = RetryPolicy()
        with pytest.raises(ValidationError):
            policy.max_attempts = 10  # type: ignore[misc]

    def test_retry_policy_serialization(self) -> None:
        policy = RetryPolicy()
        data = policy.model_dump()
        restored = RetryPolicy.model_validate(data)
        assert restored == policy


class TestProviderConfig:
    """Тесты для модели ProviderConfig."""

    def test_provider_config_defaults(self) -> None:
        config = ProviderConfig(provider_id="openai")
        assert config.provider_id == "openai"
        assert config.provider_instance_id == "default"
        assert config.base_url is None
        assert config.api_key_env_var is None
        assert config.timeout_sec == 60.0
        assert config.default_headers == {}
        assert config.retry_policy == RetryPolicy()

    def test_provider_config_custom_values(self) -> None:
        custom_retry = RetryPolicy(max_attempts=2)
        config = ProviderConfig(
            provider_id="custom_vllm",
            provider_instance_id="us-east-cluster",
            base_url="http://localhost:8000/v1",
            api_key_env_var="LOCAL_API_KEY",
            timeout_sec=120.0,
            default_headers={"X-Custom": "Header"},
            retry_policy=custom_retry,
        )
        assert config.provider_id == "custom_vllm"
        assert config.provider_instance_id == "us-east-cluster"
        assert config.base_url == "http://localhost:8000/v1"
        assert config.api_key_env_var == "LOCAL_API_KEY"
        assert config.timeout_sec == 120.0
        assert config.default_headers == {"X-Custom": "Header"}
        assert config.retry_policy.max_attempts == 2

    def test_provider_config_missing_required_provider_id(self) -> None:
        with pytest.raises(ValidationError):
            ProviderConfig()  # type: ignore[call-arg]

    @pytest.mark.parametrize("invalid_timeout", [0.0, -10.0])
    def test_provider_config_invalid_timeout(self, invalid_timeout: float) -> None:
        with pytest.raises(ValidationError):
            ProviderConfig(provider_id="openai", timeout_sec=invalid_timeout)

    def test_provider_config_immutability(self) -> None:
        config = ProviderConfig(provider_id="openai")
        with pytest.raises(ValidationError):
            config.timeout_sec = 30.0  # type: ignore[misc]


class TestModelCapabilities:
    """Тесты для матрицы возможностей ModelCapabilities."""

    def test_capabilities_defaults(self) -> None:
        caps = ModelCapabilities(task_types={"chat"})
        assert caps.task_types == {"chat"}
        assert caps.supports_streaming is True
        assert caps.supports_tools is False
        assert caps.supports_parallel_tool_calls is False
        assert caps.supports_strict_tool_schema is False
        assert caps.supports_structured_output is False
        assert caps.supports_prompt_caching is False
        assert caps.input_modalities == {"text"}
        assert caps.output_modalities == {"text"}

    def test_capabilities_custom(self) -> None:
        caps = ModelCapabilities(
            task_types={"chat", "image_gen"},
            supports_streaming=True,
            supports_tools=True,
            supports_parallel_tool_calls=True,
            supports_strict_tool_schema=True,
            supports_structured_output=True,
            supports_prompt_caching=True,
            input_modalities={"text", "image"},
            output_modalities={"text", "image"},
        )
        assert caps.task_types == {"chat", "image_gen"}
        assert caps.supports_tools is True
        assert caps.input_modalities == {"text", "image"}

    def test_capabilities_empty_task_types_raises(self) -> None:
        with pytest.raises(ValidationError):
            ModelCapabilities(task_types=set())

    def test_capabilities_empty_modalities_raises(self) -> None:
        with pytest.raises(ValidationError):
            ModelCapabilities(task_types={"chat"}, input_modalities=set())
        with pytest.raises(ValidationError):
            ModelCapabilities(task_types={"chat"}, output_modalities=set())

    def test_capabilities_literals_coverage(self) -> None:
        expected_tasks = {
            "chat",
            "embedding",
            "classification",
            "image_gen",
            "audio_gen",
            "video_gen",
        }
        expected_modalities = {"text", "image", "audio", "video", "document"}
        assert set(get_args(TaskType)) == expected_tasks
        assert set(get_args(ModalityType)) == expected_modalities

    def test_capabilities_immutability(self) -> None:
        caps = ModelCapabilities(task_types={"chat"})
        with pytest.raises(ValidationError):
            caps.supports_tools = True  # type: ignore[misc]


class TestModelLimits:
    """Тесты для лимитов ModelLimits."""

    def test_limits_defaults(self) -> None:
        limits = ModelLimits()
        assert limits.max_context_tokens == 128_000
        assert limits.max_output_tokens == 4_096
        assert limits.reserve_output_tokens == 1_024
        assert limits.max_inline_asset_bytes == 15 * 1024 * 1024
        assert limits.allowed_mime_types is None

    def test_limits_custom(self) -> None:
        limits = ModelLimits(
            max_context_tokens=1_000_000,
            max_output_tokens=8_192,
            reserve_output_tokens=2_048,
            max_inline_asset_bytes=20 * 1024 * 1024,
            allowed_mime_types={"image/png", "application/pdf"},
        )
        assert limits.max_context_tokens == 1_000_000
        assert limits.allowed_mime_types == {"image/png", "application/pdf"}

    @pytest.mark.parametrize("invalid_tokens", [0, -100])
    def test_limits_positive_tokens_validation(self, invalid_tokens: int) -> None:
        with pytest.raises(ValidationError):
            ModelLimits(max_context_tokens=invalid_tokens)
        with pytest.raises(ValidationError):
            ModelLimits(max_output_tokens=invalid_tokens)

    def test_limits_reserve_can_be_zero(self) -> None:
        limits = ModelLimits(reserve_output_tokens=0)
        assert limits.reserve_output_tokens == 0

    def test_limits_overflow_validator_raises(self) -> None:
        err_msg = "max_output_tokens \\+ reserve_output_tokens must be < max_context_tokens"
        with pytest.raises(ValidationError, match=err_msg):
            ModelLimits(
                max_context_tokens=5_000,
                max_output_tokens=4_000,
                reserve_output_tokens=1_000,
            )

    def test_limits_immutability(self) -> None:
        limits = ModelLimits()
        with pytest.raises(ValidationError):
            limits.max_context_tokens = 64_000  # type: ignore[misc]


class TestCompatibilityRules:
    """Тесты для правил совместимости CompatibilityRules."""

    def test_compatibility_defaults(self) -> None:
        rules = CompatibilityRules()
        assert rules.role_sequence_policy == "openai"
        assert rules.reasoning_policy == "preserve_same_provider"
        assert rules.preserve_thoughts_in_react is True
        assert rules.require_thought_signature_on_tools is False
        assert rules.disallowed_generation_params == set()

    def test_compatibility_custom(self) -> None:
        rules = CompatibilityRules(
            role_sequence_policy="google",
            reasoning_policy="strip",
            preserve_thoughts_in_react=False,
            require_thought_signature_on_tools=True,
            disallowed_generation_params={"temperature", "top_p"},
        )
        assert rules.role_sequence_policy == "google"
        assert rules.reasoning_policy == "strip"
        assert rules.preserve_thoughts_in_react is False
        assert rules.require_thought_signature_on_tools is True
        assert rules.disallowed_generation_params == {"temperature", "top_p"}

    def test_compatibility_literals(self) -> None:
        assert set(get_args(RoleSequence)) == {"openai", "google", "anthropic", "generic"}
        expected_policies = {"preserve_same_provider", "strip", "transform_to_text"}
        assert set(get_args(ReasoningPolicy)) == expected_policies


class TestModelProfile:
    """Тесты для манифеста модели ModelProfile."""

    @pytest.fixture
    def default_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            task_types={"chat"},
            supports_streaming=True,
            supports_tools=True,
        )

    def test_profile_creation_minimal(self, default_capabilities: ModelCapabilities) -> None:
        profile = ModelProfile(
            profile_id="gpt-4o-default",
            model_id="gpt-4o-2024-08-06",
            provider_id="openai",
            capabilities=default_capabilities,
        )
        assert profile.profile_id == "gpt-4o-default"
        assert profile.model_id == "gpt-4o-2024-08-06"
        assert profile.model_name == "gpt 4o 2024 08 06"  # Автоматическая генерация
        assert profile.provider_id == "openai"
        assert profile.api_surface == "openai_chat"
        assert profile.tokenizer_id == "cl100k_base"
        assert profile.limits == ModelLimits()
        assert profile.compatibility == CompatibilityRules()

    def test_profile_creation_explicit_model_name(
        self, default_capabilities: ModelCapabilities
    ) -> None:
        profile = ModelProfile(
            profile_id="gemini-flash",
            model_id="gemini-2.5-flash",
            model_name="Gemini 2.5 Flash",
            provider_id="google",
            api_surface="google_genai",
            capabilities=default_capabilities,
        )
        assert profile.model_name == "Gemini 2.5 Flash"
        assert profile.api_surface == "google_genai"

    def test_profile_api_surface_literals(self) -> None:
        expected = {
            "openai_chat",
            "openai_responses",
            "google_genai",
            "anthropic_messages",
            "jev_grpc",
        }
        assert set(get_args(APISurface)) == expected

    def test_profile_immutability(self, default_capabilities: ModelCapabilities) -> None:
        profile = ModelProfile(
            profile_id="p1",
            model_id="m1",
            provider_id="prov1",
            capabilities=default_capabilities,
        )
        with pytest.raises(ValidationError):
            profile.model_id = "m2"  # type: ignore[misc]

        with pytest.raises(ValidationError):
            profile.limits.max_context_tokens = 999  # type: ignore[misc]

    def test_profile_json_roundtrip(self, default_capabilities: ModelCapabilities) -> None:
        profile = ModelProfile(
            profile_id="claude-sonnet",
            model_id="claude-3-7-sonnet",
            provider_id="anthropic",
            api_surface="anthropic_messages",
            capabilities=default_capabilities,
            compatibility=CompatibilityRules(
                role_sequence_policy="anthropic",
                reasoning_policy="preserve_same_provider",
            ),
        )
        dumped = profile.model_dump(mode="json")
        restored = ModelProfile.model_validate(dumped)
        assert restored == profile

    def test_profile_yaml_methods_roundtrip(self, default_capabilities: ModelCapabilities) -> None:
        profile = ModelProfile(
            profile_id="gemini-pro",
            model_id="gemini-2.5-pro",
            model_name="Gemini 2.5 Pro",
            provider_id="google",
            api_surface="google_genai",
            capabilities=default_capabilities,
            limits=ModelLimits(max_context_tokens=1_000_000, max_output_tokens=8_192),
            compatibility=CompatibilityRules(
                role_sequence_policy="google",
                require_thought_signature_on_tools=True,
            ),
        )
        yaml_str = profile.to_yaml()
        assert isinstance(yaml_str, str)
        assert "Gemini 2.5 Pro" in yaml_str
        assert "google_genai" in yaml_str

        restored = ModelProfile.from_yaml(yaml_str)
        assert restored == profile

    def test_profile_from_file_path_and_str(
        self, default_capabilities: ModelCapabilities, tmp_path: Path
    ) -> None:
        profile = ModelProfile(
            profile_id="deepseek-r1-chat",
            model_id="deepseek-reasoner",
            model_name="DeepSeek R1",
            provider_id="deepseek",
            capabilities=default_capabilities,
            compatibility=CompatibilityRules(
                reasoning_policy="strip",
                preserve_thoughts_in_react=True,
            ),
        )
        file_path = tmp_path / "deepseek.yaml"
        file_path.write_text(profile.to_yaml(), encoding="utf-8")

        # Чтение через Path
        loaded_by_path = ModelProfile.from_file(file_path)
        assert loaded_by_path == profile

        # Чтение через str
        loaded_by_str = ModelProfile.from_file(str(file_path))
        assert loaded_by_str == profile
