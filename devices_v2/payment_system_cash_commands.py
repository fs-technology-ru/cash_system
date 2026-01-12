"""
Command handler for the payment system.

This module provides command routing and execution for the cash payment system,
translating Redis pub/sub commands into API calls.
"""

from typing import Any, Callable, Awaitable, Optional

from loggers import logger


# Type alias for command handlers
CommandHandler = Callable[..., Awaitable[dict[str, Any]]]


class CommandResponse:
    """
    Standardized response for command execution.

    Attributes:
        command_id: The ID of the executed command.
        success: Whether the command succeeded.
        message: Human-readable message.
        data: Optional response data.
    """

    def __init__(
        self,
        command_id: Optional[int] = None,
        success: bool = False,
        message: Optional[str] = None,
        data: Any = None,
    ) -> None:
        self.command_id = command_id
        self.success = success
        self.message = message
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        """Convert the response to a dictionary."""
        return {
            "command_id": self.command_id,
            "success": self.success,
            "message": self.message,
            "data": self.data,
        }


class CommandRouter:
    """
    Routes commands to their appropriate handlers.

    This class provides a clean way to register and dispatch commands
    to their handler methods on the PaymentSystemAPI.
    """

    def __init__(self, api: Any) -> None:
        """
        Initialize the command router.

        Args:
            api: The PaymentSystemAPI instance.
        """
        self.api = api
        self._handlers: dict[str, tuple[CommandHandler, list[str]]] = {}
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """Register all default command handlers."""
        # Device initialization
        self.register("init_devices", self.api.init_devices, [])

        # Payment flow
        self.register("start_accepting_payment", self.api.start_accepting_payment, ["amount"])
        self.register("stop_accepting_payment", self.api.stop_accepting_payment, [])

        # Change dispensing
        self.register("test_dispense_change", self.api.test_dispense_change, ["is_bill", "is_coin"])
        self.register("dispense_change", self.api.dispense_change, ["amount"])

        # Bill acceptor commands
        self.register("bill_acceptor_set_max_bill_count", self.api.bill_acceptor_set_max_bill_count, ["value"])
        self.register("bill_acceptor_reset_bill_count", self.api.bill_acceptor_reset_bill_count, [])
        self.register("bill_acceptor_status", self.api.bill_acceptor_status, [])

        # Bill dispenser commands
        self.register("set_bill_dispenser_lvl", self.api.set_bill_dispenser_lvl, ["upper_lvl", "lower_lvl"])
        self.register("set_bill_dispenser_count", self.api.set_bill_dispenser_count, ["upper_count", "lower_count"])
        self.register("bill_dispenser_status", self.api.bill_dispenser_status, [])
        self.register("bill_dispenser_reset_bill_count", self.api.bill_dispenser_reset_bill_count, [])

        # Coin system commands
        self.register("coin_system_add_coin_count", self.api.coin_system_add_coin_count, ["value", "denomination"])
        self.register("coin_system_status", self.api.coin_system_status, [])
        self.register("coin_system_cash_collection", self.api.coin_system_cash_collection, [])

    def register(
        self,
        command_name: str,
        handler: CommandHandler,
        required_args: list[str],
    ) -> None:
        """
        Register a command handler.

        Args:
            command_name: The name of the command.
            handler: The async handler function.
            required_args: List of required argument names from data.
        """
        self._handlers[command_name] = (handler, required_args)

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

        if command not in self._handlers:
            logger.warning(f"Unknown command: {command}")
            response.message = f"Unknown command: {command}"
            return response.to_dict()

        handler, required_args = self._handlers[command]

        try:
            # Extract required arguments from data
            kwargs = {arg: data.get(arg) for arg in required_args}

            # Execute the handler
            result = await handler(**kwargs) if required_args else await handler()

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

    Args:
        command_data: Dictionary containing command name, ID, and data.
        api: The PaymentSystemAPI instance.

    Returns:
        Response dictionary with execution result.
    """
    router = CommandRouter(api)
    return await router.execute(command_data)
