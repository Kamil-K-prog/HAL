
<p align="center">
  <img src=".github/assets/banner.jpg" alt="HAL Banner" width="100%">
</p>

> *«I'm sorry, Dave. I'm afraid I can't do that.»* 

**HAL** — это единый асинхронный Python-фреймворк для работы с разнородными ИИ-провайдерами и моделями. 

Он создавался, чтобы избавить код от жёсткой привязки к конкретным SDK (`openai`, `google-genai`, `anthropic` и др.) и свести всё взаимодействие с нейросетями к одному чистому, предсказуемому интерфейсу.

---

## ✨ Что умеет HAL?

* **Единый формат диалога (UMF):** история сообщений, файлы и вызовы функций хранятся в универсальном формате, не зависящем от капризов конкретного API.
* **Смена моделей на лету:** можно начать диалог с мультимодальной моделью (например, разобрать картинку или PDF через Gemini), а на следующем шаге переключиться на чисто текстовый ризонер (DeepSeek или OpenAI) без потери контекста.
* **Надёжный ReAct и инструменты:** превращайте обычные Python-функции в инструменты для моделей одним декоратором — со строгой валидацией аргументов, контролем лимитов и поддержкой подтверждения действий человеком (Human-in-the-Loop).
* **Мультимодальность из коробки:** автоматическая работа с картинками, аудио, видео и документами (кэширование, загрузка в облачные Files API провайдеров и фоллбэк в текст для моделей, которые «не умеют смотреть»).
* **Больше чем просто LLM:** единое ядро поддерживает не только чат-модели, но и генераторы эмбеддингов (для RAG), специализированные классификаторы (вроде Jev) и модели генерации медиа.

---

## 🚀 Установка и разработка

Проект использует пакетный менеджер **[uv](https://docs.astral.sh/uv/)**:

```bash
# Установка базового ядра и всех провайдеров для разработки
uv sync --all-extras

# Запуск тестов
uv run pytest

# Проверка типов и линтера
uv run mypy
uv run ruff check .
```

---

## 💻 Быстрый пример

```python
import asyncio
from hal import ChatSession, ModelAdapter, Runner, ToolsRegistry

registry = ToolsRegistry()

@registry.register()
def open_pod_bay_doors(pod_id: int) -> str:
    """Открывает шлюз указанной капсулы."""
    return f"Шлюз капсулы #{pod_id} успешно открыт."

async def main() -> None:
    # 1. Инициализируем сессию и адаптер модели
    session = ChatSession(conversation_id="discovery_one")
    gemini = ModelAdapter.create("gemini-2.5-flash")
    runner = Runner(adapter=gemini, tools=registry)

    # 2. Запускаем шаг диалога с поддержкой инструментов
    await session.add_user_message("HAL, открой шлюз капсулы номер 1.")
    await runner.run(session)

    # 3. Переключаемся на другую модель и другого провайдера прямо посреди диалога[^1]
    deepseek = ModelAdapter.create("deepseek-chat")
    await session.switch_model(deepseek.identity)

    await session.add_user_message("Отлично, а теперь рассчитай траекторию до Юпитера.")
    await runner.run(session, adapter=deepseek)

if __name__ == "__main__":
    asyncio.run(main())
```