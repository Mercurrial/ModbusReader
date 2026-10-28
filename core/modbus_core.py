import struct
import time
import queue
from PyQt6.QtCore import QThread, pyqtSignal

from core import datatypes
from core import linestats
from core import transports
from core.modbus_client import TcpMaster, link_error_kind, mbap
from app.i18n import get_translator
# Byte-order codecs live in datatypes.py now (single source of truth).
# Re-exported here for backward compatibility with any external importer.
from core.datatypes import (
    pack_float, unpack_float, pack_long, unpack_long, pack_short, unpack_short,
)


# ==========================================
# ЯДРО ОПРОСА (ОТДЕЛЬНЫЙ ПОТОК)
# ==========================================
class ModbusCore(QThread):
    status_changed = pyqtSignal(bool, str)
    data_updated = pyqtSignal(int, str)
    log_msg = pyqtSignal(str, str)
    # The link did not open: (link_error_kind, the OS text). The window
    # shows the connection card with the reason in words.
    open_failed = pyqtSignal(str, str)

    # === НОВЫЙ СИГНАЛ ===
    # Передает: (адрес массива, список прочитанных 16-битных слов)
    array_read_finished = pyqtSignal(int, list)

    def __init__(self):
        super().__init__()
        self.client = None
        self.is_running = False
        # Set by stop(); checked right after connect() so a click on
        # «Отключить» while the port is still opening is not lost.
        self._abort = False
        self.slave_id = 10
        self.timeout = 1.0        # client response timeout, s
        self.poll_interval = 0.5  # pause between dashboard poll cycles, s
        self.interframe = 0.05    # pause between frames (write words, chunks), s
        # Active transport (serial / TCP / …) — chosen in setup_connection from
        # the "transport" setting. The link details (serial port / TCP host)
        # live in self.settings; the descriptor builds the client from them.
        self.settings = {}
        self.transport = transports.get(transports.DEFAULT_ID)
        # Translator for the messages this thread emits. AppContext swaps it
        # when the UI language changes; a bare core (tests, scripts) speaks
        # Russian, the app's primary language. A dict lookup — thread-safe.
        self.t = get_translator("ru")

        # Связь / переподключение
        self.retries = 3              # подряд неудачных опросов до "связь потеряна"
        self.auto_reconnect = False   # молча переподключаться после потери связи
        self.reconnect_interval = 5.0 # секунд между тихими попытками переподключения

        self.poll_list = []
        self.write_queue = queue.Queue()
        self.array_read_queue = queue.Queue()  # Очередь для разовых запросов чтения массивов
        self.op_queue = queue.Queue()          # Синхронные операции макросов (высший приоритет)
        self.raw_queue = queue.Queue()         # Сырые кадры из консоли (отправка как есть)
        self.verbose_addrs = set()  # Адреса, для которых логируется опрос в консоль
        # Every exchange on the line is counted here (status-bar statistics).
        self.stats = linestats.LineStats()

    def _msg(self, key: str, **params) -> str:
        """Translated message for *key* (i18n.STRINGS), filled with params."""
        try:
            return self.t(key).format(**params)
        except (KeyError, IndexError, ValueError):
            return key

    def setup_connection(self, settings, slave_id):
        # The transport descriptor owns all link-specific parsing (port/baudrate/
        # parity for serial, host/port for TCP) — see transports.py. ModbusCore
        # just keeps the raw settings snapshot and the chosen descriptor.
        self.settings = dict(settings)
        self.transport = transports.get(settings.get("transport", "serial"))
        try:
            self.slave_id = int(slave_id)
        except (TypeError, ValueError):
            self.slave_id = 10
        # Все три ручки — из настроек (секция «Опрос», применяется к новым
        # подключениям): мс → секунды, с защитными границами.
        def _sec(key, default_ms, lo, hi):
            try:
                return min(hi, max(lo, float(settings.get(key, default_ms)) / 1000.0))
            except (TypeError, ValueError):
                return default_ms / 1000.0
        self.timeout       = _sec("timeout", 1000, 0.1, 5.0)
        self.poll_interval = _sec("poll_rate", 500, 0.1, 5.0)   # пауза между циклами
        self.interframe    = _sec("interframe_delay", 50, 0.0, 0.5)
        try:
            self.retries = max(1, int(settings.get("retry_count", 3)))
        except (TypeError, ValueError):
            self.retries = 3
        self.auto_reconnect = bool(settings.get("auto_reconnect", False))
        try:
            self.reconnect_interval = max(0.5, float(settings.get("reconnect_interval", 5)))
        except (TypeError, ValueError):
            self.reconnect_interval = 5.0

    def update_profile(self, profile_data):
        self.poll_list = [
            reg for reg in profile_data
            if datatypes.should_poll(reg.get("type", ""))
        ]

    def queue_write(self, addr, dtype, value):
        self.write_queue.put({"addr": addr, "type": dtype, "value": value})

    def queue_array_read(self, addr, length):
        """Интерфейс вызывает этот метод, чтобы заказать чтение массива памяти"""
        self.array_read_queue.put({"addr": addr, "length": length})

    def queue_raw(self, frame: bytes):
        """Консоль: отправить кадр в порт как есть (байт-в-байт, без framer'а).
        Обмен виден в журнале обычными TX/RX-строками."""
        self.raw_queue.put(bytes(frame))

    # ==========================================
    # СИНХРОННЫЙ КАНАЛ ДЛЯ МАКРОСОВ
    # ==========================================
    def request_op(self, kind, addr, dtype, value=None, timeout=5.0, slave=None,
                   count=None):
        """Блокирующая операция чтения/записи для потоков макросов/сканера.

        Кладёт задачу в op_queue (обрабатывается в потоке ModbusCore с высшим
        приоритетом) и ждёт результат. Возвращает значение для 'read',
        'alive'/'exception'/'silent' для 'probe', None для 'write'. Бросает
        RuntimeError при ошибке/таймауте — вызывающий поток ловит её.
        *slave* переопределяет slave ID для ЭТОЙ операции (перебор сканера)."""
        if not self.is_running:
            raise RuntimeError(self._msg("coreNotConnected"))
        result = queue.Queue(maxsize=1)
        self.op_queue.put({"kind": kind, "addr": int(addr), "type": dtype,
                           "value": value, "slave": slave, "count": count,
                           "result": result})
        try:
            status, payload = result.get(timeout=timeout)
        except queue.Empty:
            raise RuntimeError(self._msg("coreOpTimeout", kind=kind,
                                         addr=f"0x{int(addr):04X}"))
        if status == "err":
            raise RuntimeError(payload)
        return payload

    def _execute_op(self, op):
        result = op["result"]
        try:
            if op["kind"] == "read":
                value = self._read_value(op["addr"], op["type"],
                                         slave=op.get("slave"),
                                         count=op.get("count"))
                result.put(("ok", value))
            elif op["kind"] == "write":
                # A macro must learn that its write was refused — otherwise a
                # script carries on as if the setpoint had been applied.
                if self._execute_write(op["addr"], op["type"], str(op["value"])):
                    result.put(("ok", None))
                else:
                    result.put(("err", self._msg("coreWriteFailedOp",
                                                 addr=datatypes.key_label(op["addr"]))))
            elif op["kind"] == "probe":
                result.put(("ok", self._probe(op["addr"], op.get("slave"))))
            elif op["kind"] == "ping":
                result.put(("ok", self._ping(op["addr"], op.get("slave"))))
            else:
                result.put(("err", self._msg("coreUnknownOp", kind=op["kind"])))
        except Exception as e:
            result.put(("err", str(e)))

    def _probe(self, addr, slave) -> str:
        """Scanner ping: one 1-register read. Classify the outcome:
        'alive'     — normal response (device answered with data);
        'exception' — a Modbus exception response (device is ALIVE, it just
                      refuses this address/function — счётся найденным);
        'silent'    — no response at all (timeout / IO error)."""
        area, raw = datatypes.split_key(int(addr))   # a holding key IS the address
        try:
            res = self._counted_read(raw, 1, slave=slave, area=area)
        except Exception:
            return "silent"
        return {"ok": "alive", "exception": "exception"}.get(
            linestats.classify(res), "silent")

    def _ping(self, key, slave) -> dict:
        """The connection card's «Проверить связь» on the open link: one
        1-register read, with what exactly came back — {"state": ok |
        exception | timeout | crc, "code": exception code, "ms": time}."""
        area, raw = datatypes.split_key(int(key))
        t0 = time.perf_counter()
        try:
            res = self._counted_read(raw, 1, slave=slave, area=area)
        except Exception:
            return {"state": "timeout", "code": 0, "ms": None}
        return {"state": linestats.classify(res),
                "code": int(getattr(res, "exception_code", 0) or 0),
                "ms": (time.perf_counter() - t0) * 1000.0}

    def _read_value(self, addr, dtype, slave=None, count=None):
        """Синхронное чтение одного регистра → число. Также обновляет дашборд
        (только для СВОЕГО устройства — чтение чужого slave при сканировании
        не должно подменять значения в основной таблице)."""
        if not datatypes.is_scalar(dtype):
            raise RuntimeError(self._msg("coreNotReadable", type=dtype))
        key = int(addr)
        area, raw = datatypes.split_key(key)
        if count is None:
            reg = self._find_reg(key)
            count = (datatypes.reg_read_count(reg) if reg
                     else datatypes.read_count(dtype))
        res = self._counted_read(raw, count, slave=slave, area=area)
        if not res or res.isError():
            raise RuntimeError(self._msg("coreNoAnswer", addr=datatypes.key_label(key)))
        value = datatypes.decode(dtype, res.registers)
        if slave is None or int(slave) == self.slave_id:
            self.data_updated.emit(key, datatypes.read_to_str(dtype, res.registers))
        return value

    def _make_client(self):
        # The active transport descriptor builds the client (core/modbus_client)
        # from self.settings (retries=1 rationale lives in transports.py).
        return self.transport.create(self.settings, self.timeout)

    def _describe(self):
        """Human link string for status messages, e.g. 'COM1 (115200)'."""
        return self.transport.describe(self.settings)

    def start(self, *args, **kwargs):
        self._abort = False
        super().start(*args, **kwargs)

    def run(self):
        # Building the client or opening the port can raise (a port name the
        # OS rejects, a driver that throws instead of returning False). Inside
        # a QThread an uncaught exception just ends the thread — the window
        # would sit on "connecting" forever with nothing in the log.
        try:
            self.client = self._make_client()
            opened = bool(self.client.connect())
        except Exception as e:
            self.client = None
            self._report_open_fail(link_error_kind(e), str(e))
            return
        if not opened:
            self._report_open_fail(getattr(self.client, "last_error", "") or "other",
                                   getattr(self.client, "last_error_text", ""))
            return
        if self._abort:                       # «Отключить» while opening
            self._close_client()
            self.status_changed.emit(False, self._msg("coreDisconnected"))
            return

        self.is_running = True
        self.stats.reset()                    # statistics are per connection
        self.status_changed.emit(True, self._msg("coreConnected", link=self._describe()))
        self.log_msg.emit("SYS", self._msg("coreLinkUp", sid=self.slave_id))

        poll_idx = 0
        fail_streak = 0   # подряд неудачных опросов
        next_cycle = 0.0  # monotonic-дедлайн следующего цикла опроса (0 = сразу)

        while self.is_running:
            # 0. СИНХРОННЫЕ ОПЕРАЦИИ МАКРОСОВ (высший приоритет)
            if not self.op_queue.empty():
                self._execute_op(self.op_queue.get())
                continue

            # 0b. СЫРЫЕ КАДРЫ ИЗ КОНСОЛИ (интерактивные — сразу после макросов)
            if not self.raw_queue.empty():
                self._execute_raw(self.raw_queue.get())
                time.sleep(self.interframe)
                continue

            # 1. ПРОВЕРЯЕМ ОЧЕРЕДЬ ЗАПИСИ
            if not self.write_queue.empty():
                cmd = self.write_queue.get()
                self._execute_write(cmd["addr"], cmd["type"], cmd["value"])
                time.sleep(self.interframe)
                continue

            # 2. ПРОВЕРЯЕМ ОЧЕРЕДЬ ЧТЕНИЯ БОЛЬШИХ МАССИВОВ (ЧАНКИ)
            if not self.array_read_queue.empty():
                task = self.array_read_queue.get()
                self._execute_chunked_read(task["addr"], task["length"])
                time.sleep(self.interframe)
                continue

            # 3. ЦИКЛИЧЕСКИЙ ОПРОС ДАШБОРДА
            # Каденс: регистры цикла читаются подряд; после полного круга
            # следующий начинается не раньше чем через poll_interval (настройка
            # «Период опроса»). Очереди при этом дренируются каждый тик.
            # Snapshot the list: update_profile() (GUI thread) may swap it for a
            # shorter one between iterations, so clamp the index against THIS
            # snapshot to avoid an IndexError.
            pl = self.poll_list
            if pl and time.monotonic() >= next_cycle:
                poll_idx %= len(pl)
                reg = pl[poll_idx]
                ok = self._execute_read(datatypes.reg_key(reg), reg["type"],
                                        datatypes.reg_read_count(reg))
                if ok is None:
                    # Нет ответа / таймаут — считаем подряд идущие сбои.
                    fail_streak += 1
                    if fail_streak >= self.retries:
                        if not self._handle_connection_lost():
                            break  # остановка, требуется ручное подключение
                        fail_streak = 0  # тихо переподключились — продолжаем
                else:
                    # ok=True (валидный ответ) или ok=False (исключение Modbus,
                    # но связь жива) — сбрасываем счётчик.
                    fail_streak = 0
                poll_idx += 1
                if poll_idx >= len(pl):
                    poll_idx = 0
                    next_cycle = time.monotonic() + self.poll_interval

            time.sleep(0.03)

        self.is_running = False
        self._close_client()
        self._drain_queues()
        self.status_changed.emit(False, self._msg("coreDisconnected"))

    def _report_open_fail(self, kind: str, text: str):
        from core import linktest
        reason = linktest.why(kind, self.settings, text, self.t)
        self.log_msg.emit("ERR", self._msg("coreOpenFail", link=self._describe())
                          + (f" — {reason}" if reason else ""))
        self.open_failed.emit(kind, text)
        self.status_changed.emit(False, "")

    def _close_client(self):
        try:
            if self.client:
                self.client.close()
        except Exception:
            pass

    def _drain_queues(self):
        """Throw away everything still queued when the link goes down.

        * A macro/scanner blocked in request_op() gets an immediate error
          instead of sitting out its whole timeout (30 s for the scanner).
        * A WRITE queued before the disconnect must never fire on the next
          connect — possibly hours later, onto a device in a different state.
          In an industrial tool a stale write is worse than a lost one, so it
          is dropped and the operator is told.
        * A pending memory-area read reports an empty result, so the viewer
          re-enables its button instead of waiting forever."""
        while True:
            try:
                op = self.op_queue.get_nowait()
            except queue.Empty:
                break
            try:
                op["result"].put_nowait(("err", self._msg("coreCancelled")))
            except queue.Full:
                pass
        dropped = 0
        while True:
            try:
                self.write_queue.get_nowait()
                dropped += 1
            except queue.Empty:
                break
        if dropped:
            self.log_msg.emit("ERR", self._msg("coreWritesDropped", n=dropped))
        while True:
            try:
                self.raw_queue.get_nowait()
            except queue.Empty:
                break
        while True:
            try:
                task = self.array_read_queue.get_nowait()
            except queue.Empty:
                break
            self.array_read_finished.emit(task["addr"], [])

    def _handle_connection_lost(self):
        """Связь потеряна (подряд self.retries неудачных опросов).

        Возвращает False → поток должен остановиться (требуется нажать
        «Подключить» вручную). Возвращает True → удалось тихо переподключиться,
        опрос продолжается. Логирует ОДНУ строку, а не спам по каждому чтению.
        """
        if not self.auto_reconnect:
            self.log_msg.emit("ERR", self._msg("coreLostStop"))
            self.is_running = False
            return False

        self.log_msg.emit("ERR", self._msg("coreLostRetry"))
        while self.is_running:
            # Ждём интервал, оставаясь отзывчивыми к stop().
            slept = 0.0
            while self.is_running and slept < self.reconnect_interval:
                time.sleep(0.1)
                slept += 0.1
            if not self.is_running:
                return False
            self._close_client()
            try:
                self.client = self._make_client()
                if self.client.connect():
                    self.log_msg.emit("SYS", self._msg("coreRestored"))
                    self.status_changed.emit(
                        True, self._msg("coreReconnected", link=self._describe()))
                    return True
            except Exception:
                pass
        return False

    def stop(self):
        self._abort = True
        self.is_running = False

    # ── counted exchanges (line statistics) ───────────────────────────
    def _counted(self, fn, *args, **kwargs):
        """Run one request and record its outcome + response time.

        Response times are taken with perf_counter: on Windows the monotonic
        clock ticks every 15.6 ms, so a device answering in 3 ms showed as
        0 or 16 ms — the statistics and the link test were quantised."""
        t0 = time.perf_counter()
        try:
            res = fn(*args, **kwargs)
        except Exception:
            self.stats.record("timeout")           # the link failed (ModbusLinkError)
            raise
        outcome = linestats.classify(res)
        self.stats.record(outcome, time.perf_counter() - t0
                          if outcome in ("ok", "exception") else None)
        return res

    def _counted_read(self, addr, count, slave=None, area=None):
        return self._counted(self._safe_read, addr, count, slave=slave, area=area)

    def _find_reg(self, key):
        """The register dict with this KEY (area << 16 | addr), or None."""
        for reg in self.poll_list:
            if datatypes.reg_key(reg) == int(key):
                return reg
        return None

    # The client call per Modbus table (FC 03 / 04 / 01 / 02).
    _READERS = {"holding": "read_holding_registers",
                "input": "read_input_registers",
                "coil": "read_coils",
                "discrete": "read_discrete_inputs"}

    def _safe_read(self, addr, count, slave=None, area=None):
        sid = self.slave_id if slave is None else int(slave)
        area = area or datatypes.AREAS[datatypes.DEFAULT_AREA]
        fn = getattr(self.client, self._READERS[area.key])
        res = fn(address=addr, count=count, device_id=sid)
        if area.bits and res is not None and not res.isError():
            # The rest of the app reads one 0/1 "word" per coil.
            res.registers = [1 if b else 0 for b in list(res.bits)[:count]]
        return res

    def _safe_write_coil(self, addr, on: bool):
        return self.client.write_coil(address=addr, value=bool(on), device_id=self.slave_id)

    def _safe_write_single(self, addr, val):
        return self.client.write_register(address=addr, value=val, device_id=self.slave_id)

    # ==========================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ЛОГИРОВАНИЯ ФРЕЙМОВ
    # ==========================================
    @staticmethod
    def _crc16(data: bytes) -> bytes:
        """Вычисление Modbus RTU CRC16."""
        crc = 0xFFFF
        for b in data:
            crc ^= b
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return struct.pack('<H', crc)

    def _wire(self, body: bytes, tx: bool = True) -> bytes:
        """*body* (address + PDU) as it travels on the active link: RTU
        appends the CRC, Modbus TCP puts the MBAP header in front (with the
        transaction id the request carries / the answer came with)."""
        client = self.client
        if isinstance(client, TcpMaster):
            tid = client.next_tid() if tx else client._tid
            return mbap(tid, body[0], body[1:])
        return body + self._crc16(body)

    @staticmethod
    def _hex(data: bytes) -> str:
        """Форматирование байтов в HEX-строку."""
        return ' '.join(f'{b:02X}' for b in data)

    # Frame logging is cosmetic (a debug view); it must NEVER crash the poll
    # loop, so struct fields are masked to their width — an out-of-spec slave_id
    # (>255, hand-edited settings) or addr (>0xFFFF) can't raise struct.error.
    def _log_tx_read(self, addr, count, fc=0x03):
        """Логирование TX-фрейма чтения (FC01/02/03/04)."""
        pdu = struct.pack('>BBHH', self.slave_id & 0xFF, fc & 0xFF, addr & 0xFFFF, count & 0xFFFF)
        frame = self._wire(pdu)
        what = self._msg("coreUnitBit" if fc in (0x01, 0x02) else "coreUnitReg")
        self.log_msg.emit("TX", f"→ [{self._hex(frame)}]  " + self._msg(
            "coreFrameRead", fc=f"{fc:02X}", n=count, what=what, addr=f"0x{addr:04X}"))

    def _log_rx_read(self, registers, fc=0x03):
        """Логирование RX-фрейма: ответ на чтение."""
        if fc in (0x01, 0x02):               # bits packed LSB-first
            data = bytearray((len(registers) + 7) // 8)
            for i, b in enumerate(registers):
                if b:
                    data[i // 8] |= 1 << (i % 8)
            rx = struct.pack('>BBB', self.slave_id & 0xFF, fc, len(data)) + bytes(data)
            shown = ''.join('1' if b else '0' for b in registers)
        else:
            rx = struct.pack('>BBB', self.slave_id & 0xFF, fc, (len(registers) * 2) & 0xFF)
            for r in registers:
                rx += struct.pack('>H', r & 0xFFFF)
            shown = ' '.join(f'{r & 0xFFFF:04X}' for r in registers)
        last = getattr(self.client, "last_answer", b"")
        if isinstance(self.client, TcpMaster) and last:
            frame = bytes(last)          # the MBAP answer exactly as it came
        else:
            frame = self._wire(rx, tx=False)
        self.log_msg.emit("RX", f"← [{self._hex(frame)}]  "
                          + self._msg("coreFrameData", data=shown))

    def _log_tx_write(self, addr, value, fc=0x06):
        """Логирование TX-фрейма: FC06 Write Single Register / FC05 Coil."""
        pdu = struct.pack('>BBHH', self.slave_id & 0xFF, fc, addr & 0xFFFF, value & 0xFFFF)
        frame = self._wire(pdu)
        self.log_msg.emit("TX", f"→ [{self._hex(frame)}]  " + self._msg(
            "coreFrameWrite", fc=f"{fc:02X}", value=f"0x{value & 0xFFFF:04X}",
            addr=f"0x{addr:04X}"))

    def _log_rx_write(self, addr, value, fc=0x06):
        """Логирование RX-фрейма: эхо-ответ на FC06 / FC05."""
        pdu = struct.pack('>BBHH', self.slave_id & 0xFF, fc, addr & 0xFFFF, value & 0xFFFF)
        frame = self._wire(pdu, tx=False)
        self.log_msg.emit("RX", f"← [{self._hex(frame)}]  " + self._msg("coreFrameEcho"))

    # ==========================================
    # ВЫПОЛНЕНИЕ ОПЕРАЦИЙ ЧТЕНИЯ / ЗАПИСИ
    # ==========================================
    def _execute_read(self, addr, dtype, count=None):
        """Возвращает: True — валидный ответ; False — Modbus-исключение (связь
        жива, но регистр недоступен); None — нет ответа/таймаут (связь под
        вопросом, учитывается в счётчике потери соединения).

        ERR логируется только в verbose-режиме, чтобы не было спама на каждый
        неудачный опрос — потеря связи сообщается одной строкой в run().
        """
        key = int(addr)
        area, raw = datatypes.split_key(key)
        if count is None:
            count = datatypes.read_count(dtype)
        verbose = key in self.verbose_addrs
        if verbose:
            self._log_tx_read(raw, count, area.fc_read)
        try:
            res = self._counted_read(raw, count, area=area)
            if res is None or (hasattr(res, "isError") and res.isError()):
                if verbose:
                    self.log_msg.emit("ERR", self._msg("coreReadErr",
                                                       addr=datatypes.key_label(key)))
                # Modbus-исключение (прибор ответил кодом ошибки) → связь жива.
                # Anything else — no answer, a broken frame — counts towards
                # "connection lost".
                if res is not None and linestats.classify(res) == "exception":
                    return False
                return None
            if verbose:
                self._log_rx_read(res.registers, area.fc_read)
            self.data_updated.emit(key, datatypes.read_to_str(dtype, res.registers))
            return True
        except Exception as e:
            if verbose:
                self.log_msg.emit("ERR", self._msg("coreTimeout",
                                                   addr=datatypes.key_label(key), err=e))
            return None

    def _execute_chunked_read(self, start_addr, total_length):
        """Вычитывает большой массив из прибора чанками по 125 слов.
        *start_addr* — ключ регистра (область << 16 | адрес)."""
        area, first = datatypes.split_key(start_addr)
        self.log_msg.emit("SYS", self._msg("coreArrayStart",
                                           addr=datatypes.key_label(start_addr),
                                           n=total_length))
        full_buffer = []
        current_addr = first
        words_left = total_length

        MAX_CHUNK = 125  # Лимит Modbus RTU за один запрос

        try:
            while words_left > 0:
                count_to_read = min(words_left, MAX_CHUNK)
                self._log_tx_read(current_addr, count_to_read, area.fc_read)

                res = self._counted_read(current_addr, count_to_read, area=area)

                if res and not res.isError():
                    self._log_rx_read(res.registers, area.fc_read)
                    full_buffer.extend(res.registers)
                    words_left -= count_to_read
                    current_addr += count_to_read
                    time.sleep(self.interframe)  # пауза между чанками (настройка)
                else:
                    self.log_msg.emit("ERR", self._msg("coreChunkErr",
                                                       addr=f"0x{current_addr:04X}"))
                    self.array_read_finished.emit(start_addr, [])  # Отправляем пустой массив как флаг ошибки
                    return

            self.log_msg.emit("SYS", self._msg("coreArrayDone",
                                               addr=datatypes.key_label(start_addr),
                                               n=len(full_buffer)))
            # Отправляем готовый склеенный буфер в GUI
            self.array_read_finished.emit(start_addr, full_buffer)

        except Exception as e:
            self.log_msg.emit("ERR", self._msg("coreArrayFail", err=e))
            self.array_read_finished.emit(start_addr, [])

    def _execute_raw(self, frame: bytes):
        """Отправка сырого кадра (консоль) и чтение ответа до «тишины».

        Работает мимо разбора кадров клиента — кадр уходит как есть: в
        последовательный порт (или сокет преобразователя для «RTU по TCP»),
        а для Modbus TCP — в сокет, уже с заголовком MBAP, который собрала
        консоль. Длина ответа неизвестна (кадр может быть и мусорным, и
        чужого протокола), поэтому читаем всё, что приходит, пока линия не
        замолчит или не истечёт timeout; ответ Modbus TCP заканчивается там,
        где говорит его заголовок."""
        self.log_msg.emit("TX", f"→ [{self._hex(frame)}]  RAW · "
                          + self._msg("coreBytes", n=len(frame)))
        client = self.client
        if isinstance(client, TcpMaster):
            self._execute_raw_tcp(client, bytes(frame))
            return
        sock = getattr(client, "socket", None)
        if sock is None and getattr(client, "_opened", False):
            client.connect()                # a converter that dropped the link
            sock = client.socket
        if sock is None or not hasattr(sock, "in_waiting"):
            self.log_msg.emit("ERR", self._msg("coreRawNoPort"))
            return
        quiet = getattr(client, "quiet_s", 0.05)
        t0 = time.perf_counter()
        try:
            sock.reset_input_buffer()
            sock.write(bytes(frame))
            buf = bytearray()
            deadline = time.perf_counter() + self.timeout
            last_rx = 0.0
            while time.perf_counter() < deadline:
                n = sock.in_waiting
                if n:
                    buf += sock.read(n)
                    last_rx = time.perf_counter()
                elif buf and time.perf_counter() - last_rx > quiet:
                    break  # ответ пришёл и линия замолчала
                else:
                    time.sleep(0.005)
            if buf:
                self.log_msg.emit("RX", f"← [{self._hex(bytes(buf))}]  "
                                  + self._msg("coreBytes", n=len(buf)))
                # Raw frames may be anything — only a reply that is FRAMED
                # like Modbus (≥ 4 bytes) is judged by its CRC.
                from core.sniffer_core import frame_crc_ok
                good = len(buf) < 4 or frame_crc_ok(bytes(buf))
                exc = good and len(buf) >= 2 and buf[1] >= 0x80
                self.stats.record("exception" if exc else ("ok" if good else "crc"),
                                  last_rx - t0 if good else None)
            else:
                self.stats.record("timeout")
                self.log_msg.emit("ERR", self._msg("coreRawNoAnswer"))
        except Exception as e:
            self.stats.record("timeout")
            self.log_msg.emit("ERR", f"RAW: {e}")

    def _execute_raw_tcp(self, client, frame: bytes):
        """Raw console over Modbus TCP: *frame* already carries its MBAP
        header. The answer is complete when its header says so."""
        import socket as _socket
        t0 = time.perf_counter()
        try:
            sock = client._send(frame)
        except Exception as e:
            self.stats.record("timeout")
            self.log_msg.emit("ERR", f"RAW: {e}")
            return
        buf = bytearray()
        deadline = t0 + self.timeout
        last_rx = 0.0
        try:
            while time.perf_counter() < deadline:
                if len(buf) >= 6:
                    need = 6 + int.from_bytes(buf[4:6], "big")
                    if int.from_bytes(buf[2:4], "big") == 0 and len(buf) >= need:
                        break
                if buf and time.perf_counter() - last_rx > client.quiet_s:
                    break
                try:
                    sock.settimeout(0.02)
                    chunk = sock.recv(4096)
                except _socket.timeout:
                    continue
                if not chunk:
                    client.close()          # the device closed it; reopened next time
                    break
                buf += chunk
                last_rx = time.perf_counter()
        except OSError as e:
            client.close()
            self.log_msg.emit("ERR", f"RAW: {e}")
        if not buf:
            self.stats.record("timeout")
            self.log_msg.emit("ERR", self._msg("coreRawNoAnswer"))
            return
        self.log_msg.emit("RX", f"← [{self._hex(bytes(buf))}]  "
                          + self._msg("coreBytes", n=len(buf)))
        good = (len(buf) >= 8 and int.from_bytes(buf[2:4], "big") == 0
                and len(buf) == 6 + int.from_bytes(buf[4:6], "big"))
        exc = good and buf[7] >= 0x80
        self.stats.record("exception" if exc else ("ok" if good else "crc"),
                          last_rx - t0 if good else None)

    def _execute_write(self, addr, dtype, value_str) -> bool:
        """Write one value; True only when EVERY word was acknowledged.
        *addr* is the register KEY (area << 16 | address)."""
        key = int(addr)
        area, addr = datatypes.split_key(key)
        label = datatypes.key_label(key)
        try:
            if not area.writable:
                raise RuntimeError(self._msg("coreReadOnlyArea", addr=label))
            if area.bits:
                on = datatypes.encode(datatypes.BIT_TYPE, value_str)[0]
                wire = 0xFF00 if on else 0x0000
                self._log_tx_write(addr, wire, 0x05)
                res = self._counted(self._safe_write_coil, addr, bool(on))
                if res and not res.isError():
                    self._log_rx_write(addr, wire, 0x05)
                    self.log_msg.emit("SYS", self._msg("coreWriteOk", addr=label,
                                                       value=value_str))
                    return True
                self.log_msg.emit("ERR", self._msg("coreWriteUnconfirmed", bad=label,
                                                   addr=label, value=value_str))
                return False
            if datatypes.is_text(dtype):
                # A text field is written NUL-padded to its full length, so
                # an old longer value cannot survive past the new end.
                reg = self._find_reg(key)
                words = (datatypes.addr_span(reg) if reg else
                         max(1, (len(str(value_str).encode("cp1251", "replace")) + 1) // 2))
                regs = datatypes.encode(dtype, str(value_str), words)
            else:
                # No float() here: an INT64 above 2**53 must arrive exact.
                regs = datatypes.encode(dtype, str(value_str).strip().replace(",", "."))
            if not regs:
                raise RuntimeError(self._msg("coreNotWritable", type=dtype))
            # Write each 16-bit word sequentially; pause between words on
            # multi-register types (matches the original FLOAT/LONG behavior).
            failed = []
            for i, word in enumerate(regs):
                if i:
                    time.sleep(self.interframe)
                self._log_tx_write(addr + i, word)
                res = self._counted(self._safe_write_single, addr + i, word)
                if res and not res.isError():
                    self._log_rx_write(addr + i, word)
                else:
                    failed.append(addr + i)
            # Honest outcome: never report success when the device refused or
            # didn't acknowledge a word (the operator must know the write failed).
            if failed:
                bad = ", ".join(f"0x{a:04X}" for a in failed)
                self.log_msg.emit("ERR", self._msg("coreWriteUnconfirmed", bad=bad,
                                                   addr=label, value=value_str))
                return False
            self.log_msg.emit("SYS", self._msg("coreWriteOk", addr=label,
                                               value=value_str))
            return True
        except Exception as e:
            self.log_msg.emit("ERR", self._msg("coreWriteErr", addr=label, err=e))
            return False
