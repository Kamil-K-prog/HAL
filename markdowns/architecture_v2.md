# Архитектурная спецификация фреймворка V2

Документ фиксирует финальную архитектуру модульного Python-фреймворка для унифицированной работы с ИИ-провайдерами (LLM/MLLM, генераторы эмбеддингов, классификаторы, генераторы медиа).

---

## 🎯 1. Концепция, назначение и архитектурные гарантии

Фреймворк предоставляет единый доменный слой и инфраструктурное ядро для взаимодействия с гетерогенными API-провайдерами (Google GenAI, OpenAI Chat/Responses, Anthropic, DeepSeek, Moonshot, локальные vLLM/Ollama, специализированные классификаторы вроде Jev и медиа-модели).

### Ключевые архитектурные гарантии:
1. **Единый доменный контракт (УФС 2.0 / UMF v2.0):** бизнес-логика, история диалога и инструменты полностью изолированы от SDK конкретных провайдеров.
2. **Управляемая мутабельность через Aggregate Root (`ChatSession`):** история диалога изменяется исключительно через идемпотентные атомарные транзакции (`append_turn`) с оптимистичной блокировкой (`expected_version`) и защитой активного хода (`TurnState`).
3. **Совместимая смена моделей (Compatibility-Driven Switching):** история диалога сохраняется всегда, а переключение между моделями и провайдерами сопровождается явной валидацией возможностей (`ModelProfile`), проекцией контекста (`ContextPreprocessor`), мультимодальным фоллбэком и диагностическим отчётом совместимости (`CompatibilityIssue`).
4. **Детерминированный и безопасный ReAct-цикл:** строгая валидация вызовов до исполнения (`ToolCallValidator`), классификация ошибок (`FrameworkError`), идемпотентность, контроль бюджета (`RunPolicy`) и асинхронный Human-in-the-Loop (`ApprovalPort`).
5. **Async-First ядро с синхронными фасадами:** канонический контур исполнения полностью асинхронный (`async`/`await`, `AsyncIterator`), а для скриптов без собственного Event Loop предоставляются безопасные синхронные обёртки (`SyncRunner`, `SyncModelAdapter`).
6. **Мультизадачное ядро (Multi-Task AI Kernel):** сетевой транспорт, профили моделей, ретраи, телеметрия и файловый менеджер (`AssetManager`) переиспользуются между диалоговыми LLM, эмбеддерами (RAG), классификаторами и генераторами медиа.

---

## 🏛️ 2. Уровень 1: Высокоуровневая архитектура и разделение ответственности

### 2.1. Публичная поверхность (Public API) и внутренние порты

Для снижения когнитивной нагрузки фреймворк разделяет **публичные точки входа** и **внутренние инфраструктурные порты**:

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│                              Пользовательский код / UI                             │
└──────┬──────────────────────┬───────────────────────┬───────────────────────┬──────┘
       │ (История и стейт)    │ (Многошаговый ReAct)  │ (Одиночный шаг LLM)   │ (RAG / Jev / Media)
       ▼                      ▼                       ▼                       ▼
┌──────────────┐       ┌──────────────┐        ┌──────────────┐       ┌─────────────────────┐
│ ChatSession  │◄──────┤    Runner    ├───────►│ ModelAdapter │       │ SpecializedAdapters │
│ (Aggregate)  │       │ (Оркестратор)│        │ (Фасад LLM)  │       │ - EmbeddingAdapter  │
└──────────────┘       └──────┬───────┘        └──────┬───────┘       │ - ClassifierAdapter │
                              │                       │               │ - MediaGenAdapter   │
                              ▼                       │               └──────────┬──────────┘
                       ┌──────────────┐               │                          │
                       │ ToolExecutor │               ▼                          ▼
                       │ + Registry   │        ┌────────────────────────────────────────────┐
                       └──────────────┘        │       Общее ядро (Shared AI Kernel)        │
                                               │ • ProviderConfig & ModelProfile            │
                                               │ • Capability Ports (Chat, Embed, Classify) │
                                               │ • AssetManager & AssetStore                │
                                               │ • ContextPreprocessor & RetryPolicy        │
                                               │ • TelemetryPort & Redactor                 │
                                               └────────────────────────────────────────────┘
```

#### Публичные сущности (User-Facing Layer):
1. **`ChatSession` (Aggregate Root):** единственный владелец мутабельного состояния истории (`messages`), аудиторского потока (`events`) и runtime-состояния активного хода (`TurnState`).
2. **`Runner` (Оркестратор ReAct):** управляет многошаговым циклом генерации, вызовом инструментов, проверкой бюджетов (`RunPolicy`), жизненным циклом `TurnState` и стримингом событий `RunnerEvent`.
3. **`ModelAdapter` (Диалоговый фасад):** отвечает строго за **один сетевой шаг (turn)** генерации текста/структурированных данных/тулов. Не хранит историю, не запускает инструменты и не мутирует `ChatSession`.
4. **Специализированные адаптеры (`EmbeddingAdapter`, `ClassifierAdapter`, `MediaGenAdapter`):** предоставляют типобезопасные интерфейсы для не-диалоговых задач поверх общего ядра провайдеров.
5. **`ToolsRegistry` и `ToolExecutor`:** отвечают за регистрацию, компиляцию JSON-схем, пре-валидацию аргументов, проверку прав (`ToolPolicy` / `ApprovalPort`) и изолированное исполнение функций.

---

### 2.2. Граница синхронного и асинхронного контуров (Async-First Contract)

Все внутренние компоненты (`Capability Ports`, `AssetManager`, `ContextPreprocessor`, `ToolExecutor`, `ChatSession`) имеют **единый канонический асинхронный интерфейс**. Это исключает скрытый запуск `asyncio.run()` внутри работающего Event Loop и расхождение поведения между ветками кода.

- **Канонический API (`async`):**
  - `await adapter.generate(...) -> GenerationResult`
  - `adapter.stream(...) -> AsyncIterator[RunnerEvent]`
  - `await runner.run(session, ...) -> RunResult`
  - `runner.stream(session, ...) -> AsyncIterator[RunnerEvent]`
- **Синхронный фасад (`SyncRunner`, `SyncModelAdapter`):**
  - Предназначен для CLI-утилит и синхронных скриптов.
  - Управляет выделенным фоновым потоком с Event Loop (`BackgroundLoopPortal`), проксируя вызовы в канонический `async`-пайплайн.
  - Гарантирует 100% идентичность валидации, ретраев, порядка событий и обработки ошибок.

---

### 2.3. Конвейер подготовки контекста и выполнения шага (Pipeline)

Каждый шаг обращения к модели в рамках `Runner` проходит через строго детерминированный конвейер:

```
[ChatSession.snapshot() -> ChatData]
      │
      ▼
1. ┌────────────────────────┐ (AssetManager + AssetStore: Inbound)
   │  Разрешение ассетов    │ Проверка целостности (SHA-256), загрузка в Files API провайдера
   │  и контроль TTL        │ (если размер > лимита inline), обновление CloudRef.
   └──────────┬─────────────┘
              ▼
2. ┌────────────────────────┐ (ContextPreprocessor: Ephemeral Projection)
   │  Валидация, бюджет     │ • HistoryInvariantValidator (проверка I1–I6)
   │  и проекция контекста  │ • MediaFallbackStrategy (PDF/Audio/Image -> RepresentationCache)
   │                        │ • Reasoning & Provider Extensions Policy (preserve/strip/drop)
   │                        │ • RoleNormalizer (слияние ролей, system -> user при необходимости)
   │                        │ • ContextBudgeter (применение CompressionCheckpoint и лимитов окна)
   └──────────┬─────────────┘
              ▼  [PreparedContext (read-only проекция)]
3. ┌────────────────────────┐ (ModelAdapter + CapabilityPort + RetryPolicy + AssetManager: Outbound)
   │  Сетевой шаг и         │ • PromptCompiler (чистая функция + подстановка inline данных из AssetStore)
   │  парсинг ответа        │ • Transport Execution (с единой RetryPolicy и идемпотентностью)
   │                        │ • ResponseParser (чистая функция -> RawGenerationResult)
   │                        │ • Материализация сгенерированных медиа в AssetStore
   └──────────┬─────────────┘
              │
              ▼
[GenerationResult] ──► (Валидация и вызов тулов при наличии) ──► [ChatSession.append_turn()]
```

---

## ⚙️ 3. Уровень 2: Провайдеры, профили моделей и Capability-порты

### 3.1. Ортогональное разделение: `ProviderConfig` и `ModelProfile`

Для предотвращения комбинаторного взрыва классов инфраструктура отделена от декларативных характеристик модели:

```python
class RetryPolicy(BaseModel):
    """Единая политика повторов сетевых запросов на уровне транспорта."""
    max_attempts: int = 3
    initial_backoff_sec: float = 1.0
    max_backoff_sec: float = 30.0
    backoff_multiplier: float = 2.0
    jitter: bool = True
    retryable_status_codes: tuple[int, ...] = (408, 429, 500, 502, 503, 504)


class ProviderConfig(BaseModel):
    """Инфраструктурная конфигурация хостинга и авторизации."""
    provider_id: str                           # "openai", "genai", "moonshot", "local_vllm", "jev_local"
    provider_instance_id: str                  # Безопасный ID инстанса/аккаунта (без секретов, для аудит-трейла)
    base_url: Optional[str] = None
    api_key_env_var: Optional[str] = None      # Имя переменной окружения (сам ключ не сериализуется в логи/снимки)
    timeout_sec: float = 60.0
    default_headers: dict[str, str] = Field(default_factory=dict)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
```

```python
class ModelCapabilities(BaseModel):
    """Декларативная матрица возможностей модели."""
    task_types: set[Literal["chat", "embedding", "classification", "image_gen", "audio_gen", "video_gen"]]
    supports_streaming: bool = True
    supports_tools: bool = False
    supports_parallel_tool_calls: bool = False
    supports_strict_tool_schema: bool = False
    supports_structured_output: bool = False
    supports_prompt_caching: bool = False
    input_modalities: set[Literal["text", "image", "audio", "video", "document"]] = {"text"}
    output_modalities: set[Literal["text", "image", "audio", "video"]] = {"text"}


class ModelLimits(BaseModel):
    """Бюджетные и протокольные лимиты модели."""
    max_context_tokens: int = 128_000
    max_output_tokens: int = 4_096
    reserve_output_tokens: int = 1_024
    max_inline_asset_bytes: int = 15 * 1024 * 1024  # Вместо хардкода 20 МБ
    allowed_mime_types: Optional[set[str]] = None   # None = все для поддерживаемых модальностей


class CompatibilityRules(BaseModel):
    """Правила проекции истории под капризы конкретного протокола."""
    role_sequence_policy: Literal["openai", "google", "anthropic", "generic"] = "openai"
    reasoning_policy: Literal["preserve_same_provider", "strip", "transform_to_text"] = "preserve_same_provider"
    require_thought_signature_on_tools: bool = False  # True для Gemini 2.5/3 Thinking
    disallowed_generation_params: set[str] = Field(default_factory=set)  # Например, {"temperature"} для o1/o3


class ModelProfile(BaseModel):
    """Полная декларативная спецификация модели (может загружаться из JSON/YAML)."""
    profile_id: str
    model_name: str
    provider_id: str
    api_surface: str                           # "openai_chat", "openai_responses", "google_genai", "jev_grpc", ...
    capabilities: ModelCapabilities
    limits: ModelLimits = Field(default_factory=ModelLimits)
    compatibility: CompatibilityRules = Field(default_factory=CompatibilityRules)
    tokenizer_id: str = "cl100k_base"
```

---

### 3.2. Capability-порты вместо монолитного `BaseApiDriver` (Соблюдение ISP и LSP)

Вместо одного «толстого» интерфейса драйвера, вынуждающего ставить `NotImplementedError` для неподдерживаемых фич, сетевой уровень разделён на атомарные протоколы возможностей (**Capability Ports**):

```python
class ChatGenerationPort(Protocol):
    """Порт одиночной генерации ответа в диалоге."""
    async def generate(
        self,
        context: PreparedContext,
        tools_schema: Optional[list[Any]],
        response_schema: Optional[type[BaseModel] | dict[str, Any]],
        profile: ModelProfile,
        provider: ProviderConfig,
        token: Optional[CancellationToken] = None,
    ) -> RawGenerationResult: ...


class StreamingChatPort(Protocol):
    """Порт потоковой генерации ответа (возвращает внутренние чанки адаптера)."""
    def stream(
        self,
        context: PreparedContext,
        tools_schema: Optional[list[Any]],
        response_schema: Optional[type[BaseModel] | dict[str, Any]],
        profile: ModelProfile,
        provider: ProviderConfig,
        token: Optional[CancellationToken] = None,
    ) -> AsyncIterator[DriverStreamChunk]: ...


class EmbeddingPort(Protocol):
    """Порт генерации векторных представлений (для RAG-систем)."""
    async def embed(
        self,
        inputs: list[str | Asset],
        profile: ModelProfile,
        provider: ProviderConfig,
        dimensions: Optional[int] = None,
        task_type: Optional[str] = None,  # Например, "RETRIEVAL_QUERY" / "RETRIEVAL_DOCUMENT"
    ) -> EmbeddingResult: ...


class ClassificationPort(Protocol):
    """Порт классификации текста или мультимодальных данных (например, Jev и др.)."""
    async def classify(
        self,
        inputs: list[str | Asset],
        profile: ModelProfile,
        provider: ProviderConfig,
        candidate_labels: Optional[list[str]] = None,
        top_k: int = 5,
    ) -> ClassificationResult: ...


class MediaGenerationPort(Protocol):
    """Порт генерации изображений, аудио (TTS) и видео (включая polling долгих задач)."""
    async def generate_media(
        self,
        prompt: str,
        reference_assets: list[Asset],
        profile: ModelProfile,
        provider: ProviderConfig,
        params: dict[str, Any],
        token: Optional[CancellationToken] = None,
    ) -> RawMediaResult: ...
```

**Преимущества:**
- Адаптер проверяет `profile.capabilities` и наличие нужного порта в драйвере **до** сетевого вызова. Если модель не поддерживает стриминг или тулы, выбрасывается типизированная ошибка `UnsupportedCapabilityError` (Fail Fast).
- Реализации драйверов (`OpenAiChatDriver`, `OpenAiResponsesDriver`, `GoogleGenaiDriver`, `JevClassifierDriver`) реализуют только те протоколы, которые физически поддерживают.

---

### 3.3. Специализированные адаптеры для не-LLM задач (Embeddings, Classifiers, Media)

Благодаря общему ядру работа с RAG, классификаторами и генераторами медиа использует те же настройки провайдера, пулы соединений, подсчёт токенов и `AssetManager`:

```python
@dataclass
class EmbeddingVector:
    index: int
    vector: list[float]
    object_id: Optional[str] = None

@dataclass
class EmbeddingResult:
    vectors: list[EmbeddingVector]
    dimensions: int
    model_name: str
    usage: UsageStats

@dataclass
class ClassificationPrediction:
    label: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class ClassificationResult:
    predictions: list[list[ClassificationPrediction]]  # По одному списку на каждый входной элемент
    model_name: str
    latency_ms: int
```

- **`EmbeddingAdapter.embed(inputs)`:** автоматически батчит запросы по лимитам `ModelProfile`, конвертирует `Asset` при мультимодальных эмбеддингах и применяет `RetryPolicy`.
- **`ClassifierAdapter.classify(inputs)`:** унифицирует вызовы к внешним и локальным классификаторам (например, Jev), возвращая нормализованные распределения вероятностей (`ClassificationResult`).
- **`MediaGenAdapter.generate(prompt, assets)`:** вызывает `MediaGenerationPort`, автоматически сохраняет полученные байты через `AssetManager` в `AssetStore` и возвращает готовые объекты `Asset`.

---

### 3.4. Идентичность исполнения (`ModelExecutionIdentity`) и защита хода (Mid-Turn Guard)

Для надёжного отслеживания происхождения вызовов инструментов и идемпотентного переключения моделей вводится нормализованная структура идентичности:

```python
SwitchReasonCode = Literal[
    "user_request",
    "context_limit",
    "provider_error",
    "capability_fallback",
    "config_change",
]

class ModelExecutionIdentity(BaseModel):
    """Нормализованная криптографически устойчивая идентичность конфигурации модели."""
    provider_id: str
    provider_instance_id: str                  # Безопасный ID хоста/аккаунта без API-ключа
    model_name: str
    api_surface: str
    profile_id: str
    configuration_fingerprint: str             # SHA-256 от канонического JSON значимых параметров генерации и тулов
```

#### Правила Mid-Turn Guard и переключения моделей:
1. **Единственный источник истины — `TurnState`:** `ChatSession` хранит явное состояние активного хода (`active_turn`). Эвристики по «последнему сообщению в списке» запрещены.
2. **Блокировка переключения:** пока `active_turn` находится в нетерминальном статусе (`generating`, `awaiting_tool_results`, `awaiting_model`, `committing`), вызов `session.switch_model()` выбрасывает `ModelSwitchMidTurnError`.
3. **Точная идемпотентность:** `switch_model()` сравнивает полный `ModelExecutionIdentity`. Если изменился `api_surface`, системный промпт или `provider_instance_id` при том же `model_name`, событие переключения корректно фиксируется.
4. **Структурированная причина:** `switch_model(new_identity, reason_code="capability_fallback", reason_detail="...")` записывает машиночитаемую причину в аудиторский `Event`.

---

## 🛠️ 4. Уровень 3: Подсистема инструментов, валидация и безопасность

### 4.1. Каноническая модель инструмента (`Tool`) и политика безопасности (`ToolPolicy`)

Регистрация Python-функции в `ToolsRegistry` не является песочницей (sandbox), поэтому каждый инструмент снабжается явной декларацией побочных эффектов и политикой исполнения:

```python
class ToolPolicy(BaseModel):
    """Декларативная политика безопасности, ретраев и изоляции инструмента."""
    side_effect_level: Literal["pure", "idempotent", "non_idempotent"] = "non_idempotent"
    requires_approval: bool = False            # Требует ли подтверждения через ApprovalPort (HITL)
    timeout_sec: float = 30.0                  # Тайм-аут выполнения одного вызова
    max_output_bytes: int = 256 * 1024         # Защита контекста от гигантских ответов (256 КБ)
    execution_mode: Literal["async_native", "thread_pool", "process_worker"] = "thread_pool"
    allowed_capabilities: set[Literal["network", "filesystem", "database", "subprocess"]] = Field(default_factory=set)


class Tool:
    name: str
    description: str
    parameters_schema: dict[str, Any]          # Каноническая JSON Schema (Draft 7 / 2020-12)
    return_schema: Optional[dict[str, Any]]    # Схема возвращаемого значения (если аннотировано)
    handler: Callable[..., Any]
    is_async: bool
    accepts_cancellation_token: bool           # Принимает ли функция параметр token: CancellationToken
    policy: ToolPolicy
```

- **Изолированный реестр (`ToolsRegistry`):** инстанцируемый контейнер без глобального состояния. Парсит сигнатуры и docstrings один раз при регистрации.
- **Компиляция схем (`BaseSchemaCompiler`):** `ToolsRegistry` не зависит от SDK провайдеров. Специфичные компиляторы (`OpenAiStrictSchemaCompiler`, `GoogleGenaiSchemaCompiler`) транслируют `Tool.parameters_schema` непосредственно перед вызовом `ChatGenerationPort`.

---

### 4.2. Пре-валидация вызовов (`ToolCallValidator`)

Между парсером ответа модели и `ToolExecutor` работает чистый компонент `ToolCallValidator`, который проверяет каждый `ToolCallPart` **до** запуска пользовательского кода:

1. **`unknown_tool`:** запрошенное имя отсутствует в `ToolsRegistry`.
2. **`malformed_payload`:** аргументы не удалось распарсить как валидный JSON-объект.
3. **`invalid_arguments`:** аргументы не проходят валидацию по `Tool.parameters_schema`.
4. **`duplicate_call_id`:** нарушение инварианта уникальности `call_id`.
5. **`policy_denied`:** инструмент запрещён активной политикой `RunPolicy.allowed_tools`.

Если валидация не пройдена, код инструмента **не вызывается**, а формируется детерминированный `ToolExecutionOutcome` с категорией ошибки `validation_error` и безопасным текстом для самокоррекции модели.

---

### 4.3. Нормализация вывода (`OutputNormalizer`) и единый результат (`ToolExecutionOutcome`)

Для устранения рассинхронизации между тем, что уходит в историю UMF, в модель и в UI-стрим, вводится единый контейнер `ToolExecutionOutcome`:

```python
class ToolOutput(BaseModel):
    """Нормализованный результат работы функции."""
    text: str = ""                             # Сериализованное представление для контекста LLM (усечённое по max_output_bytes)
    structured_data: Optional[Any] = None      # Оригинальные JSON-совместимые данные для UI/логики
    assets: list[Asset] = Field(default_factory=list)
    ui_payload: Optional[dict[str, Any]] = None


@dataclass
class ToolExecutionOutcome:
    """Единый детерминированный результат выполнения вызова инструмента."""
    call_id: str
    tool_name: str
    status: Literal["completed", "failed", "cancelled", "denied"]
    output: ToolOutput
    result_part: ToolResultPart                # Готовая часть для записи в UMF Message(role="tool")
    error: Optional[FrameworkError] = None
    duration_ms: int = 0
```

#### Правила работы `OutputNormalizer` (внутри `ToolExecutor`):
- Владеет ссылкой на `AssetManager` для сохранения бинарных выходов (`bytes` -> `AssetStore` -> `Asset`).
- Сериализует `BaseModel` через `.model_dump(mode="json")`, а словари `dict`, списки, `datetime`, `Decimal`, `UUID` и `dataclass` — через кастомный `CanonicalJsonEncoder` (`json.dumps(..., default=...)`).
- Контролирует лимит `ToolPolicy.max_output_bytes`: при превышении обрезает `text` для модели с маркером `[...Output truncated due to budget limit...]`, предотвращая переполнение контекстного окна.

---

### 4.4. Исполнитель инструментов (`ToolExecutor`), Async HITL и семантика отмены

```python
class ApprovalDecision(BaseModel):
    """Решение человека/политики по вызову инструмента (Async HITL)."""
    action: Literal["allow", "deny", "cancel_turn"]
    reason: Optional[str] = None
    modified_args: Optional[dict[str, Any]] = None


class ApprovalPort(Protocol):
    """Асинхронный порт подтверждения действий пользователем (UI / Webhook / CLI)."""
    async def request_approval(
        self,
        tool_call: ToolCallPart,
        turn_id: str,
        timeout_sec: float,
    ) -> ApprovalDecision: ...
```

```python
class ToolExecutor:
    """
    Отвечает за безопасное локальное исполнение инструментов:
    - Пре-валидация через ToolCallValidator.
    - Асинхронный запрос разрешения через ApprovalPort (если policy.requires_approval=True).
    - Управление параллелизмом через единый семафор инстанса.
    - Честная обработка отмены (cooperative token vs process kill).
    - Строгое сохранение порядка результатов в execute_batch().
    """
    def __init__(
        self,
        registry: ToolsRegistry,
        asset_manager: AssetManager,
        validator: Optional[ToolCallValidator] = None,
        approval_port: Optional[ApprovalPort] = None,
        max_parallel_tools: int = 5,
    ): ...

    async def execute(
        self,
        tool_call: ToolCallPart,
        turn_id: str,
        token: Optional[CancellationToken] = None,
    ) -> ToolExecutionOutcome: ...

    async def execute_batch(
        self,
        tool_calls: list[ToolCallPart],
        turn_id: str,
        allow_parallel: bool = True,
        token: Optional[CancellationToken] = None,
    ) -> list[ToolExecutionOutcome]:
        """
        Возвращает список ToolExecutionOutcome строго в порядке входного списка tool_calls,
        независимо от того, в каком порядке завершились параллельные задачи.
        Если allow_parallel=False (ограничение профиля модели), выполняет строго последовательно.
        """
```

#### Честная семантика отмены синхронных инструментов:
Поскольку `asyncio.to_thread()` не может принудительно убить поток Python в ОС, фреймворк разделяет состояния `cancel_requested` и `execution_stopped`:
1. **Кооперативная отмена (`thread_pool`):** если синхронная функция принимает `token: CancellationToken`, она сама периодически проверяет `token.raise_if_cancelled()`. Если не принимает — при отмене хода `Runner` перестаёт ждать поток по тайм-ауту, но в аудит записывается предупреждение, что фоновый поток мог продолжить выполнение.
2. **Принудительная изоляция (`process_worker`):** для тяжёлых или недоверенных синхронных инструментов указывается `execution_mode="process_worker"`. При отмене или тайм-ауте дочерний процесс гарантированно завершается через `SIGTERM`/`SIGKILL` с фиксацией `execution_stopped`.

---

## 🔄 5. Уровень 4: Оркестратор ReAct (`Runner`), бюджеты (`RunPolicy`) и потоковый протокол

### 5.1. Бюджеты и ограничения выполнения (`RunPolicy`)

Для защиты от зависаний, бесконечных циклов и неконтролируемого расхода токенов `Runner` руководствуется декларативной политикой `RunPolicy`:

```python
FinishReason = Literal[
    "stop",                  # Естественное завершение ответа моделью
    "max_iterations",        # Достигнут лимит шагов ReAct
    "max_tool_calls",        # Достигнут общий лимит вызовов инструментов за ход
    "token_budget_exceeded", # Превышен лимит токенов за ход
    "deadline_exceeded",     # Истёк общий тайм-аут хода (wall-clock deadline)
    "cancelled",             # Отменено пользователем через CancellationToken
    "policy_denied",         # Прервано решением HITL (cancel_turn)
    "error",                 # Прервано из-за невосстановимой ошибки
]

class RunPolicy(BaseModel):
    """Конфигурация защитных лимитов одного запуска Runner."""
    max_iterations: int = 5
    max_total_tool_calls: int = 15
    max_turn_tokens: Optional[int] = None
    wall_clock_timeout_sec: float = 180.0
    allowed_tools: Optional[set[str]] = None   # None = все из реестра
    allow_parallel_tools: bool = True          # Пересекается с ModelProfile.capabilities.supports_parallel_tool_calls
```

---

### 5.2. Жизненный цикл хода и честная семантика Rollback

```
                     ┌────────────────────────┐
                     │          IDLE          │
                     └───────────┬────────────┘
                                 │ session.begin_turn()
                                 ▼
              ┌────► ┌────────────────────────┐
              │      │       GENERATING       │ ───────┐
              │      └───────────┬────────────┘        │
              │                  │ (tool_calls)        │ (ошибка / отмена)
  (результаты │                  ▼                     ▼
    готовы)   │      ┌────────────────────────┐   ┌────────────────────┐
              └──────┤  AWAITING_TOOL_RESULTS │──►│ FAILED / CANCELLED │
                     └────────────────────────┘   └─────────┬──────────┘
                                 │ (финальный ответ)        │
                                 ▼                          ▼
                     ┌────────────────────────┐   ┌────────────────────┐
                     │       COMMITTING       │   │ session.close_turn │
                     └───────────┬────────────┘   └────────────────────┘
                                 │ session.append_turn() + close_turn()
                                 ▼
                     ┌────────────────────────┐
                     │          IDLE          │
                     └────────────────────────┘
```

#### Семантика Tentative vs Committed и честный Rollback:
1. **Стриминговые события не являются коммитом истории:** во время фазы `GENERATING` чанки текста (`ContentDeltaEvent`) транслируются в UI со статусом `commit_status="tentative"`.
2. **Буферизация аргументов инструментов:** чанки JSON-аргументов тулов при стриминге собираются во внутреннем буфере драйвера и **не публикуются** наружу как вызов инструмента, пока JSON не будет полностью собран и проверен. Если стрим оборван посередине генерации аргументов тула, невалидный JSON отбрасывается.
3. **Границы Rollback:** термин «откат» (rollback) применяется **исключительно к незакоммиченному буферу сообщений текущего хода**. Фреймворк гарантирует, что при отмене или сбое в `ChatSession.messages` не попадёт битая или незавершённая цепочка `ToolCallPart` без `ToolResultPart`. Внешние побочные эффекты уже выполненных инструментов откату со стороны фреймворка не подлежат и отражаются в `Event(type="cancellation")`.

---

### 5.3. Единая каноническая иерархия событий (`RunnerEvent`)

Устранены любые расхождения между внутренними и внешними потоками: публичный стрим `Runner.stream()` эмитит строго типизированный Discriminated Union `RunnerEvent` с монотонной нумерацией `sequence_no` и `turn_id`:

```python
class BaseRunnerEvent(BaseModel):
    turn_id: str
    sequence_no: int                           # Монотонный номер события внутри turn_id (1, 2, 3...)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    commit_status: Literal["tentative", "committed"] = "tentative"


class ContentDeltaEvent(BaseRunnerEvent):
    """Инкрементальный чанк текста ответа модели."""
    type: Literal["content_delta"] = "content_delta"
    text: str


class ThinkingDeltaEvent(BaseRunnerEvent):
    """Инкрементальный чанк рассуждений (CoT / reasoning)."""
    type: Literal["thinking_delta"] = "thinking_delta"
    text: str


class ToolEvent(BaseRunnerEvent):
    """Единое событие жизненного цикла вызова инструмента."""
    type: Literal["tool_event"] = "tool_event"
    call_id: str
    name: str
    status: Literal["call_validated", "awaiting_approval", "running", "completed", "failed", "cancelled", "denied"]
    args: Optional[dict[str, Any]] = None
    output: Optional[ToolOutput] = None
    error: Optional[FrameworkError] = None
    duration_ms: Optional[int] = None


class AssetProcessingEvent(BaseRunnerEvent):
    """Событие фоновой обработки ассета (загрузка в облако, дескрайбинг, транскрибация)."""
    type: Literal["asset_processing"] = "asset_processing"
    asset_id: str
    action: Literal["upload", "describe", "transcribe", "ocr", "materialize"]
    status: Literal["started", "finished", "failed"]
    mime_type: Optional[str] = None
    error: Optional[FrameworkError] = None


class StepCompletedEvent(BaseRunnerEvent):
    """Завершение одного сетевого шага модели внутри ReAct-цикла."""
    type: Literal["step_completed"] = "step_completed"
    step_index: int
    message: Message
    usage: UsageStats


class RunErrorEvent(BaseRunnerEvent):
    """Структурированное событие ошибки выполнения."""
    type: Literal["run_error"] = "run_error"
    error: FrameworkError
    uncommitted_delta: list[Message] = Field(default_factory=list)


class RunCancelledEvent(BaseRunnerEvent):
    """Событие отмены хода по CancellationToken."""
    type: Literal["run_cancelled"] = "run_cancelled"
    reason: str
    uncommitted_delta: list[Message] = Field(default_factory=list)


class RunCompletedEvent(BaseRunnerEvent):
    """Финальное событие успешного завершения ReAct-цикла (после commit в ChatSession)."""
    type: Literal["run_completed"] = "run_completed"
    commit_status: Literal["committed"] = "committed"
    finish_reason: FinishReason
    committed_delta: list[Message]
    total_usage: UsageStats
    new_session_version: int


RunnerEvent = Annotated[
    ContentDeltaEvent
    | ThinkingDeltaEvent
    | ToolEvent
    | AssetProcessingEvent
    | StepCompletedEvent
    | RunErrorEvent
    | RunCancelledEvent
    | RunCompletedEvent,
    Field(discriminator="type"),
]
```

#### Управление потоком, Backpressure и закрытие стрима (`aclose()`):
- Внутренняя очередь событий между параллельными задачами (например, пачкой инструментов или загрузкой файлов) ограничена по размеру (`asyncio.Queue(maxsize=128)`), что обеспечивает естественный backpressure.
- Генератор `Runner.stream()` оборачивает весь цикл в блок `try ... finally`: если клиент отключается (SSE disconnect) или закрывает генератор через `await stream.aclose()`, `CancellationToken` немедленно активируется, сетевые соединения драйвера закрываются, семафоры освобождаются, а `TurnState` в `ChatSession` гарантированно переводится в статус `cancelled` и закрывается.

---

## 🖼️ 6. Уровень 5: Управление ассетами (`AssetStore`), проекция контекста и компрессия

### 6.1. Жизненный цикл ассета, `AssetStore` и кэш представлений (`AssetRepresentation`)

Чтобы исключить раздувание JSON-истории многомегабайтными строками base64 и поддержать как локальные диски, так и S3/In-Memory хранилища, бинарные данные отделены от метаданных `Asset`:

```
[Входящие байты / Файл]
         │
         ▼
  (status="pending")
         │ AssetStore.put() -> вычисление SHA-256 и запись в хранилище
         ▼
(status="materialized") ──► [При отправке в модель]
                                   ├── Если size <= max_inline_asset_bytes: чтение байт на лету в PromptCompiler
                                   └── Если size > max_inline_asset_bytes: CloudStorageDriver.upload()
                                                 │
                                                 ▼
                                        (status="uploaded") -> кеширование CloudRef с expires_at
```

```python
class AssetRepresentation(BaseModel):
    """Типизированное текстовое представление медиа-файла с ключом применимости."""
    kind: Literal["description", "transcription", "ocr", "extracted_text"]
    text: str
    model_identity: str                        # Какая модель сгенерировала описание
    language: str = "ru"
    content_sha256: str                        # Для автоматической инвалидации при изменении файла
    created_at: datetime
    params: dict[str, Any] = Field(default_factory=dict)


class AssetStore(Protocol):
    """Абстракция физического хранилища бинарных файлов (Local Disk, S3, Memory)."""
    async def put(self, asset_id: str, data: bytes, mime_type: str) -> tuple[str, str, int]:
        """Сохраняет байты и возвращает (storage_uri, sha256, size_bytes)."""
        ...
    async def get_bytes(self, storage_uri: str) -> bytes: ...
    async def delete(self, storage_uri: str) -> None: ...


class CloudStorageDriver(Protocol):
    """Протокол интеграции с облачными Files API провайдеров (Google Files, OpenAI, Moonshot)."""
    async def upload(self, asset: Asset, data_stream: bytes) -> CloudRef: ...
    async def refresh_if_expired(self, asset: Asset, ref: CloudRef, data_stream: bytes) -> CloudRef: ...
    async def delete(self, ref: CloudRef) -> None: ...
```

---

### 6.2. Декомпозиция `ContextPreprocessor` (Паттерн Фасад над Стратегиями)

`ContextPreprocessor` остаётся единой точкой входа для построения провайдер-специфичной проекции (`PreparedContext`), но внутри декомпозирован на специализированные чистые стратегии (соблюдение SRP):

```
                           ┌───────────────────────────┐
                           │    ContextPreprocessor    │
                           │          (Фасад)          │
                           └─────────────┬─────────────┘
         ┌───────────────┬───────────────┼───────────────┬───────────────┐
         ▼               ▼               ▼               ▼               ▼
┌─────────────────┐ ┌──────────┐ ┌──────────────┐ ┌─────────────┐ ┌──────────────┐
│HistoryInvariant │ │MediaFall-│ │ReasoningAnd  │ │RoleSequence │ │Context       │
│Validator (I1-I6)│ │backStrat.│ │ExtensionStrat│ │Normalizer   │ │Budgeter      │
└─────────────────┘ └──────────┘ └──────────────┘ └─────────────┘ └──────────────┘
```

1. **`HistoryInvariantValidator`:** проверяет целостность входного снимка `ChatData`.
2. **`MediaFallbackStrategy`:** проверяет каждый `AssetPart` против `ModelProfile.capabilities.input_modalities` и `allowed_mime_types`. Если модальность не поддерживается целевой моделью:
   - При политике `ERROR` — выбрасывает `UnsupportedMediaError`.
   - При политике `PLACEHOLDER` — в проекции (не в оригинальной истории!) заменяет `AssetPart` на `TextPart("[Вложение {mime_type} пропущено: не поддерживается моделью]")`.
   - При политике `DESCRIBE` — запрашивает из `Asset.representations` подходящее представление (`description` / `transcription` / `ocr`) или вызывает `MediaDescriber`, сохраняя результат в кэш ассета, и подставляет `TextPart` в проекцию.
3. **`ReasoningAndExtensionStrategy`:** управляет переносом провайдер-специфичных полей:
   - Если `ReasoningPart.provider != profile.provider_id`, криптографическая подпись `signature` и несовместимые `provider_extensions` удаляются с записью предупреждения в `CompatibilityIssue(issue_type="provider_state_dropped")`.
   - Если целевая модель требует `thought_signature` на `ToolCallPart` (например, Gemini 2.5/3 внутри одного хода), проверяет её наличие.
4. **`RoleSequenceNormalizer`:** приводит чередование ролей к требованиям протокола (`google` — первое сообщение `user`, строгий альтернейтинг; `anthropic` — вынос `system` в отдельный параметр; слияние соседних однородных ролей).
5. **`ContextBudgeter` и `TokenizerPort`:** оценивает число токенов проекции через `TokenizerPort`. Если размер превышает `max_context_tokens - reserve_output_tokens`:
   - Применяет виртуальную проекцию по последнему `CompressionCheckpoint` из `ChatData.metadata.compression_checkpoints`.
   - Если чекпоинта недостаточно — применяет настроенную стратегию сжатия (`truncate_old_tools`, `sliding_window`, `llm_summary`), возвращая в `PreparedContext` точный отчёт о сжатых/отброшенных сообщениях. Молчаливое удаление истории без фиксации в `applied_transformations` и `CompatibilityIssue` запрещено.

---

## 📦 7. Уровень 6: Универсальный Формат Сообщений (УФС 2.0), Таксономия Ошибок и `ChatSession`

### 7.1. Формальные инварианты УФС 2.0 (I1–I9)

- **I1 (Уникальность ID):** `Message.id`, `ToolCallPart.call_id`, `Asset.id` и `Event.id` глобально уникальны в рамках сессии (генерируются через `IdFactory` на базе ULID).
- **I2 (Чистота ролей):**
  - `system`: только `TextPart`.
  - `user`: `TextPart`, `AssetPart`.
  - `assistant`: `TextPart`, `ReasoningPart`, `AssetPart`, `ToolCallPart`, `StructuredDataPart`.
  - `tool`: только `ToolResultPart`.
- **I3 (Полнота вызовов инструментов):** в зафиксированной истории (`ChatSession.messages`) за сообщением `assistant` с $N$ частями `ToolCallPart` обязано следовать сообщение `tool` (или последовательность сообщений `tool`), содержащее ровно $N$ соответствующих `ToolResultPart` с теми же `call_id`.
- **I4 (Принадлежность вызовов — Ownership):** каждый активный вызов инструмента связан с `ModelExecutionIdentity` через `TurnState.pending_tool_calls`. Смена модели блокируется до закрытия всех pending calls.
- **I5 (Детерминированный порядок):** порядок `ToolResultPart` в пакетном ответе строго соответствует порядку `ToolCallPart`, запрошенных моделью.
- **I6 (Изоляция криптографических подписей):** `ReasoningPart.signature` и `ToolCallPart.provider_extensions` привязаны к породившему их `provider_id` и никогда не отправляются стороннему провайдеру.
- **I7 (Отделение стрима от коммита):** частичные потоковые данные не хранятся в `ChatSession.messages`.
- **I8 (Идемпотентность коммита):** повторный вызов `append_turn` с тем же `turn_id` не изменяет состояние и возвращает закэшированный `CommitResult(was_duplicate=True)`.
- **I9 (Эволюция схемы):** неизвестные части при десериализации сохраняются в контейнер `UnknownPart` (политика `preserve`), предотвращая потерю данных при откатах версий библиотеки.

---

### 7.2. Единая таксономия ошибок (`FrameworkError`)

Вместо булевого флага `is_error` все ошибки во фреймворке представлены структурированной моделью, разделяющей безопасное сообщение для пользователя/модели и внутренний диагностический контекст:

```python
ErrorCategory = Literal[
    "validation_error",        # Невалидные аргументы тула или нарушение инвариантов UMF
    "policy_denied",           # Отказ HITL или нарушение ToolPolicy / RunPolicy
    "tool_execution_error",    # Исключение внутри пользовательской функции инструмента
    "timeout_error",           # Превышение тайм-аута тула или сетевого запроса
    "cancellation_error",      # Прерывание по CancellationToken
    "transport_error",         # Сетевой сбой, DNS, обрыв сокета
    "rate_limit_error",        # HTTP 429 Quota / Rate Limit
    "provider_response_error", # HTTP 4xx/5xx или некорректный формат ответа провайдера
    "capability_error",        # Запрошена неподдерживаемая возможность (UnsupportedCapabilityError)
    "asset_storage_error",     # Ошибка чтения/записи файла или загрузки в облако
    "concurrency_error",       # TurnInProgressError / VersionConflictError / ModelSwitchMidTurnError
]

class FrameworkError(BaseModel):
    """Каноническая сериализуемая модель ошибки фреймворка."""
    code: str                                  # Машиночитаемый код, напр. "TOOL_ARG_SCHEMA_MISMATCH"
    category: ErrorCategory
    retryable: bool = False
    user_message: str                          # Безопасный текст без секретов и путей ОС (для UI и промпта LLM)
    diagnostic_context: dict[str, Any] = Field(default_factory=dict)  # Проходит через Redactor перед логированием
```

---

### 7.3. Модели данных УФС 2.0 (Pydantic V2) и `IdFactory`

```python
import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional
import ulid
from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════════
# 0. ФАБРИКА ИДЕНТИФИКАТОРОВ (ULID)
# ══════════════════════════════════════════════════════════════════

class IdFactory:
    """Генератор монотонных лексикографически сортируемых 128-битных ULID."""
    PREFIX_MESSAGE = "msg"
    PREFIX_TOOL_CALL = "call"
    PREFIX_EVENT = "evt"
    PREFIX_TURN = "trn"
    PREFIX_COMPRESSION = "cmp"
    PREFIX_ASSET = "ast"

    def generate(self, prefix: Optional[str] = None, timestamp: Optional[datetime] = None) -> str:
        id_ulid = ulid.new() if timestamp is None else ulid.from_timestamp(timestamp)
        return f"{prefix}_{id_ulid.str}" if prefix else id_ulid.str

    @staticmethod
    def extract_timestamp(id_str: str) -> datetime:
        ulid_part = id_str.split("_", 1)[1] if "_" in id_str else id_str
        return ulid.from_str(ulid_part).timestamp().datetime

    @staticmethod
    def validate(id_str: str) -> bool:
        try:
            ulid_part = id_str.split("_", 1)[1] if "_" in id_str else id_str
            ulid.from_str(ulid_part)
            return True
        except ValueError:
            return False


# ══════════════════════════════════════════════════════════════════
# 1. АССЕТЫ, ПРЕДСТАВЛЕНИЯ И ОБЛАЧНЫЕ ССЫЛКИ
# ══════════════════════════════════════════════════════════════════

class CloudRef(BaseModel):
    """Ссылка на файл во внешнем Files API провайдера."""
    provider_id: str
    cloud_id: Optional[str] = None
    uri: Optional[str] = None
    expires_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Asset(BaseModel):
    """Провайдеронезависимая модель медиа-файла (без inline base64 в истории)."""
    id: str                                   # ast_xxx
    kind: Literal["image", "audio", "video", "document"]
    storage_uri: str                          # URI в AssetStore (file://, s3://, mem://)
    mime_type: str
    size_bytes: int = 0
    sha256: str
    status: Literal["pending", "materialized", "uploaded", "expired", "failed"] = "materialized"
    representations: dict[str, AssetRepresentation] = Field(default_factory=dict)
    cloud_refs: dict[str, CloudRef] = Field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════
# 2. ЧАСТИ СООБЩЕНИЙ (MESSAGE PARTS)
# ══════════════════════════════════════════════════════════════════

class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str
    cache_control: Optional[Literal["ephemeral"]] = None  # Маркер для Prompt Caching


class ReasoningPart(BaseModel):
    type: Literal["reasoning"] = "reasoning"
    text: str = ""
    signature: Optional[str] = None           # Криптографическая подпись (напр. Gemini thought_signature)
    provider_id: Optional[str] = None


class AssetPart(BaseModel):
    type: Literal["asset"] = "asset"
    asset: Asset


class StructuredDataPart(BaseModel):
    """Типизированный JSON-ответ при использовании Structured Outputs (response_schema)."""
    type: Literal["structured_data"] = "structured_data"
    schema_name: str
    data: dict[str, Any]


class ToolCallPart(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    call_id: str                              # call_xxx
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    provider_extensions: dict[str, Any] = Field(default_factory=dict)  # Изолированные метаданные провайдера


class ToolResultPart(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    call_id: str
    name: str
    text: str
    error: Optional[FrameworkError] = None
    assets: list[Asset] = Field(default_factory=list)


class UnknownPart(BaseModel):
    """Защитный контейнер для прямой совместимости при загрузке более новых версий схемы (I9)."""
    type: Literal["unknown"] = "unknown"
    original_type: str
    raw_payload: dict[str, Any]


MessagePart = Annotated[
    TextPart
    | ReasoningPart
    | AssetPart
    | StructuredDataPart
    | ToolCallPart
    | ToolResultPart
    | UnknownPart,
    Field(discriminator="type"),
]


# ══════════════════════════════════════════════════════════════════
# 3. СООБЩЕНИЯ, АУДИТОРСКИЕ СОБЫТИЯ И СТАТИСТИКА
# ══════════════════════════════════════════════════════════════════

class UsageStats(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0              # Поддержка Context Caching
    total_tokens: int = 0


class GenerationMetadata(BaseModel):
    execution_identity: ModelExecutionIdentity
    usage: Optional[UsageStats] = None
    finish_reason: Optional[FinishReason] = None
    latency_ms: Optional[int] = None
    provider_extensions: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    """Каноническое сообщение диалога (УФС 2.0)."""
    id: str                                   # msg_xxx
    timestamp: datetime
    role: Literal["system", "user", "assistant", "tool"]
    parts: list[MessagePart] = Field(default_factory=list)
    metadata: Optional[GenerationMetadata] = None


class Event(BaseModel):
    """Аудиторское/техническое событие (хранится отдельно от messages)."""
    id: str                                   # evt_xxx
    timestamp: datetime
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


# ══════════════════════════════════════════════════════════════════
# 4. СОСТОЯНИЕ ХОДА (TURN STATE) И КОРНЕВОЙ КОНТЕЙНЕР (CHAT DATA)
# ══════════════════════════════════════════════════════════════════

class PendingToolCall(BaseModel):
    call_id: str
    turn_id: str
    execution_identity: ModelExecutionIdentity
    assistant_message_id: str
    name: str
    args_hash: str
    status: Literal["pending", "executing", "completed", "failed", "cancelled", "denied"]
    result_message_id: Optional[str] = None


class TurnState(BaseModel):
    turn_id: str                              # trn_xxx
    execution_identity: ModelExecutionIdentity
    status: Literal[
        "generating", "awaiting_tool_results", "awaiting_model", "committing",
        "completed", "failed", "cancelled"
    ]
    pending_tool_calls: list[PendingToolCall] = Field(default_factory=list)
    started_at: datetime


class CompressionCheckpoint(BaseModel):
    checkpoint_id: str                        # cmp_xxx
    created_at: datetime
    compressed_range_start: str
    compressed_range_end: str
    compressed_messages: list[Message]
    original_message_count: int
    original_token_count: int
    compressed_token_count: int
    strategy: Literal["truncate_old_tools", "llm_summary", "hybrid", "sliding_window"]
    compression_params: dict[str, Any] = Field(default_factory=dict)


class ChatMetadata(BaseModel):
    schema_version: Literal["2.0"] = "2.0"
    conversation_id: str
    created_at: datetime
    active_model_identity: Optional[ModelExecutionIdentity] = None
    compression_checkpoints: list[CompressionCheckpoint] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class ChatData(BaseModel):
    """Полный сериализуемый снимок состояния сессии."""
    metadata: ChatMetadata
    messages: list[Message] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    active_turn: Optional[TurnState] = None
```

---

### 7.4. Управление сессией (`ChatSession` — Aggregate Root)

```python
@dataclass
class CommitResult:
    success: bool
    new_version: int = 0
    committed_ids: list[str] = field(default_factory=list)
    was_duplicate: bool = False
    error: Optional[FrameworkError] = None


class ChatSession:
    """
    Aggregate Root для управления историей диалога и состоянием активного хода.
    Гарантирует:
    - Политику One Active Turn Per Session (TurnInProgressError).
    - Идемпотентный атомарный commit (по turn_id + expected_version + _message_ids).
    - Pre-commit валидацию инвариантов I1–I6 через HistoryInvariantValidator.
    - Защиту от смены модели во время незавершённого хода (ModelSwitchMidTurnError).
    """

    _NON_TERMINAL_STATUSES = frozenset({
        "generating", "awaiting_tool_results", "awaiting_model", "committing"
    })

    def __init__(
        self,
        conversation_id: str,
        *,
        initial_identity: Optional[ModelExecutionIdentity] = None,
        id_factory: Optional[IdFactory] = None,
        validator: Optional[HistoryInvariantValidator] = None,
        max_cached_turns: int = 100,
    ):
        self._id_factory = id_factory or IdFactory()
        self._validator = validator or HistoryInvariantValidator()
        self._data = ChatData(
            metadata=ChatMetadata(
                conversation_id=conversation_id,
                created_at=datetime.now(timezone.utc),
                active_model_identity=initial_identity,
            ),
        )
        self._version = 0
        self._turn_lock = asyncio.Lock()
        self._message_ids: set[str] = set()
        self._committed_turns: OrderedDict[str, CommitResult] = OrderedDict()
        self._max_cached_turns = max_cached_turns

    @property
    def id_factory(self) -> IdFactory:
        return self._id_factory

    @property
    def version(self) -> int:
        return self._version

    @property
    def messages(self) -> tuple[Message, ...]:
        return tuple(self._data.messages)

    @property
    def events(self) -> tuple[Event, ...]:
        return tuple(self._data.events)

    @property
    def active_model_identity(self) -> Optional[ModelExecutionIdentity]:
        return self._data.metadata.active_model_identity

    def snapshot(self) -> ChatData:
        """Возвращает глубокую копию состояния для read-only проекции и персистентности."""
        return self._data.model_copy(deep=True)

    def timeline(self) -> list[Message | Event]:
        """Объединённый хронологический поток сообщений и событий для UI."""
        combined: list[tuple[datetime, str, Message | Event]] = [
            *((m.timestamp, m.id, m) for m in self._data.messages),
            *((e.timestamp, e.id, e) for e in self._data.events),
        ]
        combined.sort(key=lambda x: (x[0], x[1]))
        return [item for _, _, item in combined]

    async def begin_turn(self, turn_id: str, identity: ModelExecutionIdentity) -> TurnState:
        async with self._turn_lock:
            if (
                self._data.active_turn is not None
                and self._data.active_turn.status in self._NON_TERMINAL_STATUSES
            ):
                raise TurnInProgressError(f"Turn {self._data.active_turn.turn_id} is already active")

            state = TurnState(
                turn_id=turn_id,
                execution_identity=identity,
                status="generating",
                started_at=datetime.now(timezone.utc),
            )
            self._data.active_turn = state
            return state.model_copy(deep=True)

    async def append_turn(
        self,
        delta: list[Message],
        expected_version: Optional[int] = None,
        turn_id: Optional[str] = None,
    ) -> CommitResult:
        async with self._turn_lock:
            if turn_id is not None and turn_id in self._committed_turns:
                cached = self._committed_turns[turn_id]
                return CommitResult(
                    success=True,
                    new_version=cached.new_version,
                    committed_ids=list(cached.committed_ids),
                    was_duplicate=True,
                )

            if expected_version is not None and self._version != expected_version:
                return CommitResult(
                    success=False,
                    error=FrameworkError(
                        code="VERSION_CONFLICT",
                        category="concurrency_error",
                        retryable=True,
                        user_message="История диалога была изменена параллельной операцией.",
                        diagnostic_context={"expected": expected_version, "actual": self._version},
                    ),
                )

            for msg in delta:
                if msg.id in self._message_ids:
                    return CommitResult(
                        success=False,
                        error=FrameworkError(
                            code="DUPLICATE_MESSAGE_ID",
                            category="validation_error",
                            user_message="Обнаружен дубликат идентификатора сообщения.",
                            diagnostic_context={"message_id": msg.id},
                        ),
                    )

            validation = self._validator.validate_delta(
                current_messages=self._data.messages,
                delta=delta,
                active_identity=self._data.metadata.active_model_identity,
            )
            if not validation.valid:
                return CommitResult(
                    success=False,
                    error=FrameworkError(
                        code="UMF_INVARIANT_VIOLATION",
                        category="validation_error",
                        user_message="Нарушена целостность структуры сообщений диалога.",
                        diagnostic_context={"issues": [i.__dict__ for i in validation.issues]},
                    ),
                )

            self._data.messages.extend(delta)
            self._version += 1
            committed_ids = [m.id for m in delta]
            self._message_ids.update(committed_ids)

            res = CommitResult(
                success=True,
                new_version=self._version,
                committed_ids=committed_ids,
                was_duplicate=False,
            )
            if turn_id is not None:
                self._committed_turns[turn_id] = res
                if len(self._committed_turns) > self._max_cached_turns:
                    self._committed_turns.popitem(last=False)
            return res

    async def switch_model(
        self,
        new_identity: ModelExecutionIdentity,
        reason_code: SwitchReasonCode = "user_request",
        reason_detail: Optional[str] = None,
    ) -> str:
        async with self._turn_lock:
            if (
                self._data.active_turn is not None
                and self._data.active_turn.status in self._NON_TERMINAL_STATUSES
            ):
                raise ModelSwitchMidTurnError(
                    f"Cannot switch model while turn {self._data.active_turn.turn_id} is active"
                )

            old_identity = self._data.metadata.active_model_identity
            if old_identity == new_identity:
                last_evt = next(
                    (e for e in reversed(self._data.events) if e.type == "model_switch"), None
                )
                return last_evt.id if last_evt else ""

            self._data.metadata.active_model_identity = new_identity
            now = datetime.now(timezone.utc)
            evt = Event(
                id=self._id_factory.generate(IdFactory.PREFIX_EVENT, now),
                timestamp=now,
                type="model_switch",
                payload={
                    "from_identity": old_identity.model_dump() if old_identity else None,
                    "to_identity": new_identity.model_dump(),
                    "reason_code": reason_code,
                    "reason_detail": reason_detail,
                },
            )
            self._data.events.append(evt)
            return evt.id
```

---

## 💾 8. Уровень 7: Персистентность, эволюция схем, наблюдаемость и контрактное тестирование

### 8.1. Граница персистентности (`HistoryStore`) и политика восстановления (Recovery)

Хранение состояния отделено от `ChatSession` через порт `HistoryStore`, поддерживающий атомарную запись версионированных JSON-снимков и раздельное хранение аудиторского лога:

```python
class HistoryStore(Protocol):
    """Порт сохранения и восстановления сессий."""
    async def save_snapshot(self, data: ChatData, version: int) -> None:
        """Атомарно сохраняет снимок сессии (например, через write-temp + rename или транзакцию БД)."""
        ...

    async def load_snapshot(
        self,
        conversation_id: str,
        include_events: bool = True,
    ) -> tuple[ChatData, int]:
        """Загружает снимок, прогоняет через SchemaMigrator и HistoryInvariantValidator."""
        ...
```

#### Политика восстановления прерванного хода (Crash Recovery):
Если процесс завершился аварийно и из `HistoryStore` загружен `ChatData`, в котором `active_turn is not None`:
1. Фреймворк **не пытается** эвристически продолжить прерванный сетевой стрим или угадать статус внешних вызовов инструментов.
2. При инициализации `ChatSession.from_snapshot()` вызывается `recover_interrupted_turn()`, который переводит зависший `active_turn` в терминальный статус `failed`, помечает незавершённые `PendingToolCall` как `failed (reason="process_interrupted")`, записывает аудиторский `Event(type="error", payload={"recovery": "interrupted_turn_closed"})` и очищает `active_turn`, разблокируя сессию для дальнейшей работы.

---

### 8.2. Эволюция схем (`SchemaMigrator`)

Для долгоживущих сессий запрещено использование `pickle`. Сериализация выполняется строго в канонический JSON:
- **Цепочка миграций (`SchemaMigrator`):** при чтении JSON с более старой `schema_version` (например, `"1.0"` $\rightarrow$ `"2.0"`) применяется последовательная цепочка чистых функций-миграторов до валидации Pydantic-моделями.
- **Прямая совместимость (Forward Compatibility):** кастомный валидатор `MessagePart` перехватывает неизвестные значения дискриминатора `type` и упаковывает их в `UnknownPart(original_type=..., raw_payload=...)`.

---

### 8.3. Наблюдаемость (`TelemetryPort`) и защита секретов (`Redactor`)

Каждый шаг конвейера пробрасывает сквозной контекст корреляции (`CorrelationContext`: `conversation_id`, `turn_id`, `call_id`, `asset_id`):

```python
class Redactor:
    """Санитизация чувствительных данных перед записью в логи, события и HistoryStore."""
    SENSITIVE_KEYS = {"api_key", "authorization", "token", "secret", "password", "signed_url"}

    @classmethod
    def redact_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Рекурсивно маскирует значения секретных ключей и удаляет локальные пути ОС из строк."""
        ...
```

#### Собираемые метрики (`TelemetryPort`):
- Латентность (`TTFT` — Time To First Token и полная длительность) и число ретраев в разрезе `(provider_id, model_name, api_surface)`.
- Расход токенов (`input`, `output`, `reasoning`, `cached_input`).
- Длительность и статус каждого вызова инструмента в `ToolExecutor`.
- Статистика `ContextPreprocessor`: размер сжатия по `CompressionCheckpoint`, количество срабатываний мультимодального фоллбэка и отброшенных `provider_extensions`.

---

### 8.4. Матрица контрактного тестирования (Definition of Done для слоёв)

Ни один компонент фреймворка не считается готовым без прохождения своего уровня автоматических тестов:

| Уровень тестирования | Проверяемые компоненты | Обязательные сценарии и инварианты |
| :--- | :--- | :--- |
| **1. Property-Based & Unit (Без I/O)** | `IdFactory`, `HistoryInvariantValidator`, `PromptCompiler`, `ResponseParser`, `SchemaCompiler`, `ToolCallValidator`, `OutputNormalizer` | • Round-trip сериализация `ChatData` без потери типов и с сохранением `UnknownPart`.<br>• Идемпотентность `OutputNormalizer` на произвольных вложенных типах (`datetime`, `Decimal`, `BaseModel`).<br>• Отклонение битых инвариантов I1–I6 валидатором. |
| **2. Provider Contract Suite (Записанные фикстуры)** | Все реализации `ChatGenerationPort`, `StreamingChatPort`, `EmbeddingPort`, `ClassificationPort` | • Обычный текст, мультимодальный ответ, `StructuredDataPart`, `ReasoningPart` с `signature`.<br>• Пакетный вызов инструментов и сборка фрагментированных JSON-аргументов из стрима.<br>• Трансляция HTTP `400`, `401`, `429`, `500`, `503` и сетевых тайм-аутов в канонический `FrameworkError`. |
| **3. State & Concurrency Tests** | `ChatSession`, `Runner`, `ToolExecutor` (с фейковыми портами и искусственными задержками) | • Гарантия `TurnInProgressError` при параллельном запуске двух `runner.run()` на одной сессии.<br>• Гарантия `ModelSwitchMidTurnError` во всех нетерминальных фазах `TurnState`.<br>• Сохранение строгого порядка `ToolExecutionOutcome` в `execute_batch()` при случайном времени работы тулов.<br>• Гарантия отсутствия мутации `ChatSession.messages` при обрыве стрима (`aclose()`) или отмене через `CancellationToken`. |