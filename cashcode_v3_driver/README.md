# CashCode Bill Validator Driver v3

Асинхронный Python-драйвер для купюроприемников CashCode (CCNET протокол).

## Описание

Этот драйвер обеспечивает асинхронное взаимодействие с купюроприемниками, совместимыми с протоколом CCNET (CashCode NET), включая Creator C100-B20 и другие модели.

## Установка

### 1. Установка зависимостей

```bash
cd cashcode_v3_driver
pip install -r requirements.txt
```

### 2. Настройка прав доступа к последовательному порту

Для Linux необходимо настроить права доступа к устройству:

```bash
# Временно (до перезагрузки)
sudo chmod 666 /dev/ttyUSB0

# Постоянно (добавление пользователя в группу dialout)
sudo usermod -a -G dialout $USER
# После этого необходимо перезайти в систему
```

## Использование

### Запуск демонстрационного скрипта

```bash
python main.py --port /dev/ttyUSB0 --baudrate 9600
```

### Использование в коде

```python
import asyncio
from ccnet import CashCodeDriver, EventType, StateContext

async def on_bill_stacked(event_type: str, context: StateContext) -> None:
    """Колбэк при принятии купюры."""
    amount_rub = context.bill_amount / 100
    print(f"Принята купюра: {amount_rub:.2f} RUB")

async def on_bill_escrow(event_type: str, context: StateContext) -> None:
    """Колбэк при попадании купюры в эскроу."""
    amount_rub = context.bill_amount / 100
    print(f"Купюра в эскроу: {amount_rub:.2f} RUB")

async def main():
    # Создание экземпляра драйвера
    driver = CashCodeDriver(
        port='/dev/ttyUSB0',
        baudrate=9600,
        auto_stack=True,  # Автоматическое принятие купюр
    )
    
    # Регистрация колбэков
    driver.add_callback(EventType.BILL_STACKED, on_bill_stacked)
    driver.add_callback(EventType.BILL_ESCROW, on_bill_escrow)
    
    # Подключение к устройству
    if not await driver.connect():
        print("Не удалось подключиться!")
        return
    
    # Включение приема купюр
    await driver.enable_validator()
    
    try:
        # Работа в цикле
        await asyncio.Future()  # Бесконечное ожидание
    finally:
        await driver.disconnect()

asyncio.run(main())
```

## Архитектура

Драйвер состоит из нескольких слоев:

```
┌─────────────────────────────────────────┐
│             CashCodeDriver              │  <- Прикладной уровень
│         (ccnet/driver.py)               │
├─────────────────────────────────────────┤
│        BillValidatorStateMachine        │  <- Машина состояний
│       (ccnet/state_machine.py)          │
├─────────────────────────────────────────┤
│           CCNETProtocol                 │  <- Протокольный уровень
│         (ccnet/protocol.py)             │
├─────────────────────────────────────────┤
│          CCNETTransport                 │  <- Транспортный уровень
│        (ccnet/transport.py)             │
├─────────────────────────────────────────┤
│        CRC16 / Constants                │  <- Базовые компоненты
│   (ccnet/crc.py, ccnet/constants.py)    │
└─────────────────────────────────────────┘
```

### Компоненты

- **CashCodeDriver** - основной класс драйвера, предоставляющий высокоуровневый API
- **BillValidatorStateMachine** - машина состояний для отслеживания переходов
- **CCNETProtocol** - реализация протокола CCNET (команды, ACK/NAK)
- **CCNETTransport** - транспортный уровень (фрейминг пакетов, CRC)
- **CRC16** - вычисление контрольной суммы CRC16 CCITT (полином 0x08408)

## Список событий (Events)

| Событие | Описание |
|---------|----------|
| `CONNECTED` | Драйвер подключился к устройству |
| `DISCONNECTED` | Драйвер отключился от устройства |
| `BILL_ESCROW` | Купюра в позиции эскроу (ожидает решения) |
| `BILL_STACKED` | Купюра принята и сохранена в стекере |
| `BILL_RETURNED` | Купюра возвращена пользователю |
| `BILL_REJECTED` | Купюра отклонена |
| `STATE_CHANGED` | Изменилось состояние устройства |
| `ERROR` | Произошла ошибка |
| `CASSETTE_FULL` | Кассета заполнена |
| `CASSETTE_REMOVED` | Кассета извлечена |

## Поддерживаемые номиналы

Для Creator C100-B20 (Российские рубли):

| Код | Номинал | Значение (копейки) |
|-----|---------|-------------------|
| 0x02 | 10 RUB | 1000 |
| 0x03 | 50 RUB | 5000 |
| 0x04 | 100 RUB | 10000 |
| 0x05 | 500 RUB | 50000 |
| 0x06 | 1000 RUB | 100000 |
| 0x07 | 5000 RUB | 500000 |
| 0x0C | 200 RUB | 20000 |
| 0x0D | 2000 RUB | 200000 |

## Методы драйвера

### Основные методы

| Метод | Описание |
|-------|----------|
| `connect()` | Подключение к устройству |
| `disconnect()` | Отключение от устройства |
| `enable_validator()` | Включение приема купюр |
| `disable_validator()` | Отключение приема купюр |
| `reset()` | Сброс устройства |

### Управление купюрами

| Метод | Описание |
|-------|----------|
| `stack_bill()` | Принять купюру из эскроу |
| `return_bill()` | Вернуть купюру из эскроу |

### Информация об устройстве

| Метод | Описание |
|-------|----------|
| `get_status()` | Получить статус устройства |
| `get_identification()` | Получить идентификацию устройства |

### Колбэки

| Метод | Описание |
|-------|----------|
| `add_callback(event_type, callback)` | Добавить колбэк на событие |
| `remove_callback(event_type, callback)` | Удалить колбэк |

## Свойства драйвера

| Свойство | Тип | Описание |
|----------|-----|----------|
| `port` | str | Путь к последовательному порту |
| `baudrate` | int | Скорость порта |
| `is_connected` | bool | Статус подключения |
| `is_accepting` | bool | Статус приема купюр |
| `current_state` | int | Текущее состояние устройства |
| `current_state_name` | str | Название текущего состояния |

## Контекстный менеджер

Драйвер поддерживает использование как асинхронный контекстный менеджер:

```python
async with CashCodeDriver(port='/dev/ttyUSB0') as driver:
    await driver.enable_validator()
    # Работа с устройством
    await asyncio.sleep(60)
# Автоматическое отключение
```

## Требования

- Python 3.10+
- pyserial >= 3.5
- pyserial-asyncio >= 0.6

## Лицензия

MIT License
