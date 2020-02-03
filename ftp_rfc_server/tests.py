import ftplib
import io
import traceback
import data_processing
import os


def _open_ftp_connection(config, passive, login, password):
    ftp = ftplib.FTP()
    ftp.connect(config.host, config.port)
    ftp.login(login, password)
    ftp.set_pasv(passive)
    return ftp

def run_minimal_block(config, passive, login, password):
    ftp = _open_ftp_connection(config, passive, login, password)
    f = io.BytesIO(b'test\nfile\n')
    ftp.storlines('STOR test_file_1', f)
    response = []
    ftp.retrlines('RETR test_file_1', lambda s: response.append(s))
    ftp.quit()
    ftp.close()
    return response[0] == 'test' and response[1] == 'file'


def run_minimal(config, passive, login, password):
    ok = run_minimal_block(config, passive, login, password)
    return ok

def run_test_dir_creation(config, passive, login, password):
    ok = True
    ftp = _open_ftp_connection(config, passive, login, password)
    ftp.mkd('super_test_directory')
    ftp.mkd('super_test_directory/another_epic_directory')
    data = ftp.nlst('')
    if 'super_test_directory' not in data:
        ok = False
    data = ftp.nlst('super_test_directory')
    if len(data) != 1 or data[0] != 'another_epic_directory':
        ok = False
    ftp.rmd('super_test_directory/another_epic_directory')
    ftp.rmd('super_test_directory')
    data = ftp.nlst('')
    if 'super_test_directory' in data:
        ok = False
    ftp.quit()
    ftp.close()
    return ok


def run_test_cd(config, passive, login, password):
    ok = True
    ftp = _open_ftp_connection(config, passive, login, password)
    ftp.mkd('yay1')
    ftp.mkd('yay1/yay2')
    ftp.cwd('yay1')
    data = ftp.nlst('')
    if 'yay2' not in data:
        ok = False
    ftp.rmd('yay2')
    data = ftp.nlst('')
    if 'yay2' in data:
        ok = False
    ftp.cwd('..')
    data = ftp.nlst('')
    if 'yay1' not in data:
        ok = False
    ftp.rmd('yay1')
    ftp.quit()
    ftp.close()
    return ok


def run_test_append_delete(config, passive, login, password):
    ok = True
    ftp = _open_ftp_connection(config, passive, login, password)
    f = io.BytesIO(b'test\nfile\n')
    ftp.storlines('STOR test_file_2', f)
    f = io.BytesIO(b'test\nfile\n')
    ftp.storlines('APPE test_file_2', f)
    response = []
    ftp.retrlines('RETR test_file_2', lambda s: response.append(s))
    if len(response) != 4 or response[0] != 'test' or response[3] != 'file':
        ok = False
    ftp.delete('test_file_2')
    data = ftp.nlst()
    if 'test_file_2' in data:
        ok = False
    ftp.quit()
    ftp.close()
    return ok


def run_dir(config, passive, login, password):
    ok = run_test_dir_creation(config, passive, login, password)
    ok = ok and run_test_cd(config, passive, login, password)
    ok = ok and run_test_append_delete(config, passive, login, password)
    return ok


def run_test_mode_receive(config, passive, login, password, mode):
    ftp = _open_ftp_connection(config, passive, login, password)
    f = io.BytesIO(b'test\nfile\n')
    ftp.storlines('STOR test_file_3', f)
    ftp.voidcmd('MODE ' + mode)
    raw_data = bytearray()
    ftp.retrbinary('RETR test_file_3', lambda d: raw_data.extend(d))
    data = None
    if mode == 'S':
        data = raw_data
    elif mode == 'B':
        data = data_processing.data_from_block(raw_data)
    elif mode == 'C':
        data = data_processing.data_from_compress(raw_data)

    ftp.quit()
    ftp.close()
    return data == b'test\r\nfile\r\n'


def run_test_mode_send(config, passive, login, password, mode):
    ftp = _open_ftp_connection(config, passive, login, password)
    raw_data = b'test\r\nfile\r\n'
    data = None
    if mode == 'S':
        data = raw_data
    elif mode == 'B':
        data = data_processing.data_to_block(raw_data)
    elif mode == 'C':
        data = data_processing.data_to_compress(raw_data)
    f = io.BytesIO(data)
    ftp.voidcmd('MODE ' + mode)
    ftp.storbinary('STOR test_file_4', f)
    ftp.voidcmd('MODE S')
    response = []
    ftp.retrlines('RETR test_file_1', lambda s: response.append(s))
    ftp.quit()
    ftp.close()
    return len(response) == 2 and response[0] == 'test' and response[1] == 'file'


def run_test_mode(config, passive, login, password, mode):
    ok = run_test_mode_receive(config, passive, login, password, mode)
    ok = ok and run_test_mode_send(config, passive, login, password, mode)
    return ok


def run(config):
    ok = True
    try:
        if not config.test or config.test =='minimal':
            ok = run_minimal(config, False, 'anonymous', '') and ok
        if not config.test or config.test == 'dir':
            ok = run_dir(config, False, 'anonymous', '') and ok
        if not config.test or config.test == 'passive':
            ok = run_minimal(config, True, 'anonymous', '') and ok
            ok = run_dir(config, True, 'anonymous', '') and ok
        if not config.test or config.test == 'auth':
            u = next(iter(config.users.keys()))
            p = config.users[u]
            ok = run_minimal(config, True, u, p) and ok
            ok = run_dir(config, True, u, p) and ok
        if not config.test or config.test == 'trans-mode-block':
            ok = run_test_mode(config, True, 'anonymous', '', 'B') and ok
        if not config.test or config.test == 'trans-mode-compressed':
            ok = run_test_mode(config, True, 'anonymous', '', 'C') and ok
    except Exception as e:
        if 'HW1_QUIET' not in os.environ:
            traceback.print_exc()
        ok = False
    if ok:
        print('ok')
    else:
        print('fail')
