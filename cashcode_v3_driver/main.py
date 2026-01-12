#!/usr/bin/env python3
"""
CashCode Bill Validator Driver - Entry Point.

This script demonstrates how to use the CashCodeDriver class
to communicate with a Creator C100-B20 or compatible bill validator.

Usage:
    python main.py [--port /dev/ttyUSB0] [--baudrate 9600]
"""

import asyncio
import argparse
import logging
import signal
from ccnet import CashCodeDriver, EventType, StateContext, get_state_name

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


async def on_bill_stacked(event_type: str, context: StateContext) -> None:
    """Callback when a bill is stacked (accepted)."""
    amount_rub = context.bill_amount / 100
    print(f"✅ Принята купюра: {amount_rub:.2f} RUB")


async def on_bill_escrow(event_type: str, context: StateContext) -> None:
    """Callback when a bill enters escrow position."""
    amount_rub = context.bill_amount / 100
    print(f"📥 Купюра в эскроу: {amount_rub:.2f} RUB")


async def on_bill_rejected(event_type: str, context: StateContext) -> None:
    """Callback when a bill is rejected."""
    print("❌ Купюра отклонена")


async def on_bill_returned(event_type: str, context: StateContext) -> None:
    """Callback when a bill is returned."""
    print("↩️ Купюра возвращена")


async def on_error(event_type: str, context: StateContext) -> None:
    """Callback when an error occurs."""
    state_name = get_state_name(context.current_state)
    print(f"⚠️ Ошибка: {state_name}")


async def on_connected(event_type: str, context: StateContext) -> None:
    """Callback when driver is connected."""
    print("🔗 Подключено к устройству")


async def on_disconnected(event_type: str, context: StateContext) -> None:
    """Callback when driver is disconnected."""
    print("🔌 Отключено от устройства")


async def main(port: str, baudrate: int) -> None:
    """Main entry point."""
    # Create driver instance
    driver = CashCodeDriver(
        port=port,
        baudrate=baudrate,
        auto_stack=True,  # Automatically accept bills
    )
    
    # Register callbacks
    driver.add_callback(EventType.CONNECTED, on_connected)
    driver.add_callback(EventType.DISCONNECTED, on_disconnected)
    driver.add_callback(EventType.BILL_STACKED, on_bill_stacked)
    driver.add_callback(EventType.BILL_ESCROW, on_bill_escrow)
    driver.add_callback(EventType.BILL_REJECTED, on_bill_rejected)
    driver.add_callback(EventType.BILL_RETURNED, on_bill_returned)
    driver.add_callback(EventType.ERROR, on_error)
    
    print(f"Подключение к купюроприемнику ({port})...")
    
    # Connect to the device
    if not await driver.connect():
        print("❌ Не удалось подключиться к устройству!")
        return
    
    print("✓ Подключено!")
    
    # Enable bill acceptance
    await driver.enable_validator()
    print("✓ Прием купюр включен. Ожидание купюр...")
    print("Нажмите Ctrl+C для выхода.\n")
    
    # Create a shutdown event
    shutdown_event = asyncio.Event()
    
    # Setup signal handlers for graceful shutdown
    def signal_handler():
        shutdown_event.set()
    
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        # Run forever (or until shutdown event is set)
        await shutdown_event.wait()
    finally:
        # Clean shutdown
        print("\nОстановка...")
        await driver.disconnect()
        print("✓ Отключено")


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='CashCode Bill Validator Driver',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '--port', '-p',
        type=str,
        default='/dev/ttyUSB0',
        help='Serial port path',
    )
    parser.add_argument(
        '--baudrate', '-b',
        type=int,
        default=9600,
        help='Serial baudrate',
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(main(args.port, args.baudrate))
    except KeyboardInterrupt:
        print("\nПрервано пользователем")
