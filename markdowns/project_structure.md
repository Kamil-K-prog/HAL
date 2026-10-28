```
hal/
├── .github/
├── markdowns/
│   └── architecture_v2.md
├── pyproject.toml                  # Конфигурация uv, зависимости, ruff, pytest, mypy
├── README.md
├── .gitignore
│
├── src/
│   └── hal/
│       ├── __init__.py             # Публичный фасад: экспортирует только главные классы (User-Facing Layer)
│       │
│       ├── core/                   # 🟢 СЛОЙ 0: Чистое доменное ядро (0 зависимостей от SDK и I/O!)
│       │   ├── __init__.py
│       │   ├── ids.py              # IdFactory (ULID)
│       │   ├── errors.py           # FrameworkError, ErrorCategory и классы исключений (TurnInProgressError и др.)
│       │   ├── identity.py         # ModelExecutionIdentity, SwitchReasonCode
│       │   ├── umf.py              # Все модели УФС 2.0: Asset, MessagePart, Message, Event, TurnState, ChatData
│       │   ├── invariants.py       # HistoryInvariantValidator (правила I1–I9), ValidationResult
│       │   ├── profiles.py         # ProviderConfig, RetryPolicy, ModelProfile, Capabilities, Limits
│       │   ├── ports.py            # Все Protocol-интерфейсы (ChatGenerationPort, EmbeddingPort, AssetStore и др.)
│       │   └── cancellation.py     # CancellationToken
│       │
│       ├── session/                # 🔵 СЛОЙ 1: Управление состоянием и персистентность
│       │   ├── __init__.py
│       │   ├── chat_session.py     # ChatSession (Aggregate Root), CommitResult
│       │   ├── store.py            # Реализации HistoryStore (JsonFileHistoryStore, InMemoryHistoryStore)
│       │   └── migrator.py         # SchemaMigrator (цепочки миграций JSON)
│       │
│       ├── assets/                 # 🔵 СЛОЙ 1: Менеджер ассетов и локальные/облачные хранилища
│       │   ├── __init__.py
│       │   ├── manager.py          # AssetManager (координация хешей, размеров и CloudStorageDriver)
│       │   └── stores.py           # Реализации AssetStore (LocalDiskAssetStore, InMemoryAssetStore)
│       │
│       ├── context/                # 🟡 СЛОЙ 2: Проекция контекста и компрессия (ContextPreprocessor)
│       │   ├── __init__.py
│       │   ├── preprocessor.py     # Фасад ContextPreprocessor, PreparedContext, CompatibilityIssue
│       │   ├── fallback.py         # MediaFallbackStrategy, MediaFallbackPolicy
│       │   ├── normalizer.py       # RoleSequenceNormalizer, ReasoningAndExtensionStrategy
│       │   └── budgeter.py         # ContextBudgeter и стратегии сжатия (truncate_old_tools и др.)
│       │
│       ├── tools/                  # 🟡 СЛОЙ 2: Подсистема инструментов
│       │   ├── __init__.py
│       │   ├── models.py           # Tool, ToolPolicy, ToolOutput, ToolExecutionOutcome, ApprovalDecision
│       │   ├── registry.py         # ToolsRegistry (инспекция сигнатур и docstring -> JSON Schema)
│       │   ├── validator.py        # ToolCallValidator (проверка до вызова функции)
│       │   ├── normalizer.py       # OutputNormalizer, CanonicalJsonEncoder
│       │   └── executor.py         # ToolExecutor (семафоры, thread/process пулы, ApprovalPort)
│       │
│       ├── adapters/               # 🟠 СЛОЙ 3: Фасады одиночных шагов (LLM, RAG, Jev, Media)
│       │   ├── __init__.py
│       │   ├── chat.py             # ModelAdapter, SyncModelAdapter, GenerationResult
│       │   ├── embedding.py        # EmbeddingAdapter, EmbeddingResult
│       │   ├── classifier.py       # ClassifierAdapter, ClassificationResult (под Jev и др.)
│       │   └── media.py            # MediaGenAdapter, MediaGenerationResult
│       │
│       ├── runner/                 # 🟠 СЛОЙ 3: Оркестратор ReAct и потоковые события
│       │   ├── __init__.py
│       │   ├── events.py           # Иерархия RunnerEvent (ContentDeltaEvent, ToolEvent, RunCompletedEvent...)
│       │   ├── policy.py           # RunPolicy, TurnFinishReason
│       │   ├── runner.py           # Runner (асинхронный оркестратор)
│       │   └── sync.py             # SyncRunner, BackgroundLoopPortal (для синхронного запуска)
│       │
│       ├── telemetry/              # 🟣 СЛОЙ 4: Наблюдаемость и безопасность
│       │   ├── __init__.py
│       │   ├── redactor.py         # Redactor (маскирование api_key, секретов и локальных путей)
│       │   └── logger.py           # Стандартная реализация TelemetryPort
│       │
│       ├── drivers/                # 🔴 СЛОЙ 5: Сетевые драйверы (ЕДИНСТВЕННОЕ место, где импортируются внешние SDK!)
│       │   ├── __init__.py
│       │   ├── registry.py         # DriverRegistry
│       │   ├── openai/
│       │   │   ├── __init__.py
│       │   │   ├── chat_driver.py      # OpenAiChatDriver
│       │   │   ├── responses_driver.py # OpenAiResponsesDriver
│       │   │   ├── schema_compiler.py  # OpenAiStrictSchemaCompiler
│       │   │   ├── embedding_driver.py # OpenAiEmbeddingDriver
│       │   │   └── storage_driver.py   # OpenAiStorageDriver / MoonshotStorageDriver
│       │   ├── google/
│       │   │   ├── __init__.py
│       │   │   ├── genai_driver.py     # GoogleGenaiDriver (Gemini, Imagen, Veo)
│       │   │   ├── schema_compiler.py  # GoogleGenaiSchemaCompiler
│       │   │   └── storage_driver.py   # GoogleGenaiStorageDriver (Files API 48h TTL)
│       │   └── jev/
│       │       ├── __init__.py
│       │       └── classifier_driver.py # Драйвер под классификатор Jev
│       │
│       └── builtin_profiles/       # Декларативные YAML/JSON профили популярных моделей "из коробки"
│           ├── gemini_2_5_flash.yaml
│           ├── deepseek_chat.yaml
│           └── gpt_4o.yaml
│
└── tests/
    ├── unit/                       # Быстрые тесты без I/O (core, invariants, normalizer, validator)
    ├── contract/                   # Контрактные тесты драйверов на записанных JSON-фикстурах
    └── concurrency/                # Стресс-тесты ChatSession, TurnState и Runner с asyncio.sleep
```