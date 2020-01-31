import socket
import ftp_conn
import config
import server
import tests

config = config.Configuration()

if config.mode == 'server':
    server.run(config)
elif config.mode == 'tests':
    tests.run(config)
