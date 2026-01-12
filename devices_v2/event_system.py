"""
Event system for the cash system.

This module provides a publish-subscribe event system for handling
device events like bill acceptance, coin credit, and state changes.
"""

import asyncio
from enum import Enum
from typing import Callable, Any, Union


class EventType(str, Enum):
    """
    Enumeration of event types in the cash system.

    These events are published when device state changes occur.
    """

    BILL_ACCEPTED = "bill_accepted"
    COIN_CREDIT = "coin_credit"
    OPEN = "open"
    CLOSE = "close"


class EventPublisher:
    """
    Publisher for sending events to the event queue.

    Provides a simple interface for publishing events with associated data.

    Attributes:
        event_queue: The asyncio queue to publish events to.
    """

    def __init__(self, event_queue: asyncio.Queue) -> None:
        """
        Initialize the event publisher.

        Args:
            event_queue: The asyncio queue for event distribution.
        """
        self.event_queue = event_queue

    async def publish(self, event_type: Union[EventType, str], **data: Any) -> None:
        """
        Publish an event to the queue.

        Args:
            event_type: The type of event to publish.
            **data: Additional event data as keyword arguments.
        """
        event = {"type": event_type, **data}
        await self.event_queue.put(event)


class EventConsumer:
    """
    Consumer for processing events from the event queue.

    Handles event dispatch to registered handlers based on event type.

    Attributes:
        event_queue: The asyncio queue to consume events from.
        handlers: Mapping of event types to their handler functions.
        is_consuming: Flag indicating if the consumer is active.
    """

    def __init__(self, event_queue: asyncio.Queue) -> None:
        """
        Initialize the event consumer.

        Args:
            event_queue: The asyncio queue to consume events from.
        """
        self.event_queue = event_queue
        self.handlers: dict[Union[EventType, str], list[Callable]] = {}
        self.is_consuming = False
        self._consume_task: asyncio.Task | None = None

    def register_handler(
        self,
        event_type: Union[EventType, str],
        handler: Callable,
    ) -> None:
        """
        Register a handler for an event type.

        Args:
            event_type: The event type to handle.
            handler: The handler function (sync or async).
        """
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        self.handlers[event_type].append(handler)

    def unregister_handler(
        self,
        event_type: Union[EventType, str],
        handler: Callable,
    ) -> None:
        """
        Unregister a handler for an event type.

        Args:
            event_type: The event type.
            handler: The handler function to remove.
        """
        if event_type in self.handlers:
            try:
                self.handlers[event_type].remove(handler)
            except ValueError:
                pass

    async def _process_event(self, event: dict[str, Any]) -> None:
        """
        Process a single event by calling all registered handlers.

        Args:
            event: The event dictionary containing type and data.
        """
        event_type = event.get("type")
        if event_type not in self.handlers:
            return

        handlers = self.handlers[event_type]

        # Separate async and sync handlers
        async_handlers = [h for h in handlers if asyncio.iscoroutinefunction(h)]
        sync_handlers = [h for h in handlers if not asyncio.iscoroutinefunction(h)]

        # Execute async handlers concurrently
        if async_handlers:
            await asyncio.gather(
                *(handler(event) for handler in async_handlers),
                return_exceptions=True,
            )

        # Execute sync handlers
        for handler in sync_handlers:
            try:
                handler(event)
            except Exception:
                pass  # Handlers should handle their own exceptions

    async def _consume_loop(self) -> None:
        """
        Main consumption loop that processes events from the queue.
        """
        while self.is_consuming:
            try:
                # Use wait_for with timeout to allow checking is_consuming flag
                event = await asyncio.wait_for(
                    self.event_queue.get(),
                    timeout=0.5,
                )
                await self._process_event(event)
                self.event_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                pass  # Continue processing other events

    async def start_consuming(self) -> None:
        """
        Start the event consumption loop.

        This method starts processing events from the queue.
        """
        if self.is_consuming:
            return

        self.is_consuming = True
        self._consume_task = asyncio.create_task(self._consume_loop())

    async def stop_consuming(self) -> None:
        """
        Stop the event consumption loop.

        This method stops processing events and cancels the consumption task.
        """
        self.is_consuming = False

        if self._consume_task:
            self._consume_task.cancel()
            try:
                await self._consume_task
            except asyncio.CancelledError:
                pass
            self._consume_task = None
