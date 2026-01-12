import asyncio
from asyncio.exceptions import TimeoutError
import json

from redis.asyncio import Redis


async def pubsub_command_util(redis: Redis, channel: str, command: dict):
    """Функция создает подписчика и слушателя Redis."""
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"{channel}_response")

    await redis.publish(channel, json.dumps(command))

    try:
        response_data = await wait_for_response(pubsub)
        return {"code": 200, "detail": "Ответ получен", "data": response_data}
    except TimeoutError:
        return print("Таймаут ожидания ответа от устройства")
    finally:
        await pubsub.unsubscribe(f"{channel}_response")
        await pubsub.close()


async def wait_for_response(pubsub, timeout: int = 15):
    """Ожидание ответа из Redis Pub/Sub с указанным command_id."""
    async def _listener():
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    return data
                except Exception:
                    continue
    return await asyncio.wait_for(_listener(), timeout=timeout)

if __name__ == '__main__':
    redis = Redis(host='localhost', port=6379, decode_responses=True)

    start_accepting_payment = {
        "command": "start_accepting_payment",
        "data": {"amount": 500},
        "command_id": 1,
    }

    stop_accepting_payment = {
        "command": "stop_accepting_payment",
        "command_id": 1,
    }

    test_dispense_change = {
        "command": "test_dispense_change",
        "command_id": 1,
    }

    set_bill_dispenser_lvl = {
        "command": "set_bill_dispenser_lvl",
        "data": {"upper_lvl": 100, "lower_lvl": 50},
        "command_id": 1,
    }

    bill_acceptor_set_max_bill_count = {
        "command": "bill_acceptor_set_max_bill_count",
        "data": {"value": 1400},
        "command_id": 1,
    }

    bill_acceptor_reset_bill_count = {
        "command": "bill_acceptor_reset_bill_count",
        "command_id": 1,
    }

    bill_acceptor_status = {
        "command": "bill_acceptor_status",
        "command_id": 1,
    }

    init_devices = {
        "command": "init_devices",
        "command_id": 1,
    }

    bill_dispenser_status = {
        "command": "bill_dispenser_status",
        "command_id": 1,
    }

    set_bill_dispenser_count = {
        "command": "set_bill_dispenser_count",
        "command_id": 1,
        "data": {"upper_count": 100, "lower_count": 100}
    }

    channel = 'payment_system_cash_commands'
    asyncio.run(pubsub_command_util(redis, channel, set_bill_dispenser_lvl))
