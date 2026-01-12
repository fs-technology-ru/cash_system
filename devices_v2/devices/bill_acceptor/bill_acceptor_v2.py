import asyncio

from redis.asyncio import Redis
import serial_asyncio

from event_system import EventPublisher, EventType
from configs import bill_acceptor_config
from loggers import logger


class BillAcceptor:
    """Интерфейс для коммуникации с купюроприемником."""

    def __init__(self, port: str, publisher: EventPublisher, redis: Redis):
        self.port = port
        self.publisher = publisher
        self.redis = redis

        # коммуникация
        self.reader = None
        self.writer = None
        self._msg_queue = asyncio.Queue()

        # отслеживание состояний
        self._active = False
        self._accepting_enabled = False
        self.target_amount = 0
        self.last_processed_bill = None
        self.bill_processed = False
        self.max_bill_count = None
        self.state_history = []
        self._stack_sent = False
        self._current_state = None  # Для адаптивной задержки polling

        # Счетчик транзакций
        self.transaction_counter = 0

        # Ссылки на задачи
        self._reader_task = None
        self._processor_task = None

        # НОВЫЙ флаг для принудительной остановки
        self._force_stop = False

        self._escrow_timestamp = None
        self._escrow_timeout = 3.0  # 10 секунд на обработку купюры

    async def initialize(self):
        """Инициализация."""
        if not await self._check_bill_acceptor_capacity():
            return False

        try:
            self.reader, self.writer = await serial_asyncio.open_serial_connection(
                url=self.port,
                baudrate=9600
            )
            poll_cmd = bill_acceptor_config.CMD_PULL
            poll_cmd += self._calculate_crc(poll_cmd)
            self.writer.write(poll_cmd)
            await self.writer.drain()
            response = await self._read_ccnet_message()
            if not response:
                raise Exception("No response from bill acceptor during initialization")

            self._reset_state()
            return True
        except Exception as e:
            logger.error(f"Ошибка подключения к порту {self.port}: {e}")
            return False

    def _reset_state(self):
        """Полный сброс внутреннего состояния"""
        self.last_processed_bill = None
        self.bill_processed = False
        self.state_history = []
        self._stack_sent = False

    async def reset_device(self) -> bool:
        """Сброс устройства."""
        try:
            self._reset_state()

            reset_cmd = bill_acceptor_config.CMD_RESET_DEVICE
            reset_cmd += self._calculate_crc(reset_cmd)
            self.writer.write(reset_cmd)
            await self.writer.drain()

            # После reset отправляем DISABLE
            disable_cmd = bill_acceptor_config.CMD_DISABLE
            disable_cmd += self._calculate_crc(disable_cmd)
            self.writer.write(disable_cmd)
            await self.writer.drain()

            # Очистка очереди
            while not self._msg_queue.empty():
                try:
                    self._msg_queue.get_nowait()
                    self._msg_queue.task_done()
                except asyncio.QueueEmpty:
                    break

            return True
        except Exception as e:
            logger.error(f"Ошибка сброса купюроприемника: {e}")
            return False

    async def start_accepting(self) -> None:
        """Начало приема купюр."""
        if self._active:
            await self.stop_accepting()

        self._reset_state()
        self._active = True
        self._accepting_enabled = True
        self._force_stop = False

        # Запускаем задачи
        self._reader_task = asyncio.create_task(self._serial_reader_task())
        self._processor_task = asyncio.create_task(self._message_processor_task())

        # Включаем прием купюр
        await self._enable_all_bills()

    async def stop_accepting(self) -> None:
        """Остановка приема купюр."""
        if not self._active:
            return

        # ПЕРВЫМ делом блокируем обработку
        self._accepting_enabled = False
        self._force_stop = True

        # Отправляем DISABLE
        try:
            disable_cmd = bill_acceptor_config.CMD_DISABLE
            disable_cmd += self._calculate_crc(disable_cmd)
            self.writer.write(disable_cmd)
            await self.writer.drain()
            logger.info("Disable command sent")
        except Exception as e:
            logger.error(f"Error sending disable: {e}")

        # Сбрасываем флаг СРАЗУ
        self._active = False
        logger.info(f"Set _active = False")

        # Отменяем задачи ПРИНУДИТЕЛЬНО
        tasks_to_cancel = []
        if self._reader_task and not self._reader_task.done():
            tasks_to_cancel.append(self._reader_task)
            logger.info("Cancelling reader task")
        if self._processor_task and not self._processor_task.done():
            tasks_to_cancel.append(self._processor_task)
            logger.info("Cancelling processor task")

        if tasks_to_cancel:
            for task in tasks_to_cancel:
                task.cancel()

            # Ждем отмены
            try:
                await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            except Exception as e:
                logger.error(f"Error cancelling tasks: {e}")

        # Очистка очереди (вроде и нихуя не делает но лучше перезбдеть)
        while not self._msg_queue.empty():
            try:
                self._msg_queue.get_nowait()
                self._msg_queue.task_done()
            except asyncio.QueueEmpty:
                break

        self._reset_state()
        self._reader_task = None
        self._processor_task = None
        logger.info("=== Bill acceptor STOPPED ===")

    def _calculate_crc(self, data: bytes) -> bytes:
        """Расчет CRC."""
        crc = 0
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ bill_acceptor_config.CRC_POLYNOMIAL
                else:
                    crc = crc >> 1
        return crc.to_bytes(2, 'little')

    def _verify_checksum(self, response: bytes) -> bool:
        """Валидация CRC ответа."""
        if len(response) < 6:
            return False
        return True

    async def _read_ccnet_message(self):
        """Чтение сообщения по протоколу CCNET."""
        try:
            # КРИТИЧНО: Ищем SYNC байт
            sync_found = False
            max_sync_attempts = 10

            for _ in range(max_sync_attempts):
                header = await asyncio.wait_for(self.reader.read(1), timeout=1.0)
                if len(header) == 0:
                    return None

                if header[0] == 0x02:  # Правильный SYNC байт
                    sync_found = True
                    break
                else:
                    logger.warning(f"Пропущен неверный байт: 0x{header[0]:x}")

            if not sync_found:
                logger.error("SYNC байт не найден после нескольких попыток")
                return None

            # Читаем ADDRESS и LENGTH
            addr_len = await asyncio.wait_for(self.reader.read(2), timeout=1.0)
            if len(addr_len) < 2:
                logger.error("Не удалось прочитать ADDRESS и LENGTH")
                return None

            address = addr_len[0]
            total_length = addr_len[1]

            # Валидация
            if address != 0x03:
                logger.error(f"Неверный ADDRESS: 0x{address:x}, ожидалось 0x03")
                return None

            if total_length < 3 or total_length > 50:
                logger.warning(f"Странная длина сообщения: {total_length}")
                # Очистка буфера
                try:
                    junk = await asyncio.wait_for(self.reader.read(100), timeout=0.1)
                    logger.error(f"!!! ОЧИЩЕНО {len(junk)} БАЙТ: {[f'0x{b:x}' for b in junk]}")
                except:
                    pass
                return None

            # Формируем header
            header = bytes([0x02, address, total_length])

            # Читаем остаток сообщения
            remaining_length = total_length - 3
            if remaining_length > 0:
                remaining = await asyncio.wait_for(
                    self.reader.read(remaining_length),
                    timeout=1.0
                )
                if len(remaining) < remaining_length:
                    logger.error(
                        f"Неполное сообщение: ожидалось {remaining_length}, получено {len(remaining)}")
                    return None
                complete_message = header + remaining
            else:
                complete_message = header

            return complete_message

        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.error(f"Ошибка чтения: {e}")
            return None

    async def _check_bill_acceptor_capacity(self) -> bool:
        """Проверка на переполненность купюр."""
        count = int(await self.redis.get("bill_count") or 0)
        self.max_bill_count = int(await self.redis.get('max_bill_count') or 0)
        if count >= self.max_bill_count:
            logger.error("Купюроприемник переполнен")
            return False
        return True

    async def _enable_all_bills(self):
        """Активация режима приема всех купюр."""
        enable_cmd = bill_acceptor_config.CMD_ACCEPT_ALL_BILLS
        enable_cmd += self._calculate_crc(enable_cmd)
        self.writer.write(enable_cmd)
        await self.writer.drain()

    async def _serial_reader_task(self):
        """Чтение данных из com порта."""
        logger.info("Reader task STARTED")
        try:
            while self._active and not self._force_stop:
                try:
                    # Отправляем POLL
                    poll_cmd = bill_acceptor_config.CMD_PULL
                    poll_cmd += self._calculate_crc(poll_cmd)
                    self.writer.write(poll_cmd)
                    await self.writer.drain()

                    # Читаем ответ
                    response = await self._read_ccnet_message()
                    if response:
                        await self._msg_queue.put(response)
                        # Сохраняем текущее состояние для адаптивной задержки
                        if len(response) > 3:
                            self._current_state = response[3]

                    # АДАПТИВНАЯ задержка: быстрее в STACKED, медленнее в остальных состояниях
                    if self._current_state == 0x81:  # STACKED - быстрый polling
                        await asyncio.sleep(0.01)  # 10ms - максимально быстро!
                    else:
                        await asyncio.sleep(0.2)  # Обычная скорость

                except asyncio.CancelledError:
                    logger.info("Reader task cancelled")
                    break
                except Exception as e:
                    if self._active:
                        logger.error(f"Ошибка чтения данных `_serial_reader_task`: {e}")
                        await asyncio.sleep(1)
        finally:
            logger.info("Reader task STOPPED")

    async def _message_processor_task(self):
        """Обработка сообщений из очереди."""
        logger.info("Processor task STARTED")
        try:
            while self._active and not self._force_stop:
                try:
                    data = await asyncio.wait_for(self._msg_queue.get(), timeout=0.5)
                    await self._process_response(data)
                    self._msg_queue.task_done()
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    logger.info("Processor task cancelled")
                    break
                except Exception as e:
                    if self._active:
                        logger.error(f"Processor error: {e}")
        finally:
            logger.info("Processor task STOPPED")

    async def _process_response(self, data: bytes) -> None:
        """Процесс обработки задач из очереди."""
        if len(data) < 6:
            return
        elif not self._verify_checksum(data):
            return

        state = data[3]
        state_name = bill_acceptor_config.STATES.get(state, f"UNKNOWN(0x{state:x})")
        logger.debug(f"Состояние купюроприемника: {state_name}")
        logger.debug(f'Data: {[f"0x{b:x}" for b in data]}')

        # Получаем предыдущее состояние
        prev_state = self.state_history[-1] if self.state_history else None

        # Добавляем состояние в историю
        self.state_history.append(state)
        if len(self.state_history) > 5:
            self.state_history.pop(0)

        # Игнорируем IDLING
        if state == 0x15:
            # Сбрасываем флаг ACK при возврате в IDLING
            if hasattr(self, '_ack_sent_for_bill'):
                delattr(self, '_ack_sent_for_bill')

        # Обработка STACKED (0x81) - ТОЛЬКО при переходе В это состояние
        elif state == 0x81 and prev_state != 0x81:
            # Извлекаем код купюры из data[4]
            if len(data) > 4:
                bill_code = bytes([data[4]])
                logger.info(
                    f"!!! STACKED получен (переход из 0x{prev_state:02x})! Код купюры: 0x{bill_code.hex()}")

                amount = bill_acceptor_config.BILL_CODES_V2.get(bill_code, 0)
                logger.info(f'!!! Сумма: {amount / 100} RUB')

                if self._accepting_enabled:
                    logger.info(f"!!! Публикуем BILL_ACCEPTED event, amount={amount}")
                    await self.publisher.publish(EventType.BILL_ACCEPTED, value=amount)
                    await self.redis.incr("bill_count")

                    self.transaction_counter += 1
                    logger.info(
                        f"!!! Bill accepted: {amount / 100} RUB, transaction #{self.transaction_counter}")

                    # Сохраняем код обработанной купюры
                    self.last_processed_bill = bill_code
                    self.bill_processed = True
                else:
                    logger.warning(f"!!! Bill stacked but accepting disabled: 0x{bill_code.hex()}")

                # Отправляем ACK один раз
                logger.info("!!! Отправляем enable_all_bills для возврата в polling")
                await self._enable_all_bills()
                self._ack_sent_for_bill = bill_code  # Помечаем, что ACK отправлен для этой купюры
            else:
                logger.error("!!! STACKED получен, но данные о купюре отсутствуют!")

        # Повторы состояния 0x81
        elif state == 0x81 and prev_state == 0x81:
            # Проверяем, отправляли ли уже ACK для этой купюры
            bill_code = bytes([data[4]]) if len(data) > 4 else None

            if bill_code and not hasattr(self, '_ack_sent_for_bill'):
                # Если по какой-то причине пропустили первый переход - отправляем ACK
                logger.warning("!!! STACKED (повтор), но ACK не был отправлен - отправляем сейчас")
                await self._enable_all_bills()
                self._ack_sent_for_bill = bill_code
            else:
                # Просто ждем смены состояния
                logger.debug(f"STACKED (повтор) - ожидаем смены состояния")

        # Сброс флагов при выходе из STACKED
        elif prev_state == 0x81 and state != 0x81:
            logger.info(f"Выход из STACKED в {state_name}, сбрасываем флаги")
            self.bill_processed = False
            self.last_processed_bill = None
            if hasattr(self, '_ack_sent_for_bill'):
                delattr(self, '_ack_sent_for_bill')

        # Обработка rejection
        elif state in [0x1c, 0x43, 0x44, 0x45, 0x46, 0x47]:
            logger.warning(f"Bill rejected, state: {state_name}")
            self.bill_processed = False
            self.last_processed_bill = None
            if hasattr(self, '_ack_sent_for_bill'):
                delattr(self, '_ack_sent_for_bill')