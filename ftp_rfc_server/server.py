import socket
import ftp_conn


def run(config):
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    sock.bind((config.host, config.port))
    sock.listen(5)
    while True:
        ftp = ftp_conn.FtpConnection(config, *sock.accept())
        ftp.handle()
