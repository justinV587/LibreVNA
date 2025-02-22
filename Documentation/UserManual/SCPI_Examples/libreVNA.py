import re
import socket
from asyncio import IncompleteReadError  # only import the exception class
import time

class SocketStreamReader:
    def __init__(self, sock: socket.socket, default_timeout=1):
        self._sock = sock
        self._sock.setblocking(0)
        self._recv_buffer = bytearray()
        self.default_timeout = default_timeout

    def read(self, num_bytes: int = -1) -> bytes:
        raise NotImplementedError

    def readexactly(self, num_bytes: int) -> bytes:
        buf = bytearray(num_bytes)
        pos = 0
        while pos < num_bytes:
            n = self._recv_into(memoryview(buf)[pos:])
            if n == 0:
                raise IncompleteReadError(bytes(buf[:pos]), num_bytes)
            pos += n
        return bytes(buf)

    def readline(self, timeout=None) -> bytes:
        return self.readuntil(b"\n", timeout=timeout)

    def readuntil(self, separator: bytes = b"\n", timeout=None) -> bytes:
        if len(separator) != 1:
            raise ValueError("Only separators of length 1 are supported.")
        if timeout is None:
            timeout = self.default_timeout

        chunk = bytearray(4096)
        start = 0
        buf = bytearray(len(self._recv_buffer))
        bytes_read = self._recv_into(memoryview(buf))
        assert bytes_read == len(buf)

        time_limit = time.time() + timeout
        while True:
            idx = buf.find(separator, start)
            if idx != -1:
                break
            elif time.time() > time_limit:
                raise Exception("Timed out waiting for response from GUI")

            start = len(self._recv_buffer)
            bytes_read = self._recv_into(memoryview(chunk))
            buf += memoryview(chunk)[:bytes_read]

        result = bytes(buf[: idx + 1])
        self._recv_buffer = b"".join(
            (memoryview(buf)[idx + 1 :], self._recv_buffer)
        )
        return result

    def _recv_into(self, view: memoryview) -> int:
        bytes_read = min(len(view), len(self._recv_buffer))
        view[:bytes_read] = self._recv_buffer[:bytes_read]
        self._recv_buffer = self._recv_buffer[bytes_read:]
        if bytes_read == len(view):
            return bytes_read
        try:
            bytes_read += self._sock.recv_into(view[bytes_read:], 0)
        except:
            pass
        return bytes_read

class libreVNA:
    def __init__(self, host='localhost', port=19542,
                 check_cmds=True, timeout=1):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.connect((host, port))
        except:
            raise Exception("Unable to connect to LibreVNA-GUI. Make sure it is running and the TCP server is enabled.")
        self.reader = SocketStreamReader(self.sock,
                                         default_timeout=timeout)
        self.default_check_cmds = check_cmds

    def __del__(self):
        self.sock.close()

    def __read_response(self, timeout=None):
        return self.reader.readline(timeout=timeout).decode().rstrip()

    def cmd(self, cmd, check=None, timeout=None):
        self.sock.sendall(cmd.encode())
        self.sock.send(b"\n")
        if check or (check is None and self.default_check_cmds):
            status = self.get_status(timeout=timeout)
            if status & 0x20:
                raise Exception("Command Error")
            if status & 0x10:
                raise Exception("Execution Error")
            if status & 0x08:
                raise Exception("Device Error")
            if status & 0x04:
                raise Exception("Query Error")
            return status
        else:
            return None

    def query(self, query, timeout=None):
        self.sock.sendall(query.encode())
        self.sock.send(b"\n")
        return self.__read_response(timeout=timeout)

    def get_status(self, timeout=None):
        resp = self.query("*ESR?", timeout=timeout)
        if not re.match(r'^\d+$', resp):
            raise Exception("Expected numeric response from *ESR? but got "
                            f"'{resp}'")
        status = int(resp)
        if status < 0 or status > 255:
            raise Exception(f"*ESR? returned invalid value {status}.")
        return status
    
    @staticmethod
    def parse_VNA_trace_data(data):
        ret = []
        # Remove brackets (order of data implicitly known)
        data = data.replace(']','').replace('[','')
        values = data.split(',')
        if int(len(values) / 3) * 3 != len(values):
            # number of values must be a multiple of three (frequency, real, imaginary)
            raise Exception("Invalid input data: expected tuples of three values each")
        for i in range(0, len(values), 3):
            freq = float(values[i])
            real = float(values[i+1])
            imag = float(values[i+2])
            ret.append((freq, complex(real, imag)))
        return ret
    
    @staticmethod
    def parse_SA_trace_data(data):
        ret = []
        # Remove brackets (order of data implicitly known)
        data = data.replace(']','').replace('[','')
        values = data.split(',')
        if int(len(values) / 2) * 2 != len(values):
            # number of values must be a multiple of two (frequency, dBm)
            raise Exception("Invalid input data: expected tuples of two values each")
        for i in range(0, len(values), 2):
            freq = float(values[i])
            dBm = float(values[i+1])
            ret.append((freq, dBm))
        return ret

