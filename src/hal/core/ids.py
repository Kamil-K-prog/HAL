from datetime import datetime
from typing import Final

from ulid import ULID


class IdFactory:
    """
    Фабрика уникальных идентификаторов на базе ULID:
    - Глобальная уникальность (48 бит timestamp + 80 бит random)
    - Лексикографическая сортировка
    - Извлекаемый UTC timestamp
    """

    PREFIX_MESSAGE: Final = "msg"
    PREFIX_TOOL_CALL: Final = "call"
    PREFIX_EVENT: Final = "evt"
    PREFIX_TURN: Final = "trn"
    PREFIX_COMPRESSION: Final = "cmp"
    PREFIX_ASSET: Final = "ast"

    def generate(
        self,
        prefix: str | None = None,
        timestamp: datetime | None = None,
    ) -> str:
        id_ulid = ULID() if timestamp is None else ULID.from_datetime(timestamp)
        return f"{prefix}_{id_ulid}" if prefix else str(id_ulid)

    @staticmethod
    def extract_timestamp(id_str: str) -> datetime:
        if "_" in id_str:
            prefix, ulid_part = id_str.split("_", 1)
            if not prefix:
                raise ValueError(f"Empty prefix in ID: {id_str!r}")
        else:
            ulid_part = id_str
        return ULID.from_str(ulid_part).datetime

    @staticmethod
    def validate(id_str: str) -> bool:
        try:
            IdFactory.extract_timestamp(id_str)
            return True
        except ValueError:
            return False