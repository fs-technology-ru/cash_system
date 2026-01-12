#!/usr/bin/env python3
"""
CashCode Bill Validator Driver - Production Entry Point.

This script runs the CashCodeDriver for production use with a 
Creator C100-B20 or compatible bill validator.

Usage:
    python main.py [--port /dev/ttyUSB0] [--baudrate 9600] [--debug]

Features:
    - Automatic device initialization (RESET + wait for ready state)
    - Automatic bill acceptance with escrow handling
    - Automatic re-enabling after bill rejection
    - Graceful shutdown on Ctrl+C
    - Debug mode with HEX packet logging
"""

import asyncio
import argparse
import logging
import signal
import sys
from ccnet import CashCodeDriver, EventType, StateContext, get_state_name

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
    # Get rejection reason from raw_data if available
    reason_code = context.raw_data[0] if context.raw_data else None
    reason_str = f" (код: 0x{reason_code:02X})" if reason_code else ""
    print(f"❌ Купюра отклонена{reason_str}")


async def on_bill_returned(event_type: str, context: StateContext) -> None:
    """Callback when a bill is returned."""
    print("↩️ Купюра возвращена")


async def on_error(event_type: str, context: StateContext) -> None:
    """Callback when an error occurs."""
    state_name = get_state_name(context.current_state)
    print(f"⚠️ Ошибка: {state_name}")


async def on_state_changed(event_type: str, context: StateContext) -> None:
    """Callback when device state changes (debug mode only)."""
    prev_name = get_state_name(context.previous_state) if context.previous_state else "None"
    curr_name = get_state_name(context.current_state)
    logger.debug(f"State: {prev_name} -> {curr_name}")


async def main(port: str, baudrate: int, debug: bool) -> int:
    """
    Main entry point.
    
    Returns:
        Exit code (0 for success, 1 for error).
    """
    # Create driver instance
    driver = CashCodeDriver(
        port=port,
        baudrate=baudrate,
        auto_stack=True,  # Automatically accept bills
    )
    
    # Register callbacks
    driver.add_callback(EventType.BILL_STACKED, on_bill_stacked)
    driver.add_callback(EventType.BILL_ESCROW, on_bill_escrow)
    driver.add_callback(EventType.BILL_REJECTED, on_bill_rejected)
    driver.add_callback(EventType.BILL_RETURNED, on_bill_returned)
    driver.add_callback(EventType.ERROR, on_error)
    
    if debug:
        driver.add_callback(EventType.STATE_CHANGED, on_state_changed)
    
    print(f"Подключение к купюроприемнику ({port})...")
    
    # Connect to the device (includes RESET and wait for ready state)
    if not await driver.connect():
        print("❌ Не удалось подключиться к устройству!")
        return 1
    
    print("✓ Подключено!")
    
    # Enable bill acceptance
    if not await driver.enable_validator():
        print("❌ Не удалось включить прием купюр!")
        await driver.disconnect()
        return 1
    
    print("✓ Прием купюр включен. Ожидание купюр...")
    print("Нажмите Ctrl+C для выхода.\n")
    
    # Create a shutdown event
    shutdown_event = asyncio.Event()
    
    # Setup signal handlers for graceful shutdown
    def signal_handler():
        shutdown_event.set()
    
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass
    
    try:
        # Run forever (or until shutdown event is set)
        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        # Clean shutdown
        print("\nОстановка...")
        await driver.disconnect()
        print("✓ Отключено")
    
    return 0


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='CashCode Bill Validator Driver (Production)',
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
    parser.add_argument(
        '--debug', '-d',
        action='store_true',
        help='Enable debug logging (shows HEX dump of all TX/RX packets)',
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    
    # Configure logging level based on --debug flag
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        force=True,
    )
    
    try:
        exit_code = asyncio.run(main(args.port, args.baudrate, args.debug))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nПрервано пользователем")
        sys.exit(0)
