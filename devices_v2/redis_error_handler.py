"""
Redis error handling utilities.

This module provides decorators and utilities for handling Redis-related
errors in async functions, providing consistent error responses.
"""

from functools import wraps
from typing import Any, Callable, TypeVar

from loggers import logger


# Type variable for generic function typing
F = TypeVar("F", bound=Callable[..., Any])


class RedisOperationResult:
    """
    Standardized result for Redis operations.

    Attributes:
        success: Whether the operation succeeded.
        message: Human-readable message about the operation.
        data: Optional additional data from the operation.
    """

    def __init__(
        self,
        success: bool,
        message: str,
        data: Any = None,
    ) -> None:
        self.success = success
        self.message = message
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        """Convert the result to a dictionary."""
        result = {
            "success": self.success,
            "message": self.message,
        }
        if self.data is not None:
            result["data"] = self.data
        return result


def redis_error_handler(success_message: str) -> Callable[[F], F]:
    """
    Decorator for handling Redis errors and providing unified responses.

    This decorator wraps async functions that perform Redis operations,
    catching connection and timeout errors and returning standardized
    response dictionaries.

    Args:
        success_message: The message to return on successful operation.

    Returns:
        Decorated function with error handling.

    Example:
        @redis_error_handler("Data saved successfully")
        async def save_data(self, key: str, value: str):
            await self.redis.set(key, value)
    """
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                result = await func(*args, **kwargs)
                # If the function returns something, include it in the response
                if result is not None:
                    return {
                        "success": True,
                        "message": success_message,
                        "data": result,
                    }
                return {
                    "success": True,
                    "message": success_message,
                }
            except ConnectionError as e:
                logger.error(f"Redis connection error: {e}")
                return {
                    "success": False,
                    "message": f"Redis connection error: {e}",
                }
            except TimeoutError as e:
                logger.error(f"Redis timeout error: {e}")
                return {
                    "success": False,
                    "message": f"Redis timeout error: {e}",
                }
            except Exception as e:
                logger.error(f"Unexpected error in Redis operation: {e}")
                return {
                    "success": False,
                    "message": f"Unexpected error: {e}",
                }
        return wrapper  # type: ignore
    return decorator
