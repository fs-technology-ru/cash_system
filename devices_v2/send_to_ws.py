"""
WebSocket client for sending events to the frontend.

This module provides utilities for sending real-time events
to connected WebSocket clients.
"""

import json
from typing import Any, Optional

import websockets
from websockets.exceptions import WebSocketException

from configs import WS_URL
from loggers import logger


async def send_to_ws(
    event: str,
    data: Optional[dict[str, Any]] = None,
    ws_url: str = WS_URL,
) -> bool:
    """
    Send an event to the WebSocket server.

    Args:
        event: The event name/type to send.
        data: Optional dictionary of event data.
        ws_url: WebSocket URL to connect to (default from config).

    Returns:
        True if the message was sent successfully, False otherwise.

    Example:
        await send_to_ws(
            event='acceptedBill',
            data={'bill_value': 10000, 'collected_amount': 10000},
        )
    """
    message = {"event": event, "data": data}

    try:
        async with websockets.connect(ws_url) as ws:
            await ws.send(json.dumps(message))
            logger.debug(f"WebSocket message sent: {event}")
            return True
    except WebSocketException as e:
        logger.warning(f"WebSocket connection error: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to send WebSocket message: {e}")
        return False
