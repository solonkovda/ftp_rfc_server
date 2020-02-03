import socket
import enum
import pathlib
import os
import hashlib
import data_processing

READY_FOR_NEW_USER = b"220 (solonkovda's ftp)"
USER_LOGGED_IN = b'220 User logged in, proceed'
SYST_RESPONSE = b'215 UNIX Type: L8'
QUIT_RESPONSE = b'221 Goodbye.'


class FtpConnection(object):
    class Type(enum.Enum):
        ASCII = 1

    def __init__(self, config, conn: socket.socket, addr):
        self.config = config
        self.conn = conn
        self.conn_addr = addr
        self.buffer = None
        self.buffer_offset = 0
        self.user = ''
        self.logged_in = False
        self.type = FtpConnection.Type.ASCII
        self.addr = None
        self.root_dir = pathlib.Path(config.root_dir).resolve().absolute()
        self.cwd = self.root_dir
        self.passive_sock = None
        self.mode = 'S'

    def initial_setup(self):
        self.conn.settimeout(60)
        self._send_message(READY_FOR_NEW_USER)

    def _send_message(self, message):
        self.conn.sendall(message + b'\r\n')

    def _get_byte(self):
        if self.buffer is None or self.buffer_offset == len(self.buffer):
            self.buffer = self.conn.recv(4096)
            if len(self.buffer) == 0:
                raise socket.timeout()
            self.buffer_offset = 0
        result = self.buffer[self.buffer_offset]
        self.buffer_offset += 1
        return result

    def _read_command(self):
        line = ''
        while len(line) < 2 or line[-2] != '\r' or line[-1] != '\n':
            line += chr(self._get_byte())
        line = line[:-2]
        if ' ' in line:
            command, arg = line.split(' ', 1)
        else:
            command = line
            arg = ''
        return command, arg

    def _close_passive(self):
        if self.passive_sock:
            self.passive_sock.close()
            self.passive_sock = None

    def _prepare_data(self, data):
        if self.mode == 'S':
            return data
        if self.mode == 'B':
            return data_processing.data_to_block(data)
        if self.mode == 'C':
            return data_processing.data_to_compress(data)

    def _unpack_data(self, data):
        if self.mode == 'S':
            return data
        if self.mode == 'B':
            return data_processing.data_from_block(data)
        if self.mode == 'C':
            return data_processing.data_from_compress(data)

    def _send_bytes_to_data_conn(self, data):
        if self.passive_sock:
            sock, _ = self.passive_sock.accept()
        else:
            sock = socket.socket()
            sock.connect(self.addr)
        data = self._prepare_data(data)
        sock.settimeout(60)
        sock.sendall(data)
        sock.shutdown(socket.SHUT_RDWR)
        sock.close()
        self._close_passive()

    def _recv_bytes_from_data_conn(self):
        if self.passive_sock:
            sock, _ = self.passive_sock.accept()
        else:
            sock = socket.socket()
            sock.connect(self.addr)
        sock.settimeout(60)
        data = bytearray()
        while True:
            tmp = sock.recv(4096)
            if len(tmp) == 0:
                break
            data += tmp
        sock.shutdown(socket.SHUT_RDWR)
        sock.close()
        self._close_passive()
        data = self._unpack_data(data)
        return data

    def _resolve_path(self, path):
        if path and path[0] == '/':
            path = self.root_dir / path[1:]
        new_path = self.cwd / path
        new_path = new_path.resolve().absolute()
        if not self.root_dir in new_path.parents and self.root_dir != new_path:
            return False, None
        return True, new_path

    def user_command(self, arg):
        self.user = arg
        if self.user == 'anonymous' or not self.config.auth_enabled:
            # Deviation from the RFC per homework request.
            self.logged_in = True
            self._send_message(b'230 User logged in, proceed')
            return
        self._send_message(b'331 Need password')

    def syst_command(self, arg):
        self._send_message(SYST_RESPONSE)

    def quit_command(self, arg):
        self._send_message(QUIT_RESPONSE)

    def type_command(self, arg):
        if arg[0] == 'A' or arg[0] == 'I':
            self._send_message(b'200 Switching to ASCII mode')
            self.type = FtpConnection.Type.ASCII
        else:
            self._send_message(b'500 Unrecognised TYPE command.')

    def port_command(self, arg):
        self._close_passive()
        ok = True
        try:
            arr = arg.split(',')
            ip = '.'.join(arr[:4])
            port = int(arr[4]) * 256 + int(arr[5])
            if ip != self.conn_addr[0]:
                ok = False
            else:
                self.addr = (ip, port)
        except TimeoutError:
            ok = False
        finally:
            if ok:
                self._send_message(b'200 PORT command successful')
            else:
                self._send_message(b'500 Illegal PORT command')

    def retr_command(self, arg):
        ok, path = self._resolve_path(arg)
        if not ok or not path.is_file():
            self._send_message(b'550 Invalid filepath')
            return
        self._send_message(b'150 Opening data connection')
        with open(path, 'rb') as f:
            data = f.read()
        self._send_bytes_to_data_conn(data)
        self._send_message(b'226 RETR done')

    def stor_command(self, arg, mode='wb'):
        ok, path = self._resolve_path(arg)
        if not ok or not path.parent.is_dir():
            self._send_message(b'550 Invalid filepath')
            return
        self._send_message(b'150 Opening data connection')
        data = self._recv_bytes_from_data_conn()
        with open(path, mode) as f:
            f.write(data)
        self._send_message(b'226 STOR DONE')

    def noop_command(self, arg):
        self._send_message(b'200 NOOP ok')

    def stru_command(self, arg):
        if arg != 'F':
            self._send_message(b'500 Invalid STRU command')
        else:
            self._send_message(b'200 Struct set to file')

    def cwd_command(self, arg):
        ok, new_path = self._resolve_path(arg)
        if not ok or not new_path.exists() or not new_path.is_dir():
            self._send_message(b'550 Invalid directory')
            return
        self.cwd = new_path
        self._send_message(b'250 Directory changed')

    def dele_command(self, arg):
        ok, path = self._resolve_path(arg)
        if not ok or not path.is_file():
            self._send_message(b'550 Invalid filepath')
            return
        os.remove(path)
        self._send_message(b'250 DELE done')

    def rmd_command(self, arg):
        ok, path = self._resolve_path(arg)
        if not ok or not path.is_dir():
            self._send_message(b'550 Invalid filepath')
            return
        try:
            os.rmdir(path)
        except:
            self._send_message(b'550 Unable to delete directory')
            return
        self._send_message(b'226 RMD done')

    def mkd_command(self, arg):
        ok, path = self._resolve_path(arg)
        if not ok or path.exists() or not path.parent.is_dir():
            self._send_message(b'550 Invalid filepath')
            return
        os.mkdir(path)
        self._send_message(b'226 MKD done')

    def nlst_command(self, arg):
        ok, path = self._resolve_path(arg)
        if not ok or not path.is_dir():
            self._send_message(b'550 Invalid filepath')
            return
        files = os.listdir(path)
        data = ('\r\n'.join(files) + '\r\n').encode('ascii')
        self._send_message(b'150 Opening data connection')
        self._send_bytes_to_data_conn(data)
        self._send_message(b'226 NLST done')

    def pasv_command(self, arg):
        self._close_passive()
        ip = socket.gethostbyname(socket.gethostname())
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((ip, 0))
        sock.listen(1)
        self.passive_sock = sock
        port = sock.getsockname()[1]

        text = ip.replace('.', ',')
        message = '227 Entering Passive Mode (%s,%d,%d)' % (
            text, port // 256, port % 256)
        self._send_message(message.encode())

    def pass_command(self, arg):
        if self.user not in self.config.users or self.config.users[self.user] != arg:
            self._send_message(b'530 Wrong username or password')
            return
        self._send_message(b'230 User logged in, proceed')
        self.logged_in = True

    def mode_command(self, arg):
        if arg == 'S':
            self._send_message(b'200 Mode set to stream')
            self.mode = arg
        elif arg == 'B':
            self._send_message(b'200 Mode set to block')
            self.mode = arg
        elif arg == 'C':
            self._send_message(b'200 Mode set to compressed')
            self.mode = arg
        else:
            self._send_message(b'500 Invalid mode')

    def command_loop(self):
        while True:
            command, arg = self._read_command()
            command = command.lower()
            if command == 'user':
                self.user_command(arg)
            elif command == 'pass':
                self.pass_command(arg)
            # Everything below requires authentication.
            elif not self.logged_in:
                self._send_message(b'530 Not logged in')
            elif command == 'syst':
                self.syst_command(arg)
            elif command == 'quit':
                self.quit_command(arg)
                break
            elif command == 'type':
                self.type_command(arg)
            elif command == 'port':
                self.port_command(arg)
            elif command == 'retr':
                self.retr_command(arg)
            elif command == 'stor':
                self.stor_command(arg)
            elif command == 'noop':
                self.noop_command(arg)
            elif command == 'mode':
                self.mode_command(arg)
            elif command == 'stru':
                self.stru_command(arg)
            elif command == 'cdup':
                self.cwd_command('..')
            elif command == 'cwd':
                self.cwd_command(arg)
            elif command == 'appe':
                self.stor_command(arg, 'ab')
            elif command == 'dele':
                self.dele_command(arg)
            elif command == 'rmd':
                self.rmd_command(arg)
            elif command == 'mkd':
                self.mkd_command(arg)
            elif command == 'nlst':
                self.nlst_command(arg)
            elif command == 'pasv':
                self.pasv_command(arg)
            elif command == 'mode':
                self.mode_command(arg)
            else:
                self._send_message('500 Unknown command\n')

    def handle(self):
        try:
            self.initial_setup()
            self.command_loop()
        except socket.timeout:
            pass
        except Exception:
            pass
        finally:
            self.conn.shutdown(socket.SHUT_RDWR)
            self.conn.close()
            self._close_passive()
