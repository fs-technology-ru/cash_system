import asyncio
from enum import Enum
from typing import Callable, Dict, List, Union


class EventType(str, Enum):
    BILL_ACCEPTED = "bill_accepted"
    COIN_CREDIT = 'COIN_CREDIT'
    OPEN = 'OPEN'
    CLOSE = 'CLOSE'
    ERROR = 'ERROR'
    DISPENSED = 'DISPENSED'
    INCOMPLETE_PAYOUT = 'INCOMPLETE_PAYOUT'
    EMPTIED = 'EMPTIED'


class EventPublisher:
    def __init__(self, event_queue: asyncio.Queue):
        self.event_queue = event_queue

    async def publish(self, event_type: Union[EventType, str], **data):
        """Publish an event to the queue."""
        event = {"type": event_type, **data}
        await self.event_queue.put(event)

class EventConsumer:
    def __init__(self, event_queue: asyncio.Queue):
        self.event_queue = event_queue
        self.handlers: Dict[Union[EventType, str], List[Callable]] = {}
        self.is_consuming = False
        self.consume_task = None

    def register_handler(self, event_type: Union[EventType, str], handler: Callable):
        """Register a handler for an event type."""
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        self.handlers[event_type].append(handler)

    async def _consume_one(self):
        """Consume a single event and schedule the next consumption."""
        if not self.is_consuming:
            return

        try:
            event = await self.event_queue.get()
            event_type = event.get("type")

            if event_type in self.handlers:
                # Process all handlers with functional approach
                handlers = self.handlers[event_type]
                async_handlers = [h for h in handlers if asyncio.iscoroutinefunction(h)]
                sync_handlers = [h for h in handlers if not asyncio.iscoroutinefunction(h)]

                # Execute async handlers concurrently
                if async_handlers:
                    await asyncio.gather(*[handler(event) for handler in async_handlers])

                # Execute sync handlers
                [handler(event) for handler in sync_handlers]

            self.event_queue.task_done()

            # Schedule next consumption recursively
            if self.is_consuming:
                self.consume_task = asyncio.create_task(self._consume_one())

        except asyncio.CancelledError:
            pass

    async def start_consuming(self):
        """Start consuming events."""
        if self.is_consuming:
            return

        self.is_consuming = True
        self.consume_task = asyncio.create_task(self._consume_one())

    async def stop_consuming(self):
        """Stop consuming events."""
        self.is_consuming = False
        if self.consume_task:
            self.consume_task.cancel()
            try:
                await self.consume_task
            except asyncio.CancelledError:
                pass
