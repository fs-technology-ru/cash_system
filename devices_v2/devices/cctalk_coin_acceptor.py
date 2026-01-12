
# -*- coding: utf-8 -*-
import asyncio
import serial_asyncio
from configs import COIN_ACCEPTOR_PORT
from event_system import EventType
from loggers import logger

# Конфигурация для ccTalk монетоприемника
# Взято из вашего рабочего скрипта
CCTALK_COIN_VALUES = {
    10: 100,
    12: 200,
    14: 500,
    16: 1000,   # Слот 16 для монеты в 10 рублей (1000 копеек)
    # Добавьте другие номиналы, если необходимо
}
DEVICE_ADDRESS = 2
HOST_ADDRESS = 1

class CcTalkAcceptor:
    """
    Асинхронный драйвер для монетоприемника, работающего по протоколу ccTalk.
    """
    def __init__(self, event_publisher):
        self.event_publisher = event_publisher
        self.port = COIN_ACCEPTOR_PORT
        self.reader = None
        self.writer = None
        self._is_polling = False
        self._polling_task = None
        self.last_event_counter = 0

    async def initialize(self):
        """Инициализация устройства."""
        try:
            self.reader, self.writer = await serial_asyncio.open_serial_connection(
                url=self.port, baudrate=9600, timeout=0.2
            )
            logger.info(f"ccTalk монетоприемник: порт {self.port} открыт.")
            
            # 1. Сброс устройства
            await self._send_command(1)
            await asyncio.sleep(0.5)
            logger.info("ccTalk монетоприемник: устройство сброшено.")

            # 2. Проверка связи
            response = await self._send_command(254)
            if response is None:
                logger.error("ccTalk монетоприемник: не отвечает после сброса.")
                return False
            logger.info("ccTalk монетоприемник: устройство на связи.")

            # 3. Инициализация счетчика событий
            initial_events = await self._send_command(229)
            if not initial_events:
                logger.error("ccTalk монетоприемник: не удалось получить начальный счетчик событий.")
                return False
            self.last_event_counter = initial_events[0]
            logger.info(f"ccTalk монетоприемник: счетчик событий инициализирован значением {self.last_event_counter}.")
            
            return True
        except Exception as e:
            logger.error(f"Ошибка инициализации ccTalk монетоприемника: {e}")
            return False

    async def enable(self):
        """Включить прием монет и запустить опрос."""
        if self._is_polling:
            logger.warning("ccTalk монетоприемник: опрос уже запущен.")
            return
        try:
            # Включаем все каналы монет
            await self._send_command(231, [255, 255])
            logger.info("ccTalk монетоприемник: прием монет включен.")
            
            self._is_polling = True
            self._polling_task = asyncio.create_task(self._poll_events())
            logger.info("ccTalk монетоприемник: запущен циклический опрос событий.")
        except Exception as e:
            logger.error(f"Ошибка при включении ccTalk монетоприемника: {e}")

    async def disable(self):
        """Выключить прием монет и остановить опрос."""
        if not self._is_polling:
            return
        try:
            # Выключаем все каналы монет
            await self._send_command(231, [0, 0])
            logger.info("ccTalk монетоприемник: прием монет выключен.")
            
            self._is_polling = False
            if self._polling_task:
                self._polling_task.cancel()
                await asyncio.sleep(0.1) # Даем время на завершение
            logger.info("ccTalk монетоприемник: циклический опрос остановлен.")
        except Exception as e:
            logger.error(f"Ошибка при выключении ccTalk монетоприемника: {e}")

    async def _poll_events(self):
        """Бесконечный цикл опроса устройства."""
        while self._is_polling:
            try:
                events = await self._send_command(229) # Read buffered credit
                
                if events and len(events) > 0:
                    current_event_counter = events[0]
                    
                    if current_event_counter != self.last_event_counter:
                        num_events_by_counter = (current_event_counter - self.last_event_counter + 256) % 256
                        num_events_in_buffer = (len(events) - 1) // 2
                        events_to_process = min(num_events_by_counter, num_events_in_buffer)

                        for i in range(events_to_process):
                            event_index = 1 + (i * 2)
                            if event_index + 1 >= len(events):
                                continue

                            coin_slot = events[event_index]
                            status_code = events[event_index + 1]
                            
                            if coin_slot == 0:
                                if status_code > 0:
                                    logger.warning(f"ccTalk монетоприемник: получено событие-статус (код: {status_code})")
                                continue
                            
                            if coin_slot in CCTALK_COIN_VALUES:
                                coin_value = CCTALK_COIN_VALUES[coin_slot]
                                logger.info(f"ccTalk монетоприемник: принята монета из слота {coin_slot} номиналом {coin_value / 100} рублей.")
                                # Публикуем событие для PaymentSystemAPI
                                await self.event_publisher.publish(EventType.COIN_CREDIT, value=coin_value)
                                # Сразу же снова разрешаем прием монет, чтобы подтвердить событие
                                await self._send_command(231, [255, 255])
                            else:
                                logger.warning(f"ccTalk монетоприемник: получена монета из не настроенного слота {coin_slot}")
                    
                    self.last_event_counter = current_event_counter
                
                await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                logger.info("ccTalk монетоприемник: задача опроса отменена.")
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле опроса ccTalk: {e}")
                await asyncio.sleep(1) # Пауза перед повторной попыткой

    def _calculate_checksum(self, data):
        """Рассчитывает контрольную сумму для ccTalk сообщения."""
        return (256 - (sum(data) % 256)) % 256

    async def _send_command(self, header, data=None):
        """Асинхронно отправляет команду и получает ответ."""
        if data is None:
            data = []
        
        payload = [DEVICE_ADDRESS, len(data), HOST_ADDRESS, header] + data
        checksum = self._calculate_checksum(payload)
        message = bytes(payload + [checksum])
        
        self.writer.write(message)
        await self.writer.drain()
        
        await asyncio.sleep(0.1) # Даем устройству время на ответ
        
        response = await self.reader.read(255)
        return self._parse_response(response)

    def _parse_response(self, response):
        """Разбирает ответ от устройства."""
        if not response:
            return None

        response_bytes = list(response)
        
        if len(response_bytes) < 5:
            return None

        payload = response_bytes[:-1]
        checksum = response_bytes[-1]
        
        if self._calculate_checksum(payload) != checksum:
            logger.warning(f"ccTalk: неверная контрольная сумма ответа: {response_bytes}")
            return None
            
        if response_bytes[0] != HOST_ADDRESS or response_bytes[2] != DEVICE_ADDRESS:
            logger.warning(f"ccTalk: ответ от другого устройства: {response_bytes}")
            return None

        return response_bytes[4:-1]
