### Группа 1. Ошибки одновременного доступа (`category = "concurrency_error"`)
*Защищают историю чата от поломок, когда два процесса пытаются менять её одновременно.*

#### 1. `TurnInProgressError`
* **Код:** `"TURN_IN_PROGRESS"` | **Retryable:** `False`
* **User message:** `"Can't run turns in parallel! You must wait for turn to finish."`
* **Когда срабатывает:** Когда в одной сессии (`ChatSession`) уже запущен запрос к нейросети, и кто-то пытается запустить второй запрос параллельно, не дождавшись ответа первого.

#### 2. `InvalidTurnStateError`
* **Код:** `"INVALID_TURN_STATE"` | **Retryable:** `False`
* **User message:** `"Error occurred while mutating turn state."`*
* **Когда срабатывает:** Когда `Runner` пытается обновить статус хода или закрыть его, но передаёт неправильный `turn_id` (или пытается закрыть ход, который ещё не закончился). Это защита от внутренних багов.

#### 3. `ModelSwitchMidTurnError`
* **Код:** `"MODEL_SWITCH_MID_TURN"` | **Retryable:** `False`
* **User message:** `"I'm sorry, Dave. I'm afraid I can't do that.\nCan't switch model mid-turn, wait for it to finish."`
* **Когда срабатывает:** Когда пользователь вызывает `session.switch_model()`, пока нейросеть ещё генерирует ответ или выполняет инструменты (цикл ReAct не закончен).

#### 4. `VersionConflictError`
* **Код:** `"HISTORY_VERSION_CONFLICT"` | **Retryable:** `True`
* **User message:** `"You are working with old version of history. Changes are not committed."`*
* **Когда срабатывает:** Когда `Runner` начал работать с историей версии №5, но пока он думал, кто-то другой успел добавить в сессию новое сообщение (и версия стала №6). При попытке сохранить результат сработает эта ошибка, чтобы не затереть чужие данные.

---

### Группа 2. Ошибки проверки данных и настроек (`category = "validation_error"`)
*Срабатывают, когда в систему передали неправильные данные или настройки.*

#### 5. `DuplicateMessageError`
* **Код:** `"DUPLICATE_MESSAGE_ID"` | **Retryable:** `False`
* **User message:** `"Message with this ID already exists in the session history."`
* **Когда срабатывает:** В `session.append_turn()`, если мы случайно пытаемся сохранить новое сообщение с `id`, который уже есть в истории этой сессии.

#### 6. `HistoryValidationError`
* **Код:** `"UMF_INVARIANT_VIOLATION"` | **Retryable:** `False`
* **User message:** `"Conversation history is corrupted or violates format rules."`
* **Когда срабатывает:** Когда валидатор (`HistoryInvariantValidator`) находит поломку в структуре сообщений. Например: модель попросила вызвать инструмент (`ToolCallPart`), а ответа от инструмента (`ToolResultPart`) в истории нет.
* **Особенность:** Ему можно сделать простой `__init__` (как у тебя в `VersionConflictError`), который принимает необязательный параметр `issues: list[Any] | None = None` и кладёт его в `context["issues"] = issues`.

#### 7. `ContextPreparationError`
* **Код:** `"CONTEXT_PREPARATION_FAILED"` | **Retryable:** `False`
* **User message:** `"Failed to prepare conversation history for the selected model."`
* **Когда срабатывает:** В `ContextPreprocessor`, когда перед отправкой запроса не получилось подстроить историю под требования конкретной модели (например, история слишком огромная и даже сжатие не помогло влезть в лимит токенов).

#### 8. `ConfigurationError`
* **Код:** `"INVALID_CONFIGURATION"` | **Retryable:** `False`
* **User message:** `"Framework configuration is invalid or missing required settings."`
* **Когда срабатывает:** Когда пользователь забыл указать нужную настройку. Например: не задан API-ключ в переменных окружения, или включён режим «описывать картинки текстом» (`DESCRIBE`), но сама модель для описания картинок не подключена.

---

### Группа 3. Ограничения моделей и работа с файлами
*Связаны с тем, что умеет или не умеет конкретная нейросеть, и с хранением медиа-файлов.*

#### 9. `UnsupportedCapabilityError`
* **Категория:** `"capability_error"`
* **Код:** `"UNSUPPORTED_CAPABILITY"` | **Retryable:** `False`
* **User message:** `"The selected model does not support this feature."`
* **Когда срабатывает:** Когда от модели просят то, чего она не умеет по своему паспорту (`ModelProfile`). Например: просят сгенерировать картинку через текстовую модель DeepSeek или вызывают инструменты у модели, которая их не поддерживает.

#### 10. `UnsupportedMediaError`
* **Категория:** `"capability_error"`
* **Код:** `"UNSUPPORTED_MEDIA_TYPE"` | **Retryable:** `False`
* **User message:** `"The selected model does not support this file or media type."`
* **Когда срабатывает:** Когда пользователь прикрепил к сообщению аудио, видео или PDF, выбранная модель их не понимает, а в настройках стоит строгий режим `MediaFallbackPolicy.ERROR` (падать с ошибкой вместо замены на текст).

#### 11. `AssetStorageError`
* **Категория:** `"asset_storage_error"`
* **Код:** `"ASSET_STORAGE_FAILED"` | **Retryable:** `True`
* **User message:** `"Failed to read, save, or upload media file."`
* **Когда срабатывает:** В `AssetManager` или `AssetStore`, когда не удалось сохранить картинку на диск, файл оказался удалён, или не получилось загрузить большой файл в облако Google / OpenAI.

---

### Группа 4. Инструменты и безопасность
*Срабатывают во время проверки и запуска Python-функций (тулов).*

#### 12. `ToolExecutionError`
* **Категория:** `"tool_execution_error"`
* **Код:** `"TOOL_EXECUTION_FAILED"` | **Retryable:** `False`
* **User message:** `"Tool execution failed due to an internal error in the tool function."`
* **Когда срабатывает:** В `ToolExecutor`, когда сама написанная пользователем Python-функция упала с ошибкой во время работы (например, попыталась поделить на ноль или не смогла открыть файл).

#### 13. `PolicyDeniedError`
* **Категория:** `"policy_denied"`
* **Код:** `"POLICY_DENIED"` | **Retryable:** `False`
* **User message:** `"Action was denied by security policy or rejected by user."`
* **Когда срабатывает:** В двух случаях:
  1. Нейросеть попыталась вызвать запрещённый инструмент (которого нет в списке разрешённых `RunPolicy.allowed_tools`).
  2. Сработал режим подтверждения человеком (Human-in-the-Loop), и пользователь нажал кнопку «Запретить вызов функции».

---

### Группа 5. Сеть, провайдеры, тайм-ауты и отмена
*Ошибки общения с внешним миром (серверами OpenAI, Google и т.д.).*

#### 14. `TransportError`
* **Категория:** `"transport_error"`
* **Код:** `"NETWORK_TRANSPORT_ERROR"` | **Retryable:** `True`
* **User message:** `"Network connection failed while communicating with the AI provider."`
* **Когда срабатывает:** Когда пропал интернет, не сработал DNS или оборвалось соединение с сервером до получения ответа. Помечена `retryable = True`, чтобы фреймворк сам попробовал подключиться ещё раз.

#### 15. `RateLimitError`
* **Категория:** `"rate_limit_error"`
* **Код:** `"PROVIDER_RATE_LIMIT"` | **Retryable:** `True`
* **User message:** `"Too many requests or quota exceeded for the AI provider. Please wait and try again."`
* **Когда срабатывает:** Когда сервер провайдера вернул код `HTTP 429` (слишком частые запросы в минуту или закончились деньги на балансе API).

#### 16. `ProviderResponseError`
* **Категория:** `"provider_response_error"`
* **Код:** `"PROVIDER_RESPONSE_ERROR"` | **Retryable:** `False` *(для ошибок 500/502/503 драйвер сам передаст `retryable=True` при вызове)*
* **User message:** `"The AI provider returned an unexpected error or invalid response."`
* **Когда срабатывает:** Когда сервер OpenAI или Google вернул ошибку `HTTP 400` (неправильный запрос), `HTTP 500` (упал сервер провайдера) или прислал битый JSON, который не получилось распарсить.

#### 17. `HalTimeoutError`
* **Категория:** `"timeout_error"`
* **Код:** `"OPERATION_TIMEOUT"` | **Retryable:** `True`
* **User message:** `"The operation took too long and timed out."`
* **Когда срабатывает:** Когда нейросеть слишком долго не отвечает, инструмент завис дольше своего `timeout_sec`, или весь цикл `Runner` превысил общее время `wall_clock_timeout_sec`. *(Называем `HalTimeoutError`, чтобы не путать со встроенным в Python `TimeoutError`).*

#### 18. `HalCancellationError`
* **Категория:** `"cancellation_error"`
* **Код:** `"OPERATION_CANCELLED"` | **Retryable:** `False`
* **User message:** `"The operation was cancelled by the user."`
* **Когда срабатывает:** Когда пользователь нажал кнопку «Стоп» (`CancellationToken.cancel()`) или закрыл стрим, не дождавшись конца ответа.
