import asyncio

from redis.asyncio import Redis
import json

from configs import REDIS_PORT, REDIS_HOST
from payment_system_api import PaymentSystemAPI
from loggers import logger
from payment_system_cash_commands import payment_system_cash_commands


async def listen_to_redis(redis, api):
    """Подключение к Redis и обработка команд"""
    try:
        await api.init_devices()
    except Exception as e:
        logger.error(f"Critical error: {e}")
        await api.shutdown()
        return

    pubsub = redis.pubsub()

    # Подписка на канал команд
    channel = 'payment_system_cash_commands'
    channel_response = f'{channel}_response'
    await pubsub.subscribe(channel)
    logger.info("Ожидание команд...")

    # Слушаем канал и выполняем команды
    async for message in pubsub.listen():
        if message.get('type') == 'message':
            raw_data = message.get("data")

            # обработка пинга
            if raw_data == "ping":
                continue
            try:
                command = json.loads(raw_data)
                logger.info(f"Получена команда: {command}")

                response = await payment_system_cash_commands(command, api)

                await redis.publish(channel_response, json.dumps(response))
                logger.info(f"[{channel}] Ответ отправлен в {channel_response}: {response}")
            except json.JSONDecodeError as e:
                logger.error(f"Ошибка парсинга команды: {e}")
            except Exception as e:
                logger.error(f"Неожиданная ошибка: {e}")


async def pre_settings(redis: Redis):
    max_bill_count = await redis.get('max_bill_count')
    bill_count = await redis.get('bill_count')
    if max_bill_count is None:
        max_bill_count = 1450
        await redis.set('max_bill_count', max_bill_count)
    if bill_count is None:
        bill_count = 0
        await redis.set('bill_count', bill_count)

    upper_box_count = await redis.get('bill_dispenser:upper_count')
    lower_box_count = await redis.get('bill_dispenser:lower_count')
    if upper_box_count is None:
        upper_box_count = 0
        await redis.set('bill_dispenser:upper_count', upper_box_count)
    if lower_box_count is None:
        lower_box_count = 0
        await redis.set('bill_dispenser:lower_count', lower_box_count)

    upper_lvl = await redis.get('bill_dispenser:upper_lvl')
    lower_lvl = await redis.get('bill_dispenser:lower_lvl')
    if upper_lvl is None:
        await redis.set('bill_dispenser:upper_lvl', 10000)
    if lower_lvl is None:
        await redis.set('bill_dispenser:lower_lvl', 5000)

    available_devices_cash = await redis.smembers("available_devices_cash")
    if not available_devices_cash:
        await redis.sadd(
            "available_devices_cash",
            'bill_acceptor',
            'bill_dispenser',
            'coin_dispenser',
            'coin_acceptor',
        )


async def main():
    redis = Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    payment_api = PaymentSystemAPI(redis)

    # Сначала применяем настройки
    await pre_settings(redis)

    # Потом запускаем слушатель команд
    await listen_to_redis(redis, payment_api)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановка приложения...")
