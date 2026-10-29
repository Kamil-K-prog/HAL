1. **Горизонтальный фундамент (Слой 0):** Реализация чистого доменного ядра (`core/`), не зависящего от сети и I/O.
2. **Ядро состояния (Слой 1):** Реализация `ChatSession` как Aggregate Root с проверкой инвариантов и конкурентности.
3. **Тонкий вертикальный срез (Steel Thread):** Минимальный сквозной путь через слои (Препроцессор $\rightarrow$ Адаптер $\rightarrow$ Оркестратор $\rightarrow$ Драйвер) до первого живого ответа модели в консоли.
4. **Второй вертикальный срез (ReAct + Tools):** Подключение реестра инструментов, валидатора вызовов, нормализатора вывода и исполнителя к ReAct-циклу.
5. **Наращивание горизонтальных возможностей:** Ассеты, сжатие контекста, персистентность, синхронный фасад, телеметрия и дополнительные драйверы.

Каждый шаг рассчитан на **преимущественно один** коммит с последующим написанием unit-тестов ИИ-агентом.

---

## 🟢 Этап 0: Стартовое состояние (Сделано)

- [x] **Шаг 0.1 (`src/hal/core/ids.py`):** Фабрика `IdFactory` на базе ULID (уникальность, таймстампы, префиксы).
- [x] **Шаг 0.2 (`src/hal/core/errors.py`):** `ErrorCategory`, `FrameworkError`, базовое исключение `HalError` с реестром подклассов и конвертацией в обе стороны.
- [x] **Шаг 0.3 (`src/hal/core/identity.py`):** `ModelExecutionIdentity`, хэширование конфигурации, `SwitchReasonCode`.

---

## 🟢 Этап 1: Горизонтальный фундамент (Слой 0 — `src/hal/core/`)

Закрываем все базовые типы данных, контракты и инварианты, которые импортируются остальными модулями.

- [x] **Шаг 1: `src/hal/core/cancellation.py`**
  - **Что внутри:** Класс `CancellationToken`.
  - **Логика:**
    - Потокобезопасность (`threading.Lock`): создание вне цикла событий, вызов `cancel()` из другого потока.
    - Идемпотентность `cancel(reason)` с сохранением первой причины.
    - Метод `raise_if_cancelled()` с выбросом `HalCancellationError`.
    - Подписка `on_cancel(callback)` с функцией отписки `unsubscribe()` и изоляцией ошибок.
    - Иерархия токенов: `create_child()` с двусторонней отпиской.
    - Асинхронное ожидание `await token.wait()`.
  - **Фокус тестов:** Потокобезопасность, краевые случаи отмены, иерархия родитель-потомок, отсутствие утечек памяти.

- [x] **Шаг 2: `src/hal/core/profiles.py`**
  - **Что внутри:** Декларативные модели спецификации моделей и провайдеров.
  - **Логика:**
    - `RetryPolicy` (максимум попыток, backoff, jitter, статус-коды, валидация `max_backoff_sec >= initial_backoff_sec`).
    - `ProviderConfig` (хостинг, имя env-переменной API-ключа без утечки секрета, таймауты).
    - `ModelCapabilities` (матрица задач, модальностей, поддержки тулов/стриминга/кэширования).
    - `ModelLimits` (токены контекста и вывода, inline-байты ассетов, mime-типы, проверка бюджета токенов).
    - `CompatibilityRules` (политики чередования ролей, `reasoning_policy` для прошлых ходов, `preserve_thoughts_in_react` для активного хода, `require_thought_signature_on_tools` и запрещённые параметры генерации).
    - `ModelProfile` (полный манифест модели, авто-вычисление `model_name`, загрузка/выгрузка YAML).
  - **Фокус тестов:** Дефолтные значения, валидация полей, сериализация и десериализация из JSON/YAML.

- [x] **Шаг 3: `src/hal/core/umf.py`**
  - **Что внутри:** Полная модель Универсального Формата Сообщений (УФС 2.0).
  - **Логика:**
    - Модели ассетов: `CloudRef`, `AssetRepresentation`, `Asset`.
    - Части сообщений (`MessagePart`): `TextPart`, `ReasoningPart`, `AssetPart`, `StructuredDataPart`, `ToolCallPart`, `ToolResultPart`.
    - Защитный контейнер `UnknownPart` и **Инвариант I9**: перехват неизвестных типов дискриминатора при парсинге JSON без падения.
    - Метаданные и контейнеры: `UsageStats`, `GenerationFinishReason`, `GenerationMetadata`, `Message`, `Event`.
    - Структуры ходов и компрессии: `PendingToolCall`, `TurnState`, `CompressionCheckpoint`, `ChatMetadata`, `ChatData`.
  - **Фокус тестов:** Round-trip сериализация `ChatData` $\rightarrow$ JSON $\rightarrow$ `ChatData`, проверка полиморфизма частей сообщений, валидатор неизвестных частей.

- [ ] **Шаг 4: `src/hal/core/invariants.py`**
  - **Что внутри:** `InvariantCode`, `ValidationIssue`, `ValidationResult`, `HistoryInvariantValidator`.
  - **Логика:**
    - `validate_history(messages, active_identity)`: проверка списка сообщений (`I1`, `I2`, `I3 + I5`, `I6`).
    - `validate_delta(current_messages, delta, active_identity)`: проверка дельты перед коммитом в `ChatSession`.
    - `validate_snapshot(data: ChatData)`: полная проверка снимка сессии (`messages`, `events`, `compression_checkpoints`, `active_turn`).
    - Проверка **I1** (уникальность ID, префиксы `msg_`, `call_`, `ast_`, `evt_`, `cmp_`, `trn_` и формат ULID через `IdFactory.validate`).
    - Проверка **I2** (чистота ролей: `system` — только текст, `tool` — только результаты и т.д., с допуском `UnknownPart` по I9).
    - Проверка **I3 + I5** (пары вызов-результат тулов: соответствие `call_id` и детерминированный порядок).
  - **Фокус тестов:** Спектр позитивных и негативных сценариев с преднамеренным нарушением каждого инварианта.

- [ ] **Шаг 5: `src/hal/core/ports.py`**
  - **Что внутри:** Абстрактные интерфейсы (`typing.Protocol`) и их базовые DTO.
  - **Логика:**
    - DTO: `PreparedContext`, `CompatibilityIssue`, `RawGenerationResult`, `DriverStreamChunk`.
    - Сетевые протоколы: `ChatGenerationPort`, `StreamingChatPort`, `EmbeddingPort`, `ClassificationPort`, `MediaGenerationPort`.
    - Инфраструктурные протоколы: `AssetStore`, `CloudStorageDriver`, `HistoryStore`, `TokenizerPort`, `ApprovalPort`, `TelemetryPort`.
  - **Фокус тестов:** Проверка контрактов через `@runtime_checkable`, создание фиктивных (mock) реализаций.

---

## 🔵 Этап 2: Ядро состояния (Слой 1 — `src/hal/session/`)

- [ ] **Шаг 6: `src/hal/session/chat_session.py`**
  - **Что внутри:** `ChatSession` (Aggregate Root) и `CommitResult`.
  - **Логика:**
    - Управление блокировкой активного хода через `TurnState` (гарантия «один активный ход на сессию», `TurnInProgressError`).
    - Атомарный идемпотентный метод `append_turn()` с проверкой `turn_id`, версионированием (`expected_version`) и вызовом `HistoryInvariantValidator`.
    - Защита от смены модели посреди хода (`ModelSwitchMidTurnError` в `switch_model()`).
    - Методы `snapshot()`, `timeline()`, `close_turn()`.
    - Crash Recovery: метод `ChatSession.from_snapshot()`, закрывающий незавершённый ход с записью события ошибки.
  - **Фокус тестов:** Конкурентный запуск ходов, оптимистичная блокировка, идемпотентность дельт, восстановление после сбоя.

---

## ⚡ Этап 3: Тонкий вертикальный срез («Первая искра» — текстовый диалог)

Пробиваем минимальный сквозной контур исполнения без сложного медиа-процессинга и вызова инструментов.

- [ ] **Шаг 7: Базовый `ContextPreprocessor` (`src/hal/context/normalizer.py` + `preprocessor.py`)**
  - **Что внутри:** Фасад подготовки контекста.
  - **Логика:**
    - `ReasoningAndExtensionStrategy`: удаление чужих `signature` при несовпадении `provider_id`.
    - Базовый `RoleSequenceNormalizer`: выравнивание чередования ролей.
    - Фасад `ContextPreprocessor.prepare(chat_data, profile) -> PreparedContext`: валидация через `HistoryInvariantValidator`, запуск нормализаторов. Сжатие и медиа-фоллбэк пока опциональны.
  - **Фокус тестов:** Проверка неизменяемости исходного `ChatData`, удаление провайдер-специфичных полей при смене модели.

- [ ] **Шаг 8: Диалоговый фасад (`src/hal/adapters/chat.py`)**
  - **Что внутри:** `ModelAdapter` и `GenerationResult`.
  - **Логика:**
    - Одиночный сетевой шаг: `generate()` и `stream()`.
    - Предварительная проверка возможностей: выброс `UnsupportedCapabilityError`, если модель не поддерживает стриминг или запрошенный формат.
    - Трансляция `RawGenerationResult` от драйвера в канонический `Message(role="assistant")` с метаданными `GenerationMetadata`.
  - **Фокус тестов:** Тестирование адаптера с фейковым драйвером (`FakeChatDriver`), проверка выброса ошибок возможностей, сборка сообщений.

- [ ] **Шаг 9: События и политики ReAct (`src/hal/runner/policy.py` + `events.py`)**
  - **Что внутри:** Правила запуска и канонические стриминговые события.
  - **Логика:**
    - `RunPolicy` (лимиты итераций, вызовов тулов, таймауты) и `TurnFinishReason` (причина завершения хода).
    - Иерархия `RunnerEvent` (`ContentDeltaEvent`, `ThinkingDeltaEvent`, `ToolEvent`, `StepCompletedEvent`, `RunCompletedEvent`, `RunErrorEvent`, `RunCancelledEvent`).
    - Монотонная нумерация `sequence_no` внутри хода.
  - **Фокус тестов:** Сериализация событий, валидация Discriminated Union по полю `type`.

- [ ] **Шаг 10: Оркестратор ReAct (`src/hal/runner/runner.py` — Версия 1: Text-Only)**
  - **Что внутри:** Класс `Runner` (базовый текстовый цикл).
  - **Логика:**
    - Жизненный цикл: `begin_turn()` $\rightarrow$ `ContextPreprocessor` $\rightarrow$ `ModelAdapter` $\rightarrow$ `append_turn()` $\rightarrow$ `close_turn()`.
    - Стриминг через `stream()` со статусом `commit_status="tentative"`.
    - Гарантированный Rollback: блок `try ... finally` в генераторе гарантирует закрытие хода со статусом `cancelled` при разрыве (`aclose()`) без мутации `session.messages`.
  - **Фокус тестов:** Сквозной цикл с `ChatSession` и фейковым драйвером, откат незакоммиченного буфера при отмене.

- [ ] **Шаг 11: Первый реальный драйвер + Пример запуска (🎉 Первый живой запуск)**
  - **Что внутри:**
    - Драйвер одного провайдера: `src/hal/drivers/openai/chat_driver.py` или `src/hal/drivers/google/genai_driver.py`.
    - Реализация портов `ChatGenerationPort` и `StreamingChatPort`.
    - Маппинг ошибок SDK провайдера в канонические `HalError` (`RateLimitError`, `TransportError` и др.).
    - Профиль модели в `src/hal/builtin_profiles/`.
    - Рабочий пример `examples/hello_hal.py`.
  - **Фокус тестов:** Контрактные тесты драйвера на сохранённых JSON-фикстурах, маппинг HTTP-ошибок.

---

## 🛠️ Этап 4: Второй вертикальный срез (Инструменты и полный ReAct)

Превращаем текстовый цикл в полноценного агента.

- [ ] **Шаг 12: Модели инструментов и реестр (`src/hal/tools/models.py` + `registry.py`)**
  - **Что внутри:** `Tool`, `ToolPolicy`, `ToolOutput`, `ToolExecutionOutcome`, `ApprovalDecision` и `ToolsRegistry`.
  - **Логика:**
    - Инспекция сигнатур функций и docstring Python с автоматической генерацией JSON Schema.
    - Изолированный реестр тулов без глобального состояния.
  - **Фокус тестов:** Генерация корректных схем для примитивных типов, `Pydantic`-моделей, списков, опциональных аргументов.

- [ ] **Шаг 13: Валидация вызовов и нормализация вывода (`src/hal/tools/validator.py` + `normalizer.py`)**
  - **Что внутри:** Пре-валидатор `ToolCallValidator` и сериализатор вывода `OutputNormalizer`.
  - **Логика:**
    - Валидация имени тула, JSON-аргументов и политик доступа до запуска кода функции.
    - `CanonicalJsonEncoder`: корректная сериализация `datetime`, `UUID`, `Decimal`, `BaseModel`.
    - Обрезка вывода по лимиту `ToolPolicy.max_output_bytes` с добавлением маркера усечения.
  - **Фокус тестов:** Отлов галлюцинаций аргументов модели, форматирование нестандартных типов, усечение переполненного вывода.

- [ ] **Шаг 14: Исполнитель инструментов (`src/hal/tools/executor.py`)**
  - **Что внутри:** `ToolExecutor`.
  - **Логика:**
    - Выполнение одиночных вызовов и пакетов (`execute_batch`).
    - Ограничение параллелизма через `asyncio.Semaphore`.
    - Гарантия сохранения исходного порядка результатов при параллельном выполнении.
    - Интеграция с портом подтверждения действий человека (`ApprovalPort` / HITL).
    - Безопасное исполнение синхронных функций через `asyncio.to_thread`.
  - **Фокус тестов:** Соблюдение порядка в `execute_batch`, срабатывание таймаута тула, отказ через `ApprovalDecision(action="deny")`.

- [ ] **Шаг 15: Полноценный ReAct в `Runner` и компиляторы схем**
  - **Что внутри:** Интеграция подсистемы инструментов в оркестратор и драйвер.
  - **Логика:**
    - Компилятор JSON Schema под целевой провайдер (OpenAI strict tools или Gemini tools).
    - Мультишаговый ReAct-цикл в `Runner`: модель $\rightarrow$ парсинг тулов $\rightarrow$ `ToolExecutor` $\rightarrow$ отправка результатов обратно $\rightarrow$ финальный ответ.
    - Контроль лимитов шагов (`RunPolicy.max_iterations`, `max_total_tool_calls`).
  - **Фокус тестов:** Сквозной тест ReAct с фиктивным тулом (калькулятор/погода): проверка многошагового цикла и фиксации пар вызов-результат в истории.

---

## 🧱 Этап 5: Наращивание горизонтальных возможностей

Модули расширения функциональности, которые можно реализовывать в удобном порядке.

### Персистентность сессий
- [ ] **Шаг 16: Хранилища истории (`src/hal/session/store.py`)**
  - `InMemoryHistoryStore` и атомарный `JsonFileHistoryStore` (запись во временный файл + rename).
- [ ] **Шаг 17: Эволюция схем (`src/hal/session/migrator.py`)**
  - `SchemaMigrator`: цепочки миграций истории между версиями схемы (например, 1.0 $\rightarrow$ 2.0).

### Ассеты и мультимодальность
- [ ] **Шаг 18: Хранилища бинарных данных (`src/hal/assets/stores.py`)**
  - `InMemoryAssetStore` и `LocalDiskAssetStore`.
- [ ] **Шаг 19: Менеджер ассетов (`src/hal/assets/manager.py`)**
  - `AssetManager`: координация сохранения байт, вычисление SHA-256, проверка лимитов размера.
- [ ] **Шаг 20: Мультимодальный фоллбэк (`src/hal/context/fallback.py`)**
  - `MediaFallbackStrategy`: обработка неподдерживаемых ассетов по политикам `ERROR`, `PLACEHOLDER`, `DESCRIBE`.

### Контекст и токенизация
- [ ] **Шаг 21: Контроль бюджета и сжатие (`src/hal/context/budgeter.py`)**
  - `ContextBudgeter`: оценка токенов, отсечение старых результатов тулов (`truncate_old_tools`), виртуальная проекция по `CompressionCheckpoint`.

### Синхронный фасад и наблюдаемость
- [ ] **Шаг 22: Синхронный раннер (`src/hal/runner/sync.py`)**
  - `BackgroundLoopPortal` и `SyncRunner` для безопасного использования из синхронного кода без конфликтов с Event Loop.
- [ ] **Шаг 23: Безопасность и телеметрия (`src/hal/telemetry/redactor.py` + `logger.py`)**
  - `Redactor`: маскирование секретов, API-ключей и абсолютных путей ОС в логах и метаданных.
  - Реализация `TelemetryPort` для сбора метрик задержки, токенов и ошибок.

### Специализированные адаптеры и драйверы
- [ ] **Шаг 24: Эмбеддинги (`src/hal/adapters/embedding.py`)**
  - `EmbeddingAdapter` и интеграция с драйвером OpenAI.
- [ ] **Шаг 25: Драйвер Google GenAI (`src/hal/drivers/google/`)**
  - Поддержка Gemini 2.5/3, мыслей (`ReasoningPart`) и Google Files API.
- [ ] **Шаг 26: Классификатор Jev (`src/hal/adapters/classifier.py` + `drivers/jev/`)**
  - Адаптер классификации и драйвер для Jev.