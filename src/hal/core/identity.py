"""
Классы для определения сущности моделей
"""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

SwitchReasonCode = Literal[  # Почему была изменена модель
    "user_request",  # Пользователь сменил модель
    "config_change",  # Пользователь поменял настройки генерации без смены самой модели
    "context_limit",  # fallback из-за превышения контекстного окна
    "provider_error",  # fallback из-за ошибки провайдера
    "capability_fallback",  # fallback из-за недостатка "способностей" модели
]


class ModelExecutionIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider_id: str
    provider_instance_id: str = "default"
    model_id: str
    api_surface: str
    profile_id: str | None = None
    configuration_fingerprint: str = "default"

    @staticmethod
    def get_configuration_fingerprint(config: dict[str, Any] | None = None) -> str:
        """
        Возвращает хэш текущей конфигурации модели в виде шестнадцатеричной строки
        """
        if not config:
            return "default"
        return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()
