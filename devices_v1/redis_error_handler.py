from functools import wraps

from loggers import logger


def redis_error_handler(success_message: str):
    """Декоратор для обработки ошибок Redis и унификации ответа"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                await func(*args, **kwargs)
                return {
                    'success': True,
                    'message': success_message,
                }
            except (ConnectionError, TimeoutError) as e:
                logger.error(f"Redis connection issue: {e}")
                return {
                    'success': False,
                    'message': f"Redis connection issue: {e}"
                }
        return wrapper
    return decorator
