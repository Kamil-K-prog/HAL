from __future__ import annotations

import asyncio
import threading

import pytest

from hal.core.cancellation import CancellationToken
from hal.core.errors import HalCancellationError


class TestCancellationTokenBasics:
    """Контракты базового состояния и метода raise_if_cancelled()."""

    def test_initial_state(self) -> None:
        token = CancellationToken()
        assert token.is_cancelled is False
        assert token.reason is None

    def test_raise_if_cancelled_when_active(self) -> None:
        token = CancellationToken()
        # Не должно выбрасывать исключение на активном токене
        token.raise_if_cancelled()

    def test_cancel_without_arguments(self) -> None:
        token = CancellationToken()
        res = token.cancel()

        assert res is True
        assert token.is_cancelled is True
        assert token.reason is None

        with pytest.raises(HalCancellationError) as exc_info:
            token.raise_if_cancelled()

        err = exc_info.value
        assert err.code == "OPERATION_CANCELLED"
        assert err.user_message == "The operation was cancelled by the user."

    def test_cancel_with_custom_reason(self) -> None:
        token = CancellationToken()
        res = token.cancel("User timeout")

        assert res is True
        assert token.is_cancelled is True
        assert token.reason == "User timeout"

        with pytest.raises(HalCancellationError) as exc_info:
            token.raise_if_cancelled()

        err = exc_info.value
        assert err.code == "OPERATION_CANCELLED"
        assert err.user_message == "User timeout"


class TestCancellationIdempotency:
    """Идемпотентность метода cancel()."""

    def test_cancel_is_idempotent(self) -> None:
        token = CancellationToken()

        first_res = token.cancel("First reason")
        assert first_res is True
        assert token.reason == "First reason"

        # Повторные вызовы должны возвращать False, а reason не должен перезаписываться
        second_res = token.cancel("Second reason")
        assert second_res is False
        assert token.reason == "First reason"

        third_res = token.cancel()
        assert third_res is False
        assert token.reason == "First reason"


class TestCancellationCallbacks:
    """Подписки on_cancel() и отписка unsubscribe()."""

    def test_callbacks_called_once_on_first_cancel(self) -> None:
        token = CancellationToken()
        calls_1: list[str] = []
        calls_2: list[str] = []

        token.on_cancel(lambda: calls_1.append("cb1"))
        token.on_cancel(lambda: calls_2.append("cb2"))

        token.cancel("Stop")
        assert calls_1 == ["cb1"]
        assert calls_2 == ["cb2"]

        # Повторный cancel не должен вызывать коллбэки снова
        token.cancel("Stop again")
        assert calls_1 == ["cb1"]
        assert calls_2 == ["cb2"]

    def test_on_cancel_on_already_cancelled_token(self) -> None:
        token = CancellationToken()
        token.cancel("Already cancelled")

        calls: list[str] = []
        unsubscribe = token.on_cancel(lambda: calls.append("ran immediately"))

        # Выполняется немедленно синхронно
        assert calls == ["ran"] or calls == ["ran immediately"]
        assert callable(unsubscribe)
        # Отписка безопасна и не вызывает ошибок
        unsubscribe()

    def test_unsubscribe_before_cancel(self) -> None:
        token = CancellationToken()
        calls: list[str] = []

        unsubscribe = token.on_cancel(lambda: calls.append("should not run"))
        unsubscribe()

        token.cancel("Stop")
        assert calls == []

    def test_multiple_unsubscribe_calls_are_safe(self) -> None:
        token = CancellationToken()
        unsubscribe = token.on_cancel(lambda: None)

        # Многократный вызов не должен бросать ValueError
        unsubscribe()
        unsubscribe()
        unsubscribe()

    def test_callback_error_isolation(self) -> None:
        token = CancellationToken()
        executed: list[str] = []

        def failing_cb1() -> None:
            executed.append("cb1")
            raise RuntimeError("Failure 1")

        def normal_cb2() -> None:
            executed.append("cb2")

        def failing_cb3() -> None:
            executed.append("cb3")
            raise ValueError("Failure 3")

        token.on_cancel(failing_cb1)
        token.on_cancel(normal_cb2)
        token.on_cancel(failing_cb3)

        with pytest.raises(ExceptionGroup) as exc_info:
            token.cancel("Error test")

        # Все коллбэки обязаны были выполниться, несмотря на ошибки в 1 и 3
        assert executed == ["cb1", "cb2", "cb3"]

        exceptions = exc_info.value.exceptions
        assert len(exceptions) == 2
        assert any(isinstance(e, RuntimeError) for e in exceptions)
        assert any(isinstance(e, ValueError) for e in exceptions)


class TestCancellationHierarchy:
    """Иерархия токенов create_child()."""

    def test_parent_cancellation_cancels_children(self) -> None:
        parent = CancellationToken()
        child1 = parent.create_child()
        child2 = parent.create_child()

        assert child1.is_cancelled is False
        assert child2.is_cancelled is False

        parent.cancel("Parent cancelled")

        assert child1.is_cancelled is True
        assert child1.reason == "Parent cancelled"
        assert child2.is_cancelled is True
        assert child2.reason == "Parent cancelled"

    def test_child_cancellation_does_not_affect_parent_or_siblings(self) -> None:
        parent = CancellationToken()
        child1 = parent.create_child()
        child2 = parent.create_child()

        child1.cancel("Child 1 cancelled")

        assert child1.is_cancelled is True
        assert child1.reason == "Child 1 cancelled"

        assert parent.is_cancelled is False
        assert parent.reason is None

        assert child2.is_cancelled is False
        assert child2.reason is None

    def test_create_child_on_already_cancelled_parent(self) -> None:
        parent = CancellationToken()
        parent.cancel("Parent was already cancelled")

        child = parent.create_child()

        assert child.is_cancelled is True
        assert child.reason == "Parent was already cancelled"

    def test_no_subscription_leak_when_child_cancelled(self) -> None:
        parent = CancellationToken()
        child = parent.create_child()

        # У родителя зарегистрирован коллбэк для отмены потомка
        assert len(parent._callbacks) == 1

        # Отменяем потомка напрямую
        child.cancel("Child cancelled directly")

        # Потомок должен отписаться от родителя, чтобы не висеть в памяти
        assert len(parent._callbacks) == 0

    def test_multilevel_hierarchy_cancellation(self) -> None:
        root = CancellationToken()
        child = root.create_child()
        grandchild = child.create_child()

        root.cancel("Root abort")

        assert child.is_cancelled is True
        assert child.reason == "Root abort"
        assert grandchild.is_cancelled is True
        assert grandchild.reason == "Root abort"


class TestAsyncCancellation:
    """Асинхронное ожидание await token.wait() и межпоточная безопасность."""

    def test_token_instantiation_without_event_loop(self) -> None:
        # Синхронный тест вне running loop
        token = CancellationToken()
        assert token.is_cancelled is False
        unsub = token.on_cancel(lambda: None)
        unsub()
        assert token.cancel("sync cancel") is True

    async def test_wait_wakes_up_on_cancel(self) -> None:
        token = CancellationToken()

        task = asyncio.create_task(token.wait())
        await asyncio.sleep(0.01)  # Даем корутине встать на паузу в wait()

        token.cancel("async stop")
        result = await asyncio.wait_for(task, timeout=1.0)

        assert result == "async stop"

    async def test_wait_on_already_cancelled_token(self) -> None:
        token = CancellationToken()
        token.cancel("immediate reason")

        # Должен вернуться немедленно без зависания
        result = await asyncio.wait_for(token.wait(), timeout=0.5)
        assert result == "immediate reason"

    async def test_threadsafe_cancellation(self) -> None:
        token = CancellationToken()

        wait_task = asyncio.create_task(token.wait())
        await asyncio.sleep(0.01)

        def thread_target() -> None:
            token.cancel("from thread")

        thread = threading.Thread(target=thread_target)
        thread.start()
        thread.join()

        result = await asyncio.wait_for(wait_task, timeout=1.0)
        assert result == "from thread"

    async def test_wait_cancelled_task_cleans_up_waiters(self) -> None:
        token = CancellationToken()

        task = asyncio.create_task(token.wait())
        await asyncio.sleep(0.01)

        # В списке ожидания должен быть 1 элемент
        assert len(token._waiters) == 1

        # Отменяем саму задачу стандартным task.cancel()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        # Убеждаемся, что waiter удален из списка и нет утечки памяти
        assert len(token._waiters) == 0
