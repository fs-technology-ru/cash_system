"""
Command Handler - Routes Redis commands to API methods.

Provides clean command routing with validation and error handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Awaitable, Optional

from loggers import logger


# Type alias for command handlers
CommandHandlerFunc = Callable[..., Awaitable[dict[str, Any]]]


@dataclass
class CommandResponse:
    """
    Standardized response for command execution.

    Attributes:
        command_id: The ID of the executed command.
        success: Whether the command succeeded.
        message: Human-readable message.
        data: Optional response data.
    """

    command_id: Optional[int] = None
    success: bool = False
    message: Optional[str] = None
    data: Any = None

    def to_dict(self) -> dict[str, Any]:
        """Convert the response to a dictionary."""
        return {
            "command_id": self.command_id,
            "success": self.success,
            "message": self.message,
            "data": self.data,
        }


@dataclass
class CommandDefinition:
    """
    Definition of a command.

    Attributes:
        name: Command name.
        handler: Handler function.
        required_args: List of required argument names.
        description: Human-readable description.
    """

    name: str
    handler: CommandHandlerFunc
    required_args: list[str]
    description: str = ""


class CommandHandler:
    """
    Routes commands to their appropriate handlers.

    Provides a clean way to register and dispatch commands
    to their handler methods on the API facade.
    """

    def __init__(self, api: Any) -> None:
        """
        Initialize the command handler.

        Args:
            api: The PaymentSystemFacade instance.
        """
        self._api = api
        self._commands: dict[str, CommandDefinition] = {}
        self._register_default_commands()

    def _register_default_commands(self) -> None:
        """Register all default command handlers."""
        # Device initialization
        self.register(
            "init_devices",
            self._api.init_devices,
            [],
            "Initialize all payment devices",
        )

        # Payment flow
        self.register(
            "start_accepting_payment",
            self._api.start_accepting_payment,
            ["amount"],
            "Start accepting payment for specified amount",
        )
        self.register(
            "stop_accepting_payment",
            self._api.stop_accepting_payment,
            [],
            "Stop the current payment",
        )

        # Change dispensing
        self.register(
            "test_dispense_change",
            self._api.test_dispense_change,
            ["is_bill", "is_coin"],
            "Test change dispensing",
        )
        self.register(
            "dispense_change",
            self._api.dispense_change,
            ["amount"],
            "Dispense change for specified amount",
        )

        # Bill acceptor commands
        self.register(
            "bill_acceptor_set_max_bill_count",
            self._api.bill_acceptor_set_max_bill_count,
            ["value"],
            "Set maximum bill count for acceptor",
        )
        self.register(
            "bill_acceptor_reset_bill_count",
            self._api.bill_acceptor_reset_bill_count,
            [],
            "Reset bill count (cash collection)",
        )
        self.register(
            "bill_acceptor_status",
            self._api.bill_acceptor_status,
            [],
            "Get bill acceptor status",
        )

        # Bill dispenser commands
        self.register(
            "set_bill_dispenser_lvl",
            self._api.set_bill_dispenser_lvl,
            ["upper_lvl", "lower_lvl"],
            "Set bill dispenser denominations",
        )
        self.register(
            "set_bill_dispenser_count",
            self._api.set_bill_dispenser_count,
            ["upper_count", "lower_count"],
            "Add bills to dispenser",
        )
        self.register(
            "bill_dispenser_status",
            self._api.bill_dispenser_status,
            [],
            "Get bill dispenser status",
        )
        self.register(
            "bill_dispenser_reset_bill_count",
            self._api.bill_dispenser_reset_bill_count,
            [],
            "Reset bill dispenser counts",
        )

        # Coin system commands
        self.register(
            "coin_system_add_coin_count",
            self._api.coin_system_add_coin_count,
            ["value", "denomination"],
            "Add coins to hopper",
        )
        self.register(
            "coin_system_status",
            self._api.coin_system_status,
            [],
            "Get coin hopper status",
        )
        self.register(
            "coin_system_cash_collection",
            self._api.coin_system_cash_collection,
            [],
            "Perform cash collection from hopper",
        )

    def register(
        self,
        command_name: str,
        handler: CommandHandlerFunc,
        required_args: list[str],
        description: str = "",
    ) -> None:
        """
        Register a command handler.

        Args:
            command_name: The name of the command.
            handler: The async handler function.
            required_args: List of required argument names.
            description: Human-readable description.
        """
        self._commands[command_name] = CommandDefinition(
            name=command_name,
            handler=handler,
            required_args=required_args,
            description=description,
        )

    def get_available_commands(self) -> list[dict[str, Any]]:
        """Get list of available commands with their descriptions."""
        return [
            {
                "name": cmd.name,
                "required_args": cmd.required_args,
                "description": cmd.description,
            }
            for cmd in self._commands.values()
        ]

    async def execute(self, command_data: dict[str, Any]) -> dict[str, Any]:
        """
        Execute a command based on command data.

        Args:
            command_data: Dictionary containing 'command', 'command_id', and 'data'.

        Returns:
            Response dictionary with execution result.
        """
        command = command_data.get("command")
        command_id = command_data.get("command_id")
        data = command_data.get("data", {}) or {}

        response = CommandResponse(command_id=command_id)

        # Validate command exists
        if command not in self._commands:
            logger.warning(f"Unknown command: {command}")
            response.message = f"Unknown command: {command}"
            return response.to_dict()

        definition = self._commands[command]

        try:
            # Extract required arguments from data
            kwargs = {arg: data.get(arg) for arg in definition.required_args}

            # Validate required arguments
            missing = [arg for arg in definition.required_args if kwargs.get(arg) is None]
            if missing:
                response.message = f"Missing required arguments: {missing}"
                return response.to_dict()

            # Execute the handler
            if definition.required_args:
                result = await definition.handler(**kwargs)
            else:
                result = await definition.handler()

            # Update response with result
            if isinstance(result, dict):
                response.success = result.get("success", False)
                response.message = result.get("message")
                response.data = result.get("data")
            else:
                response.success = True
                response.data = result

        except Exception as e:
            logger.error(f"Error executing command '{command}': {e}")
            response.success = False
            response.message = f"Error: {e}"

        return response.to_dict()


async def payment_system_cash_commands(
    command_data: dict[str, Any],
    api: Any,
) -> dict[str, Any]:
    """
    Execute a command on the payment system API.

    This is the main entry point for command execution from Redis pub/sub.
    Maintains backward compatibility with the original function signature.

    Args:
        command_data: Dictionary containing command name, ID, and data.
        api: The PaymentSystemFacade instance.

    Returns:
        Response dictionary with execution result.
    """
    handler = CommandHandler(api)
    return await handler.execute(command_data)
