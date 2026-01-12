import asyncio

from devices.coin_acceptor.index import SSP
from devices.bill_acceptor import bill_acceptor_v1, bill_acceptor_v2
from event_system import EventPublisher, EventConsumer, EventType
from configs import PORT_OPTIONS, BILL_DISPENSER_PORT, bill_acceptor_config, \
    COIN_ACCEPTOR_PORT, MIN_BOX_COUNT
from devices.bill_dispenser.bill_dispenser import Clcdm2000, LcdmException
from loggers import logger
from redis_error_handler import redis_error_handler
from send_to_ws import send_to_ws


class PaymentSystemAPI:
    """Api для взаимодействия с наличной системой оплаты."""
    def __init__(self, redis):
        # Event system
        self.event_queue = asyncio.Queue()
        self.event_publisher = EventPublisher(self.event_queue)
        self.event_consumer = EventConsumer(self.event_queue)

        # Redis connection
        self.redis = redis

        # Devices instances
        self.hopper = SSP(self.event_publisher)
        self.bill_acceptor = None
        self.bill_dispenser = Clcdm2000()

        # Payment tracking
        self.target_amount = 0
        self.collected_amount = 0
        self.active_devices = set()
        self.is_payment_in_progress = False
        self.dispensed_event = asyncio.Event()
        self.dispensed_amount = 0

        # Bill dispenser configurations
        self.upper_box_value = None
        self.lower_box_value = None
        self.upper_box_count = None
        self.lower_box_count = None


    async def bill_acceptor_status(self):
        """Статус купюроприемника."""
        try:
            max_bill_count = await self.redis.get('max_bill_count')
            bill_count = await self.redis.get('bill_count')
            return {
                'success': True,
                'message': 'Статус купюроприемника получен успешно',
                'data': {
                    'max_bill_count': int(max_bill_count) if max_bill_count else 0,
                    'bill_count': int(bill_count) if bill_count else 0,
                }
            }
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Redis connection issue: {e}")
            return {
                'success': False,
                'message': f"Redis connection issue: {e}"
            }


    async def bill_dispenser_status(self):
        """Статус купюродиспенсера."""
        try:
            upper_box_value = await self.redis.get('bill_dispenser:upper_lvl')
            lower_box_value = await self.redis.get('bill_dispenser:lower_lvl')
            upper_box_count = await self.redis.get('bill_dispenser:upper_count')
            lower_box_count = await self.redis.get('bill_dispenser:lower_count')
            return {
                'success': True,
                'message': 'Статус купюродиспенсера получен успешно',
                'data': {
                    'upper_box_value': int(upper_box_value) * 100,
                    'lower_box_value': int(lower_box_value) * 100,
                    'upper_box_count': int(upper_box_count),
                    'lower_box_count': int(lower_box_count),
                }
            }
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Redis connection issue: {e}")
            return {
                'success': False,
                'message': f"Redis connection issue: {e}"
            }


    @redis_error_handler("Максимальное количество купюр установлено успешно")
    async def bill_acceptor_set_max_bill_count(self, value: int):
        """Установка максимального количества купюр."""
        await self.redis.set('max_bill_count', value)
        await self.init_bill_acceptor()


    @redis_error_handler("Количество купюр в купюроприемнике обнулено успешно")
    async def bill_acceptor_reset_bill_count(self):
        """Сброс количества купюр в купюроприемнике (инкасация)."""
        await self.redis.set('bill_count', 0)


    @redis_error_handler("Номиналы диспенсера купюр установлены успешно")
    async def set_bill_dispenser_lvl(self, upper_lvl, lower_lvl):
        """Установка номиналов купюр в диспенсере."""
        await self.redis.set('bill_dispenser:upper_lvl', upper_lvl)
        await self.redis.set('bill_dispenser:lower_lvl', lower_lvl)


    @redis_error_handler("Количество купюр диспенсера установлено успешно")
    async def set_bill_dispenser_count(self, upper_count, lower_count):
        """
        Изменение количества купюр в диспенсере.
        Прибавляет переданное значение к существующему.
        """
        old_upper_count = int(await self.redis.get('bill_dispenser:upper_count'))
        old_lower_count = int(await self.redis.get('bill_dispenser:lower_count'))
        await self.redis.set('bill_dispenser:upper_count', upper_count + old_upper_count)
        await self.redis.set('bill_dispenser:lower_count', lower_count + old_lower_count)


    @redis_error_handler("Количество купюр в диспенсере обнулено успешно")
    async def bill_dispenser_reset_bill_count(self):
        """Сброс количества купюр в диспенсере."""
        await self.redis.set('bill_dispenser:upper_count', 0)
        await self.redis.set('bill_dispenser:lower_count', 0)


    async def stop_accepting_payment(self):
        """Остановка активного платежа."""
        if not self.is_payment_in_progress:
            logger.warning('Платеж не был запущен')
            return {
                'success': False,
                'message': 'Платеж не был запущен',
            }
        
        logger.info('Остановка платежа...')
        
        # Останавливаем устройства
        if "coin_acceptor" in self.active_devices:
            try:
                await self.hopper.disable()
            except Exception as e:
                logger.error(f"Error disabling hopper: {e}")
        
        if "bill_acceptor" in self.active_devices and self.bill_acceptor:
            try:
                await self.bill_acceptor.stop_accepting()
                await asyncio.sleep(0.5)
                await self.bill_acceptor.reset_device()
            except Exception as e:
                logger.error(f"Error stopping bill acceptor: {e}")
        
        # Сбрасываем состояние
        self.is_payment_in_progress = False
        self.target_amount = 0
        collected = self.collected_amount
        self.collected_amount = 0
        
        # Сброс Redis
        await self.redis.set('collected_amount', 0)
        await self.redis.set('target_amount', 0)
        
        logger.info(f'Платеж остановлен. Было собрано: {collected / 100} руб')
        return {
            'success': True,
            'message': f'Платеж остановлен. Было собрано: {collected / 100} руб',
            'collected_amount': collected,
        }


    @redis_error_handler("Тест выдачи сдачи прошел успешно")
    async def test_dispense_change(self, is_bill: bool, is_coin: bool):
        """Тест выдачи сдачи."""
        try:
            if is_coin:
                await self.hopper.enable()
                await self.hopper.command('PAYOUT_AMOUNT', {
                    'amount': 100,
                    'country_code': 'RUB',
                    'test': False
                })
            if is_bill:
                self.upper_box_value = int(await self.redis.get('bill_dispenser:upper_lvl'))
                self.lower_box_value = int(await self.redis.get('bill_dispenser:lower_lvl'))
                await self.dispense_change(self.upper_box_value + self.lower_box_value)
        except Exception as e:
            return {
                'success': False,
                'message': f"Ошибка при выдаче сдачи: {e}"
            }


    async def coin_system_add_coin_count(self, value: int, denomination: int):
        """Добавление монет определенного уровня."""
        try:
            await self.hopper.enable()
            await self.hopper.command('SET_DENOMINATION_LEVEL', {
                'value': value,
                'denomination': denomination,
                'country_code': 'RUB',
            })
            logger.info('Добавление монет прошло успешно')
            return {
                'success': True,
                'message': 'Добавление монет прошло успешно',
            }
        except Exception as e:
            return {
                'success': False,
                'message': f"Ошибка при работе с hopper: {e}"
            }


    async def coin_system_status(self):
        """Получение статуса hopper (уровни монет)."""
        try:
            await self.hopper.enable()
            status = await self.hopper.command('GET_ALL_LEVELS')
            return {
                'success': True,
                'data': status,
                'message': 'Статус hopper получен успешно',
            }
        except Exception as e:
            return {
                'success': False,
                'message': f"Ошибка при работе с hopper: {e}"
            }


    async def coin_system_cash_collection(self):
        """Инкассация."""
        try:
            await self.hopper.enable()
            await self.hopper.command('EMPTY_ALL')
            return {
                'success': True,
                'message': 'Инкассация hopper запущена успешно',
            }
        except Exception as e:
            return {
                'success': False,
                'message': f"Ошибка при инкассации hopper: {e}"
            }


    async def init_devices(self):
        """Инициализация устройств."""
        await self.init_coin_acceptor()
        await self.init_bill_acceptor()
        await self.init_bill_dispenser()

        self.register_event_handlers()
        asyncio.create_task(self.event_consumer.start_consuming())

        available_devices = await self.redis.smembers("available_devices_cash")

        if available_devices.issubset(self.active_devices):
            logger.info('Платежная система инициализирована успешно')
            return {
                'success': True,
                'message': 'Платежная система инициализирована успешно',
            }
        else:
            logger.error(
                f'Не удалось инициализировать устройтсва: '
                f'{available_devices - self.active_devices}')
            return {
                'success': False,
                'message': f'Не удалось инициализировать устройтсва: '
                           f'{available_devices - self.active_devices}',
            }


    async def init_coin_acceptor(self):
        """Инициализация Smart Hopper."""
        try:
            self.hopper.open(COIN_ACCEPTOR_PORT, PORT_OPTIONS)

            await self.hopper.command('SYNC')
            await self.hopper.command('HOST_PROTOCOL_VERSION', {'version': 6})
            await self.hopper.init_encryption()
            await self.hopper.command('SETUP_REQUEST')

            logger.info('Монетоприемник инициализирован успешно')
            self.active_devices.add("coin_acceptor")
        except Exception as e:
            logger.error(f'Ошибка инициализации монетоприемника: {e}')


    async def init_bill_acceptor(self):
        """Инициализация bill acceptor."""
        await self.redis.set('bill_acceptor_firmware', 'v2')
        bill_acceptor_firmware = await self.redis.get('bill_acceptor_firmware')
        if bill_acceptor_firmware == 'v1':
            self.bill_acceptor = bill_acceptor_v1.BillAcceptor(
                bill_acceptor_config.BILL_ACCEPTOR_PORT,
                self.event_publisher,
                self.redis,
            )
        if bill_acceptor_firmware == 'v2':
            self.bill_acceptor = bill_acceptor_v2.BillAcceptor(
                bill_acceptor_config.BILL_ACCEPTOR_PORT,
                self.event_publisher,
                self.redis,
            )
        try:
            if not await self.bill_acceptor.initialize():
                raise
            await self.bill_acceptor.reset_device()
            logger.info("Купюроприемник инициализирован успешно")
            self.active_devices.add("bill_acceptor")
        except Exception as e:
            logger.error(f"Ошибка инициализации купюроприемника: {e}")


    async def init_bill_dispenser(self):
        """Инициализация bill dispenser."""
        try:
            self.bill_dispenser.connect(BILL_DISPENSER_PORT, 9600)
            self.bill_dispenser.purge()
            logger.info('Bill dispenser инициализирован успешно')
            self.active_devices.add("bill_dispenser")
        except LcdmException as e:
            logger.error(f'Ошибка соединения при инициализации Bill dispenser: {e}')


    def register_event_handlers(self):
        """Регистрация обработчиков для событий приема монет и купюр."""
        self.event_consumer.register_handler(EventType.BILL_ACCEPTED, self.handle_bill_accepted)
        self.event_consumer.register_handler(EventType.COIN_CREDIT, self.on_coin_credit)
        self.event_consumer.register_handler(EventType.DISPENSED, self.on_dispensed)
        self.event_consumer.register_handler(EventType.INCOMPLETE_PAYOUT, self.on_dispensed)

    async def on_dispensed(self, event):
        """Обработчик события DISPENSED."""
        logger.info(f"on_dispensed event: {event}")
        info = event.get('info', {})
        if info.get('name') == 'INCOMPLETE_PAYOUT':
            self.dispensed_amount = info.get('actual', 0)
        else:
            value = info.get('value')
            if isinstance(value, list):
                self.dispensed_amount = sum(item.get('value', 0) for item in value)
            elif isinstance(value, int):
                self.dispensed_amount = value
            else:
                self.dispensed_amount = 0
        self.dispensed_event.set()


    async def handle_bill_accepted(self, event):
        """Обработчик принятия купюры."""
        bill_value = event['value']
        self.collected_amount += bill_value
        await self.redis.set('collected_amount', self.collected_amount)

        logger.info(f"Принята купюра: {bill_value / 100} рублей. Всего принято: {self.collected_amount / 100} рублей")
        await send_to_ws(
            event='acceptedBill',
            data={'bill_value': bill_value, 'collected_amount': self.collected_amount},
        )

        if self.target_amount != 0 and self.collected_amount >= self.target_amount:
            await self.complete_payment()


    async def on_coin_credit(self, event):
        """Обработчик принятия монеты."""
        logger.info(f"on_coin_credit event: {event}")
        try:
            coin_data = event.get('info').get("value")[0]
            num = coin_data.get("value")
            amount_map = {1375731712: 100, 1375731713: 500, 1375731715: 1000}

            if len(event.get('info').get("value")) == 200 and amount_map.get(num) == 100:
                amount = 200
            else:
                amount = amount_map.get(num, None)

            if amount is None:
                logger.error(f"Ошибка, неизвестная монета: {num}")
                return

            self.collected_amount += amount
            await self.redis.set('collected_amount', self.collected_amount)

            logger.info(f"Получена монета: {amount / 100} рублей. Всего: {self.collected_amount / 100} рублей")

            # Check if we reached or exceeded the target
            if (self.collected_amount >= self.target_amount) and (self.target_amount > 0):
                await self.complete_payment()

        except Exception as e:
            logger.error(f'Ошибка при получении монеты: {e}')


    async def start_accepting_payment(self, amount):
        """Начало платежа."""
        if amount <= 0:
            logger.error(f'Некорректная сумма платежа: {amount}')
            return {
                'success': False,
                'message': 'Некорректная сумма платежа',
            }
        
        upper_box_count = int(await self.redis.get('bill_dispenser:upper_count'))
        lower_box_count = int(await self.redis.get('bill_dispenser:lower_count'))
        bill_count = int(await self.redis.get('bill_count'))
        max_bill_count = int(await self.redis.get('max_bill_count'))
        is_test_mode = await self.redis.get('cash_system_is_test_mode')

        if self.is_payment_in_progress:
            logger.error('Платеж уже запущен')
            return {
                'success': False,
                'message': 'Платеж уже запущен',
            }

        if is_test_mode:
            logger.info('Тестовый режим — пропускаем проверки купюр.')
        elif upper_box_count < MIN_BOX_COUNT or lower_box_count < MIN_BOX_COUNT:
            logger.error(f'В bill_dispenser недостаточно купюр, менее {MIN_BOX_COUNT}. '
                         f'Верхний: {upper_box_count}, Нижний: {lower_box_count}')
            return {
                'success': False,
                'message': 'В устройстве bill_dispenser не достаточно купюр.',
            }
        elif bill_count >= max_bill_count:
            logger.error('Устройство bill acceptor переполнено')
            return {
                'success': False,
                'message': 'Устройство bill acceptor переполнено',
            }

        logger.info(f"Начат прием на сумму {amount / 100} рублей")

        # Устанавливаем значения ПЕРЕД запуском устройств
        self.target_amount = amount
        self.collected_amount = 0
        self.is_payment_in_progress = True

        await self.redis.set('target_amount', amount)
        await self.redis.set('collected_amount', 0)

        devices_started = []
        errors = []

        # Запускаем устройства с обработкой ошибок
        if "coin_acceptor" in self.active_devices:
            try:
                await self.hopper.enable()
                devices_started.append("coin acceptor")
                logger.info("Coin acceptor enabled")
            except Exception as e:
                logger.error(f"Failed to enable coin acceptor: {e}")
                errors.append(f"coin acceptor: {e}")

        if "bill_acceptor" in self.active_devices and self.bill_acceptor:
            try:
                # Убеждаемся что устройство не активно
                if self.bill_acceptor._active:
                    logger.warning("Bill acceptor was already active, stopping first")
                    await self.bill_acceptor.stop_accepting()
                    await asyncio.sleep(0.5)
                
                await self.bill_acceptor.start_accepting()
                devices_started.append("bill acceptor")
                logger.info("Bill acceptor enabled")
            except Exception as e:
                logger.error(f"Failed to enable bill acceptor: {e}")
                errors.append(f"bill acceptor: {e}")

        if devices_started:
            message = f"Начат прием на сумму {amount / 100} руб. Активны: {', '.join(devices_started)}"
            if errors:
                message += f". Ошибки: {'; '.join(errors)}"
            return {
                'success': True,
                'message': message,
                'active_devices': devices_started,
            }
        else:
            self.is_payment_in_progress = False
            self.target_amount = 0
            self.collected_amount = 0
            logger.error('Не удалось запустить ни одно устройство')
            return {
                'success': False,
                'message': f'Не удалось запустить устройства. Ошибки: {"; ".join(errors)}',
            }


    async def complete_payment(self):
        """Успешное завершение платежа."""
        logger.info("=== COMPLETING PAYMENT ===")
        
        # Сохраняем значения
        collected = self.collected_amount
        target = self.target_amount
        change = max(0, collected - target)
        
        # Сбрасываем флаг платежа ПЕРВЫМ делом
        self.is_payment_in_progress = False
        
        # Останавливаем устройства
        if "bill_acceptor" in self.active_devices and self.bill_acceptor:
            try:
                await self.bill_acceptor.stop_accepting()
                logger.info("Bill acceptor stopped and reset")
            except Exception as e:
                logger.error(f"Error stopping bill acceptor: {e}")
        
        if "coin_acceptor" in self.active_devices:
            try:
                await self.hopper.disable()
                logger.info("Coin acceptor disabled")
            except Exception as e:
                logger.error(f"Error disabling coin: {e}")

        # Сбрасываем счетчики
        self.target_amount = 0
        self.collected_amount = 0
        await self.redis.set('collected_amount', 0)
        await self.redis.set('target_amount', 0)

        logger.info(f"Payment completed: {collected/100} RUB, change: {change/100} RUB")
        
        await send_to_ws(
            event='successPayment',
            data={'collected_amount': collected, 'change': change},
        )

        # Выдача сдачи
        if change > 0:
            try:
                await self.dispense_change(change)
            except Exception as e:
                logger.error(f"Error dispensing change: {e}")


    async def dispense_change(self, amount):
        """Выдача сдачи."""
        dispensed_amount = 0

        self.upper_box_value = int(await self.redis.get('bill_dispenser:upper_lvl'))
        self.lower_box_value = int(await self.redis.get('bill_dispenser:lower_lvl'))
        # Сначала пробуем выдать купюры
        if "bill_dispenser" in self.active_devices and amount >= self.lower_box_value:
            try:
                # Определяем какой номинал больше
                higher_box_value = max(self.upper_box_value, self.lower_box_value)
                lower_box_value = min(self.upper_box_value, self.lower_box_value)

                # Сначала используем больший номинал, затем меньший
                higher_bills = int(amount // higher_box_value)
                lower_bills = int((amount % higher_box_value) // lower_box_value)

                if higher_bills > 0 or lower_bills > 0:
                    # В зависимости от того, какой номинал был больше, передаем параметры в правильном порядке
                    if self.upper_box_value > self.lower_box_value:
                        result = self.bill_dispenser.upperLowerDispense(higher_bills, lower_bills)
                    else:
                        result = self.bill_dispenser.upperLowerDispense(lower_bills, higher_bills)

                    upper_exit, lower_exit, upper_rejected, lower_rejected, upper_check, lower_check = result

                    dispensed_amount = (upper_exit * self.upper_box_value + lower_exit * self.lower_box_value)
                    amount -= dispensed_amount

                    upper_count = int(await self.redis.get('bill_dispenser:upper_count'))
                    lower_count = int(await self.redis.get('bill_dispenser:lower_count'))
                    new_upper = upper_count - upper_exit
                    new_lower = lower_count - lower_exit
                    await self.redis.set('bill_dispenser:upper_count', new_upper)
                    await self.redis.set('bill_dispenser:lower_count', new_lower)

            except Exception as e:
                logger.error(f'Ошибка при выдаче купюр: {e}')
                return {
                    'success': False,
                    'message': f'Ошибка при выдаче купюр: {e}',
                }

        if "coin_acceptor" in self.active_devices:
            try:
                await self.hopper.enable()
                self.dispensed_event.clear()
                self.dispensed_amount = 0
                coins_to_dispense = int(amount)
                result = await self.hopper.command('PAYOUT_AMOUNT', {
                    'amount': coins_to_dispense,
                    'country_code': 'RUB',
                    'test': False
                })

                if result.get("success"):
                    await asyncio.wait_for(self.dispensed_event.wait(), timeout=30)
                    dispensed_amount += self.dispensed_amount
                    amount -= self.dispensed_amount
                else:
                    error_msg = f"Coin payout failed: {result.get('error', 'Unknown error')}"
                    logger.error(error_msg)

            except asyncio.TimeoutError:
                logger.error("Timeout waiting for DISPENSED event")
            except Exception as e:
                error_msg = f"Ошибка при выдаче монет: {str(e)}"
                logger.error(error_msg)
            finally:
                await self.hopper.disable()

        if amount > 0:
            logger.info(f"Остаток не выданной сдачи: {amount / 100} RUB")

        if dispensed_amount > 0:
            logger.info(f"Выдано сдачи: {dispensed_amount / 100} RUB, невыданный остаток: {amount / 100}")
            return {
                'success': True,
                'message': 'Сдача выдана успешно',
            }
        else:
            logger.info("Сдача не выдана")
            return {
                'success': False,
                'message': 'Сдача не выдана',
            }


    async def shutdown(self):
        """Завершение работы с устройствами."""
        try:
            if "coin_acceptor" in self.active_devices:
                await self.hopper.disable()
                await self.hopper.close()

            if "bill_acceptor" in self.active_devices and self.bill_acceptor:
                await self.bill_acceptor.stop_accepting()

            # Stop event consumer
            await self.event_consumer.stop_consuming()

            logger.info("Платежная система выключена успешно")
        except Exception as e:
            logger.error(f"Ошибка выключения платежной системы: {e}")