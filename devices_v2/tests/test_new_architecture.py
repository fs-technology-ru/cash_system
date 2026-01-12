"""
Unit tests for the new cash system architecture.

Tests core components, value objects, and services.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
sys.path.insert(0, '.')

from core.value_objects import Money, PaymentResult, DispensingResult, PaymentStatus
from core.exceptions import (
    CashSystemError,
    DeviceError,
    PaymentError,
    PaymentInProgressError,
)
from domain.payment_state_machine import PaymentStateMachine, PaymentPhase
from domain.device_manager import DeviceManager, DeviceRegistry
from infrastructure.settings import Settings, get_settings


# =============================================================================
# Value Objects Tests
# =============================================================================


class TestMoney:
    """Tests for Money value object."""

    def test_money_creation(self):
        """Test creating Money from kopecks."""
        m = Money(kopecks=5000)
        assert m.kopecks == 5000
        assert m.rubles == 50.0

    def test_money_from_rubles(self):
        """Test creating Money from rubles."""
        m = Money.from_rubles(100.50)
        assert m.kopecks == 10050
        assert m.rubles == 100.50

    def test_money_addition(self):
        """Test adding Money objects."""
        m1 = Money(kopecks=1000)
        m2 = Money(kopecks=500)
        result = m1 + m2
        assert result.kopecks == 1500

    def test_money_subtraction(self):
        """Test subtracting Money objects."""
        m1 = Money(kopecks=1000)
        m2 = Money(kopecks=300)
        result = m1 - m2
        assert result.kopecks == 700

    def test_money_subtraction_no_negative(self):
        """Test that Money subtraction doesn't go negative."""
        m1 = Money(kopecks=100)
        m2 = Money(kopecks=500)
        result = m1 - m2
        assert result.kopecks == 0

    def test_money_str(self):
        """Test Money string representation."""
        m = Money(kopecks=5050)
        assert str(m) == "50.50 RUB"

    def test_money_negative_raises(self):
        """Test that negative kopecks raises error."""
        with pytest.raises(ValueError):
            Money(kopecks=-100)


class TestPaymentResult:
    """Tests for PaymentResult value object."""

    def test_payment_result_started(self):
        """Test creating a started payment result."""
        result = PaymentResult.started(10000, ["bill_acceptor"])
        assert result.success is True
        assert result.target_amount == 10000
        assert "bill_acceptor" in result.active_devices

    def test_payment_result_stopped(self):
        """Test creating a stopped payment result."""
        result = PaymentResult.stopped(5000)
        assert result.success is True
        assert result.collected_amount == 5000

    def test_payment_result_completed(self):
        """Test creating a completed payment result."""
        result = PaymentResult.completed(12000, 10000)
        assert result.success is True
        assert result.collected_amount == 12000
        assert result.target_amount == 10000
        assert result.change_due == 2000

    def test_payment_result_failed(self):
        """Test creating a failed payment result."""
        result = PaymentResult.failed("Device error")
        assert result.success is False
        assert "Device error" in result.message

    def test_payment_result_to_dict(self):
        """Test converting PaymentResult to dict."""
        result = PaymentResult.started(10000, ["bill_acceptor"])
        d = result.to_dict()
        assert d["success"] is True
        assert d["target_amount"] == 10000


# =============================================================================
# Exception Tests
# =============================================================================


class TestExceptions:
    """Tests for custom exceptions."""

    def test_cash_system_error(self):
        """Test CashSystemError creation and to_dict."""
        error = CashSystemError("Test error", code="TEST_001")
        assert error.message == "Test error"
        assert error.code == "TEST_001"

        d = error.to_dict()
        assert d["error"] == "TEST_001"
        assert d["message"] == "Test error"

    def test_device_error_with_device_name(self):
        """Test DeviceError includes device name."""
        error = DeviceError("Connection failed", device_name="bill_acceptor")
        assert error.device_name == "bill_acceptor"
        assert error.details["device"] == "bill_acceptor"

    def test_payment_in_progress_error(self):
        """Test PaymentInProgressError is a PaymentError."""
        error = PaymentInProgressError("Already accepting payment")
        assert isinstance(error, PaymentError)


# =============================================================================
# Payment State Machine Tests
# =============================================================================


class TestPaymentStateMachine:
    """Tests for PaymentStateMachine."""

    @pytest.fixture
    def state_machine(self):
        """Create a fresh state machine for each test."""
        return PaymentStateMachine()

    def test_initial_state(self, state_machine):
        """Test initial state is IDLE."""
        assert state_machine.phase == PaymentPhase.IDLE
        assert not state_machine.is_active
        assert not state_machine.is_accepting

    @pytest.mark.asyncio
    async def test_start_payment(self, state_machine):
        """Test starting a payment."""
        result = await state_machine.start(10000, ["bill_acceptor"])
        assert result.success is True
        assert state_machine.phase == PaymentPhase.ACCEPTING
        assert state_machine.is_active
        assert state_machine.is_accepting

    @pytest.mark.asyncio
    async def test_start_payment_invalid_amount(self, state_machine):
        """Test starting payment with invalid amount raises error."""
        from core.exceptions import InvalidAmountError
        with pytest.raises(InvalidAmountError):
            await state_machine.start(-100, ["bill_acceptor"])

    @pytest.mark.asyncio
    async def test_start_payment_while_active(self, state_machine):
        """Test starting payment while one is active raises error."""
        await state_machine.start(10000, ["bill_acceptor"])
        with pytest.raises(PaymentInProgressError):
            await state_machine.start(5000, ["bill_acceptor"])

    @pytest.mark.asyncio
    async def test_add_payment(self, state_machine):
        """Test adding payment updates collected amount."""
        await state_machine.start(10000, ["bill_acceptor"])
        await state_machine.add_payment(5000, "bill_acceptor")
        assert state_machine.context.collected_amount == 5000

    @pytest.mark.asyncio
    async def test_payment_completion(self, state_machine):
        """Test payment completes when target reached."""
        state_machine.set_on_complete(AsyncMock())
        await state_machine.start(10000, ["bill_acceptor"])
        await state_machine.add_payment(10000, "bill_acceptor")
        assert state_machine.phase == PaymentPhase.COMPLETING

    @pytest.mark.asyncio
    async def test_stop_payment(self, state_machine):
        """Test stopping a payment."""
        await state_machine.start(10000, ["bill_acceptor"])
        await state_machine.add_payment(5000, "bill_acceptor")
        result = await state_machine.stop()
        assert result.success is True
        assert result.collected_amount == 5000
        assert state_machine.phase == PaymentPhase.IDLE


# =============================================================================
# Device Manager Tests
# =============================================================================


class TestDeviceRegistry:
    """Tests for DeviceRegistry."""

    def test_register_device(self):
        """Test registering a device."""
        registry = DeviceRegistry()
        mock_device = MagicMock()
        mock_device.device_name = "test_device"
        mock_device.device_type = MagicMock()

        registry.register(mock_device)
        assert "test_device" in registry

    def test_get_device(self):
        """Test getting a device by name."""
        registry = DeviceRegistry()
        mock_device = MagicMock()
        mock_device.device_name = "test_device"
        mock_device.device_type = MagicMock()

        registry.register(mock_device)
        retrieved = registry.get("test_device")
        assert retrieved == mock_device

    def test_get_nonexistent_device(self):
        """Test getting a device that doesn't exist."""
        registry = DeviceRegistry()
        assert registry.get("nonexistent") is None


class TestDeviceManager:
    """Tests for DeviceManager."""

    def test_device_manager_creation(self):
        """Test creating a DeviceManager."""
        manager = DeviceManager()
        assert not manager.is_initialized
        assert len(manager.registry) == 0


# =============================================================================
# Settings Tests
# =============================================================================


class TestSettings:
    """Tests for Settings configuration."""

    def test_settings_defaults(self):
        """Test default settings values."""
        settings = get_settings()
        assert settings.redis.host == "localhost"
        assert settings.redis.port == 6379
        assert settings.payment.min_dispenser_box_count == 50

    def test_settings_command_channel(self):
        """Test command channel setting."""
        settings = get_settings()
        assert settings.payment.command_channel == "payment_system_cash_commands"
        assert settings.payment.response_channel == "payment_system_cash_commands_response"


# =============================================================================
# Run tests
# =============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
