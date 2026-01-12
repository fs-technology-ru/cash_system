"""
Example usage of the CCNET Bill Validator Driver.

This example demonstrates how to use the CashCodeDriver class
to communicate with a Creator C100-B20 bill validator.
"""

import asyncio
import logging
from ccnet import CashCodeDriver, EventType, StateContext

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)


async def on_bill_inserted(event_type: str, context: StateContext) -> None:
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


async def on_error(event_type: str, context: StateContext) -> None:
    """Callback when an error occurs."""
    from ccnet import get_state_name
    state_name = get_state_name(context.current_state)
    print(f"⚠️ Ошибка: {state_name}")


async def main():
    """Main entry point."""
    # Create driver instance
    driver = CashCodeDriver(
        port='/dev/ttyUSB0',  # Change to your serial port
        baudrate=9600,
        auto_stack=True,  # Automatically accept bills
    )
    
    # Register callbacks
    driver.add_callback(EventType.BILL_STACKED, on_bill_inserted)
    driver.add_callback(EventType.BILL_ESCROW, on_bill_escrow)
    driver.add_callback(EventType.BILL_REJECTED, on_bill_rejected)
    driver.add_callback(EventType.ERROR, on_error)
    
    print("Подключение к купюроприемнику...")
    
    # Connect to the device
    if not await driver.connect():
        print("Не удалось подключиться к устройству!")
        return
    
    print("✓ Подключено!")
    
    # Enable bill acceptance
    await driver.enable_validator()
    print("✓ Прием купюр включен. Ожидание купюр...")
    
    try:
        # Run forever (or until interrupted)
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        # Clean shutdown
        print("\nОстановка...")
        await driver.disconnect()
        print("✓ Отключено")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nПрервано пользователем")
