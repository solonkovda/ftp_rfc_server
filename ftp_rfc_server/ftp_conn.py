import socket
import enum
import pathlib
import os
import hashlib
import data_processing

READY_FOR_NEW_USER = b"220 (solonkovda's ftp)\r\n"
USER_LOGGED_IN = b'220 User logged in, proceed\r\n'
SYST_RESPONSE = b'215 UNIX Type: L8\r\n'
QUIT_RESPONSE = b'221 Goodbye.\r\n'


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
        self.cwd = pathlib.Path.cwd()
        self.passive_sock = None
        self.mode = 'S'

    def initial_setup(self):
        self.conn.settimeout(60)
        self.conn.sendall(READY_FOR_NEW_USER)

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
            self.conn.sendall(b'230 User logged in, proceed\r\n')
            return
        self.conn.sendall(b'331 Need password\r\n')

    def syst_command(self, arg):
        self.conn.sendall(SYST_RESPONSE)

    def quit_command(self, arg):
        self.conn.sendall(QUIT_RESPONSE)

    def type_command(self, arg):
        if arg[0] == 'A' or arg[0] == 'I':
            self.conn.sendall(b'200 Switching to ASCII mode\r\n')
            self.type = FtpConnection.Type.ASCII
        else:
            self.conn.sendall(b'500 Unrecognised TYPE command.\r\n')

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
                self.conn.sendall(b'200 PORT command successful\r\n')
            else:
                self.conn.sendall(b'500 Illegal PORT command\r\n')

    def retr_command(self, arg):
        ok, path = self._resolve_path(arg)
        if not ok or not path.is_file():
            self.conn.sendall(b'550 Invalid filepath\r\n')
            return
        self.conn.sendall(b'150 Opening data connection\r\n')
        with open(path, 'rb') as f:
            data = f.read()
        self._send_bytes_to_data_conn(data)
        self.conn.sendall(b'226 RETR done\r\n')

    def stor_command(self, arg, mode='wb'):
        ok, path = self._resolve_path(arg)
        if not ok or not path.parent.is_dir():
            self.conn.sendall(b'550 Invalid filepath\r\n')
            return
        self.conn.sendall(b'150 Opening data connection\r\n')
        data = self._recv_bytes_from_data_conn()
        with open(path, mode) as f:
            f.write(data)
        self.conn.sendall(b'226 STOR DONE\r\n')

    def noop_command(self, arg):
        self.conn.sendall(b'200 NOOP ok\r\n')

    def stru_command(self, arg):
        if arg != 'F':
            self.conn.sendall(b'500 Invalid STRU command\r\n')
        else:
            self.conn.sendall(b'200 Struct set to file\r\n')

    def cwd_command(self, arg):
        ok, new_path = self._resolve_path(arg)
        if not ok or not new_path.exists() or not new_path.is_dir():
            self.conn.sendall(b'550 Invalid directory\r\n')
            return
        self.cwd = new_path
        self.conn.sendall(b'250 Directory changed\r\n')

    def dele_command(self, arg):
        ok, path = self._resolve_path(arg)
        if not ok or not path.is_file():
            self.conn.sendall(b'550 Invalid filepath\r\n')
            return
        os.remove(path)
        self.conn.sendall(b'250 DELE done\r\n')

    def rmd_command(self, arg):
        ok, path = self._resolve_path(arg)
        if not ok or not path.is_dir():
            self.conn.sendall(b'550 Invalid filepath\r\n')
            return
        try:
            os.rmdir(path)
        except:
            self.conn.sendall(b'550 Unable to delete directory\r\n')
            return
        self.conn.sendall(b'226 RMD done\r\n')

    def mkd_command(self, arg):
        ok, path = self._resolve_path(arg)
        if not ok or path.exists() or not path.parent.is_dir():
            self.conn.sendall(b'550 Invalid filepath\r\n')
            return
        os.mkdir(path)
        self.conn.sendall(b'226 MKD done\r\n')

    def nlst_command(self, arg):
        ok, path = self._resolve_path(arg)
        if not ok or not path.is_dir():
            self.conn.sendall(b'550 Invalid filepath\r\n')
            return
        files = os.listdir(path)
        data = ('\r\n'.join(files) + '\r\n').encode('ascii')
        self.conn.sendall(b'150 Opening data connection\r\n')
        self._send_bytes_to_data_conn(data)
        self.conn.sendall(b'226 NLST done\r\n')

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
        message = '227 Entering Passive Mode (%s,%d,%d)\r\n' % (
            text, port // 256, port % 256)
        self.conn.sendall(message.encode())

    def pass_command(self, arg):
        if self.user not in self.config.users or self.config.users[self.user] != arg:
            self.conn.sendall(b'530 Wrong username or password\r\n')
            return
        self.conn.sendall(b'230 User logged in, proceed\r\n')
        self.logged_in = True

    def mode_command(self, arg):
        if arg == 'S':
            self.conn.sendall(b'200 Mode set to stream\r\n')
            self.mode = arg
        elif arg == 'B':
            self.conn.sendall(b'200 Mode set to block\r\n')
            self.mode = arg
        elif arg == 'C':
            self.conn.sendall(b'200 Mode set to compressed\r\n')
            self.mode = arg
        else:
            self.conn.sendall(b'500 Invalid mode\r\n')

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
                self.conn.sendall(b'530 Not logged in\r\n')
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
