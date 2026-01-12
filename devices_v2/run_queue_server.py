"""
Redis queue server for the cash payment system.

This module provides the main entry point for the cash system service,
handling Redis pub/sub communication and command processing.
"""

import asyncio
import json
from typing import Any, Final

from redis.asyncio import Redis

from configs import REDIS_PORT, REDIS_HOST
from loggers import logger
from payment_system_api import PaymentSystemAPI
from payment_system_cash_commands import payment_system_cash_commands


# =============================================================================
# Constants
# =============================================================================

COMMAND_CHANNEL: Final[str] = "payment_system_cash_commands"
RESPONSE_CHANNEL: Final[str] = f"{COMMAND_CHANNEL}_response"

# Default Redis settings
DEFAULT_SETTINGS: Final[dict[str, dict[str, Any]]] = {
    "max_bill_count": {"key": "max_bill_count", "default": 1450},
    "bill_count": {"key": "bill_count", "default": 0},
    "upper_count": {"key": "bill_dispenser:upper_count", "default": 0},
    "lower_count": {"key": "bill_dispenser:lower_count", "default": 0},
    "upper_lvl": {"key": "bill_dispenser:upper_lvl", "default": 10000},
    "lower_lvl": {"key": "bill_dispenser:lower_lvl", "default": 5000},
}

AVAILABLE_DEVICES: Final[set[str]] = {
    "bill_acceptor",
    "bill_dispenser",
    "coin_dispenser",
    "coin_acceptor",
}


# =============================================================================
# Redis Command Listener
# =============================================================================

async def listen_to_redis(redis: Redis, api: PaymentSystemAPI) -> None:
    """
    Listen for commands on Redis pub/sub and process them.

    Args:
        redis: Redis client instance.
        api: PaymentSystemAPI instance for command execution.
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
    redis = Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True,
    )

    payment_api = PaymentSystemAPI(redis)

    # Initialize default settings
    await initialize_redis_settings(redis)

    # Start command listener
    await listen_to_redis(redis, payment_api)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
