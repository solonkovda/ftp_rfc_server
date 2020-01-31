import hashlib
import os


class Configuration:
    def __init__(self):
        self.mode = os.environ.get('HW1_MODE', 'server')
        self.host = os.environ.get('HW1_HOST', '')
        self.port = int(os.environ.get('HW1_PORT', '21'))
        self.test = os.environ.get('HW1_TEST', '')
        self.quiet = 'HW1_QUIET' in os.environ
        self.root_dir = os.environ.get('HW1_DIRECTORY')
        if self.root_dir is None:
            raise AttributeError('root dir not set')

        user_file = os.environ.get('HW1_USERS', None)
        self.users = dict()
        self.auth_enabled = os.environ.get('HW1_AUTH_DISABLED', 0) == 0
        if user_file is not None:
            with open(user_file, 'r') as f:
                users = f.readlines()
            users = users[1:]
            for s in users:
                login, password = s.strip().split('\t')
                self.users[login] = password
