"""
Cash Payment System - Main entry point.

This module provides the main entry point for the cash system service,
using the new layered architecture while maintaining Redis pub/sub compatibility.
"""

import asyncio
import json
from typing import Any, Final

from redis.asyncio import Redis

from application.api_facade import PaymentSystemFacade
from application.command_handler import payment_system_cash_commands
from infrastructure.settings import get_settings, DEFAULT_SETTINGS, AVAILABLE_DEVICES
from loggers import logger


# =============================================================================
# Constants
# =============================================================================

settings = get_settings()
COMMAND_CHANNEL: Final[str] = settings.payment.command_channel
RESPONSE_CHANNEL: Final[str] = settings.payment.response_channel


# =============================================================================
# Redis Command Listener
# =============================================================================


async def listen_to_redis(redis: Redis, api: PaymentSystemFacade) -> None:
    """
    Listen for commands on Redis pub/sub and process them.

    Args:
        redis: Redis client instance.
        api: PaymentSystemFacade instance for command execution.
    """
    try:
        await api.init_devices()
    except Exception as e:
        logger.error(f"Critical error during device initialization: {e}")
        await api.shutdown()
        return

    pubsub = redis.pubsub()
    await pubsub.subscribe(COMMAND_CHANNEL)
    logger.info(f"Listening for commands on channel: {COMMAND_CHANNEL}")

    async for message in pubsub.listen():
        if message.get("type") != "message":
            continue

        raw_data = message.get("data")

        # Handle ping messages
        if raw_data == "ping":
            continue

        try:
            command = json.loads(raw_data)
            logger.info(f"Received command: {command}")

            response = await payment_system_cash_commands(command, api)

            await redis.publish(RESPONSE_CHANNEL, json.dumps(response))
            logger.info(f"Response sent to {RESPONSE_CHANNEL}: {response}")

        except json.JSONDecodeError as e:
            logger.error(f"Command parsing error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error processing command: {e}")


# =============================================================================
# Pre-initialization Settings
# =============================================================================


async def initialize_redis_settings(redis: Redis) -> None:
    """
    Initialize default Redis settings if they don't exist.

    Args:
        redis: Redis client instance.
    """
    for setting in DEFAULT_SETTINGS.values():
        key = setting["key"]
        default = setting["default"]

        current_value = await redis.get(key)
        if current_value is None:
            await redis.set(key, default)
            logger.debug(f"Initialized {key} = {default}")

    # Initialize available devices set
    available_devices = await redis.smembers("available_devices_cash")
    if not available_devices:
        await redis.sadd("available_devices_cash", *AVAILABLE_DEVICES)
        logger.debug(f"Initialized available_devices_cash: {AVAILABLE_DEVICES}")


# =============================================================================
# Main Entry Point
# =============================================================================


async def main() -> None:
    """
    Main entry point for the cash system service.

    Initializes Redis connection, applies default settings, and starts
    the command listener.
    """
    settings = get_settings()

    redis = Redis(
        host=settings.redis.host,
        port=settings.redis.port,
        decode_responses=settings.redis.decode_responses,
    )

    payment_api = PaymentSystemFacade(redis)

    # Initialize default settings
    await initialize_redis_settings(redis)

    # Start command listener
    await listen_to_redis(redis, payment_api)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
