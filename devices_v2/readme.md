# Cash Payment System (devices_v2)

A payment system for handling cash transactions using bill acceptors, bill dispensers, coin acceptors, and coin hoppers.

## Architecture

This system follows a layered architecture with clean separation of concerns:

```
devices_v2/
├── core/                    # Foundation layer (no external dependencies)
│   ├── exceptions.py        # Structured exception hierarchy
│   ├── interfaces.py        # Device protocols and interfaces
│   └── value_objects.py     # Immutable value objects (Money, PaymentResult)
│
├── infrastructure/          # External dependencies layer
│   ├── redis_repository.py  # Repository pattern for Redis operations
│   └── settings.py          # Centralized configuration
│
├── domain/                  # Business logic layer
│   ├── device_adapters.py   # Unified device interface adapters
│   ├── device_manager.py    # Device lifecycle management
│   └── payment_state_machine.py  # Payment flow state machine
│
├── application/             # Application services layer
│   ├── api_facade.py        # Facade preserving backward compatibility
│   ├── command_handler.py   # Redis command routing
│   ├── device_service.py    # Device operations service
│   └── payment_service.py   # Payment flow orchestration
│
├── devices/                 # Hardware device drivers
│   ├── bill_acceptor/       # CCNET bill acceptor drivers
│   ├── bill_dispenser/      # LCDM-2000 dispenser driver
│   ├── coin_acceptor/       # SSP hopper driver
│   └── cctalk_coin_acceptor.py  # ccTalk coin acceptor
│
├── main.py                  # Entry point (new architecture)
├── run_queue_server.py      # Entry point (legacy)
└── tests/                   # Unit tests
```

## Key Features

- **Layered Architecture**: Clear separation between core, infrastructure, domain, and application layers
- **Repository Pattern**: Type-safe Redis operations with domain-specific repositories
- **State Machine**: Clean payment flow management (IDLE → ACCEPTING → COMPLETING → COMPLETED)
- **Unified Device Interface**: Common interface for all payment devices
- **Value Objects**: Immutable objects for Money, PaymentResult, DispensingResult
- **Structured Exceptions**: Typed exception hierarchy for better error handling
- **Backward Compatible**: Preserves Redis pub/sub API for existing integrations

## Redis API

The system communicates via Redis pub/sub on channel `payment_system_cash_commands`.

### Available Commands

| Command | Arguments | Description |
|---------|-----------|-------------|
| `init_devices` | - | Initialize all payment devices |
| `start_accepting_payment` | `amount` (int) | Start accepting payment |
| `stop_accepting_payment` | - | Stop current payment |
| `dispense_change` | `amount` (int) | Dispense change |
| `bill_acceptor_status` | - | Get bill acceptor status |
| `bill_acceptor_set_max_bill_count` | `value` (int) | Set max bill capacity |
| `bill_acceptor_reset_bill_count` | - | Reset bill count |
| `bill_dispenser_status` | - | Get dispenser status |
| `set_bill_dispenser_lvl` | `upper_lvl`, `lower_lvl` | Set denominations |
| `set_bill_dispenser_count` | `upper_count`, `lower_count` | Add bills |
| `coin_system_status` | - | Get hopper status |
| `coin_system_add_coin_count` | `value`, `denomination` | Add coins |
| `coin_system_cash_collection` | - | Empty hopper |

### Example

```python
import asyncio
import json
from redis.asyncio import Redis

async def send_command():
    redis = Redis(host='localhost', port=6379, decode_responses=True)
    
    command = {
        "command": "start_accepting_payment",
        "command_id": 1,
        "data": {"amount": 10000}  # 100 RUB
    }
    
    await redis.publish("payment_system_cash_commands", json.dumps(command))
```

## Running

```bash
# Install dependencies
pip install -r requirements.txt

# Start the service (new architecture)
python main.py

# Or using the legacy entry point
python run_queue_server.py
```

## Device Configuration

Serial port configuration for devices:

```bash
# Find serial ports
sudo dmesg | grep tty

# Get device info
udevadm info -a -n /dev/ttyS1

# Create udev rules for consistent port names
sudo nano /etc/udev/rules.d/99-myserial.rules
# SUBSYSTEM=="tty", KERNEL=="ttyS*", ATTRS{id}=="PNP0501", SYMLINK+="myserial"

sudo udevadm control --reload-rules
sudo udevadm trigger
```

## Testing

```bash
# Run tests
python -m pytest tests/ -v
```