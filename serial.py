import os
import socket
import struct
import sys
import threading
import time
from typing import Union


class MameSerial:
    """
    Interface serial estilo Arduino/ESP32 sobre socket TCP para o MAME
    (-rs232a null_modem -bitb socket.127.0.0.1:4000).
    """

    def __init__(self, line_ending: str = "\r\n", timeout: float = 1.0):
        self.line_ending = line_ending
        self.timeout = timeout  # Equivalente ao Serial.setTimeout() (em segundos)

        self._sock: socket.socket | None = None
        self._server_sock: socket.socket | None = None
        self._rx_buffer = bytearray()
        self._lock = threading.Lock()
        self._running = False
        self._rx_thread: threading.Thread | None = None

    @property
    def is_connected(self) -> bool:
        """Indica se a conexão TCP com o MAME está ativa."""
        return self._running and self._sock is not None

    def begin(self, host: str = "127.0.0.1", port: int = 4000) -> None:
        """Abre a conexão com o MAME (inicie este script antes do MAME)."""
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            client.connect((host, port))
            self._sock = client
            print(f"[Serial] Conectado ao MAME em {host}:{port}")
        except ConnectionRefusedError:
            client.close()
            self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_sock.bind((host, port))
            self._server_sock.listen(1)
            print(f"[Serial] Aguardando o MAME conectar em {host}:{port}...")
            conn, addr = self._server_sock.accept()
            self._sock = conn
            print(f"[Serial] MAME conectado ({addr[0]}:{addr[1]})")

        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._running = True
        self._rx_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._rx_thread.start()

    def _receive_loop(self) -> None:
        """Thread em segundo plano que alimenta o buffer RX."""
        while self._running and self._sock:
            try:
                data = self._sock.recv(1024)
                if not data:
                    print("\n[Serial] Conexão encerrada pelo MAME.")
                    self._running = False
                    break
                with self._lock:
                    self._rx_buffer.extend(data)
            except OSError as e:
                if self._running:
                    print(f"\n[Serial] Erro de socket com o MAME: {e}")
                self._running = False
                break

    def setTimeout(self, timeout_ms: int) -> None:
        """Define o timeout de leitura em milissegundos."""
        self.timeout = timeout_ms / 1000.0

    # --- Escrita (TX) ---

    def write(self, data: Union[int, bytes, bytearray, str]) -> int:
        """Envia 1 byte (0-255) ou uma sequência de bytes brutos."""
        if not self._sock or not self._running:
            return 0
        if isinstance(data, int):
            payload = bytes([data & 0xFF])
        elif isinstance(data, str):
            payload = data.encode("latin-1")
        else:
            payload = bytes(data)

        self._sock.sendall(payload)
        return len(payload)

    def print(self, data: Union[str, int, float]) -> int:
        """Envia texto ou número sem quebra de linha (Serial.print)."""
        return self.write(str(data))

    def println(self, data: Union[str, int, float] = "") -> int:
        """Envia texto ou número com quebra de linha (Serial.println)."""
        return self.write(f"{data}{self.line_ending}")

    # --- Leitura (RX) ---

    def available(self) -> int:
        """Retorna quantos bytes estão disponíveis no buffer RX (Serial.available)."""
        with self._lock:
            return len(self._rx_buffer)

    def read(self) -> int:
        """Lê e remove 1 byte do buffer (0-255), ou retorna -1 se vazio (Serial.read)."""
        with self._lock:
            if not self._rx_buffer:
                return -1
            byte = self._rx_buffer[0]
            del self._rx_buffer[0]
            return byte

    def peek(self) -> int:
        """Retorna o próximo byte sem removê-lo do buffer, ou -1 se vazio (Serial.peek)."""
        with self._lock:
            return self._rx_buffer[0] if self._rx_buffer else -1

    def readBytes(self, length: int) -> bytes:
        """Lê até `length` bytes respeitando o timeout (Serial.readBytes)."""
        deadline = time.monotonic() + self.timeout
        result = bytearray()

        while len(result) < length and time.monotonic() < deadline:
            with self._lock:
                if self._rx_buffer:
                    take = min(length - len(result), len(self._rx_buffer))
                    result.extend(self._rx_buffer[:take])
                    del self._rx_buffer[:take]
                    continue
            time.sleep(0.001)

        return bytes(result)

    def readString(self) -> str:
        """Lê todos os dados que chegarem até expirar o timeout (Serial.readString)."""
        deadline = time.monotonic() + self.timeout
        result = bytearray()

        while time.monotonic() < deadline:
            with self._lock:
                if self._rx_buffer:
                    result.extend(self._rx_buffer)
                    self._rx_buffer.clear()
                    deadline = time.monotonic() + min(self.timeout, 0.05)
            time.sleep(0.002)

        return result.decode("latin-1")

    def readStringUntil(self, terminator: str = "\n") -> str:
        """Lê até encontrar o delimitador ou atingir o timeout (Serial.readStringUntil)."""
        term_byte = terminator.encode("latin-1")[0]
        deadline = time.monotonic() + self.timeout
        result = bytearray()

        while time.monotonic() < deadline:
            with self._lock:
                if self._rx_buffer:
                    idx = self._rx_buffer.find(term_byte)
                    if idx != -1:
                        result.extend(self._rx_buffer[:idx])
                        del self._rx_buffer[: idx + 1]
                        return result.decode("latin-1")
                    result.extend(self._rx_buffer)
                    self._rx_buffer.clear()
            time.sleep(0.002)

        return result.decode("latin-1")

    def flush(self) -> None:
        """Descarta bytes pendentes no buffer RX."""
        with self._lock:
            self._rx_buffer.clear()

    def close(self) -> None:
        """Fecha a conexão serial."""
        self._running = False
        for s in (self._sock, self._server_sock):
            if s:
                try:
                    s.close()
                except OSError:
                    pass


def prepare_payload(bin_path: str) -> bytes:
    """Lê o .bin (máx. 32 KB) e garante a condição de parada do bootloader."""
    if not os.path.isfile(bin_path):
        raise FileNotFoundError(f"Arquivo não encontrado: {bin_path}")

    with open(bin_path, "rb") as f:
        payload = bytearray(f.read())

    if len(payload) > 0x8000:
        raise ValueError(f"Arquivo excede 32768 bytes ({len(payload)} bytes).")

    magic = b"\xDE\xAD\xBE\xEF"
    if len(payload) < 0x8000 and not payload.endswith(magic):
        if len(payload) <= 0x8000 - 4:
            payload.extend(magic)
        else:
            payload.extend(b"\x00" * (0x8000 - len(payload)))

    return bytes(payload)


def wait_for_banner(serial_port: MameSerial, banner: bytes = b"\x10/boot.bin", timeout_s: float = 10.0) -> bool:
    """Aguarda a string inicial enviada pelo bootloader Z80."""
    deadline = time.monotonic() + timeout_s
    rx_stream = bytearray()

    while time.monotonic() < deadline:
        if serial_port.available() > 0:
            rx_stream.append(serial_port.read())
            if rx_stream.endswith(banner):
                return True
        else:
            time.sleep(0.002)

    print(f"[Erro] Timeout aguardando banner. Recebido: {bytes(rx_stream)!r}")
    return False


def upload_binary(serial_port: MameSerial, payload: bytes) -> None:
    """Envia cada byte no formato [N_low, N_high, Data] e valida o eco de 3 bytes."""
    total = len(payload)
    t0 = time.monotonic()

    for offset, byte_val in enumerate(payload):
        packet = struct.pack("<HB", offset, byte_val)
        serial_port.write(packet)

        is_last = (offset == total - 1)
        if not is_last:
            echo = serial_port.readBytes(3)
            if echo != packet:
                raise RuntimeError(
                    f"Falha de eco no offset 0x{offset:04X}: "
                    f"enviado {packet.hex(' ')}, recebido {echo.hex(' ')}"
                )
        else:
            # No último byte (0xEF ou offset 0x7FFF), o bootloader salta para $8000
            # e o Channel Reset ($18) da SIO interrompe o eco final, gerando lixo (ex: 0xF8).
            time.sleep(0.02)
            serial_port.flush()

        if (offset + 1) % 256 == 0 or is_last:
            pct = ((offset + 1) * 100) // total
            print(f"\r[Bootloader] Enviando: {offset + 1}/{total} bytes ({pct}%)", end="", flush=True)

    elapsed = time.monotonic() - t0
    print(f"\n[Bootloader] Concluído em {elapsed:.2f}s! Z80 executando a partir de $8000.")

def serial_terminal(serial_port: MameSerial) -> None:
    """
    Modo terminal interativo:
    - Exibe em tempo real tudo o que chega pela serial (RX).
    - Envia cada linha digitada quando Enter é pressionado (TX).
    """
    stop_event = threading.Event()

    def rx_printer() -> None:
        while not stop_event.is_set() and serial_port.is_connected:
            avail = serial_port.available()
            if avail > 0:
                data = serial_port.readBytes(avail)
                sys.stdout.write(data.decode("latin-1", errors="replace"))
                sys.stdout.flush()
            else:
                time.sleep(0.005)

    rx_thread = threading.Thread(target=rx_printer, daemon=True)
    rx_thread.start()

    print("[Terminal] Conectado. Digite e pressione Enter para enviar (Ctrl+C para sair):\n", flush=True)

    try:
        while serial_port.is_connected:
            try:
                line = input()
            except EOFError:
                print("\n[Terminal] Entrada de teclado indisponível (EOF). Mantendo apenas leitura RX...", flush=True)
                while serial_port.is_connected:
                    time.sleep(0.1)
                break

            if not serial_port.is_connected:
                break

            serial_port.println(line)
    finally:
        stop_event.set()
        rx_thread.join(timeout=0.2)


if __name__ == "__main__":
    bin_file = sys.argv[1] if len(sys.argv) > 1 else "boot.bin"
    payload = prepare_payload(bin_file)

    Serial = MameSerial(line_ending="\r\n")
    Serial.begin("127.0.0.1", 4000)
    Serial.setTimeout(2000)

    try:
        print("[Bootloader] Aguardando banner 10h + '/boot.bin' do Z80...")
        if not wait_for_banner(Serial, b"\x10/boot.bin", timeout_s=15.0):
            sys.exit(1)

        print("[Bootloader] Banner recebido! Iniciando upload...")
        upload_binary(Serial, payload)

        serial_terminal(Serial)

    except KeyboardInterrupt:
        print("\n[Terminal] Encerrado pelo usuário.")
    except Exception as e:
        print(f"\n[Erro] Falha durante a execução: {e}")
        raise
    finally:
        Serial.close()
