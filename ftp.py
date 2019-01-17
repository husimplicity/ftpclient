import os
import sys
import select
import socket
from socket import _GLOBAL_DEFAULT_TIMEOUT
from pathlib import Path

from tqdm import tqdm




CRLF        = '\r\n'
B_CRLF      = b'\r\n'
FTP_PORT    = 21
MAXLINE     = 8192
_227_re = None
_150_re = None


# https://stackoverflow.com/questions/287871/print-in-terminal-with-colors
ENDC        = '\033[0m'
BOLD        = '\033[1m'
ITALIC      = '\033[3m'
UNDERLINE   = '\033[4m'
OKGREEN     = '\033[92m'
WARNING     = '\033[93m'
OKBLUE      = '\033[94m'
BGCOLOR     = '\033[6;30;42m'


# Exception raised when an error or invalid response is received
class Error(Exception):     pass
class error_reply(Error):   pass          # unexpected [123]xx reply
class error_temp(Error):    pass          # 4xx errors
class error_perm(Error):    pass          # 5xx errors
class error_proto(Error):   pass          # response does not begin with [1-5]
all_errors = {Error, IOError, EOFError}




class FTP:
    def __init__(self, host=None, user=None, passwd=None, acct=None,
                 timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
        self.host           = ''
        self.port           = FTP_PORT
        self.sock           = None
        self.file           = None
        self.welcome        = None
        self.passiveserver  = 1
        self.maxline        = MAXLINE
        self.source_address = source_address
        self.encoding       = 'latin-1'  # Extended ASCII
        self.timeout        = timeout

        if host:
            self.connect(host)
            if user:
                self.login(user, passwd, acct)

    def putline(self, cmd):
        cmd = cmd + CRLF
        self.sock.sendall(cmd.encode(self.encoding))

    # RFC-959 Page 35
    def getline(self):
        line = self.file.readline()
        if not line:
            raise EOFError
        if line[-2:] == CRLF:
            line = line[:2]
        elif line[-1:] in CRLF:
            line = line[:-1]
        # print(line)
        return line

    def getmultiline(self):
        line = self.getline()
        if line[3:4] == '-':
            code = line[:3]
            while 1:
                nextline = self.getline()
                line = line + ('\n' + nextline)
                if nextline[:3] == code and nextline[3:4] != '-':
                    break;
        return line

    def getresp(self):
        resp = self.getmultiline()
        self.lastresp = resp[:3]
        c = resp[:1]
        if c in {'1','2','3'}:
            return resp
        if c == '4':
            raise error_temp(resp)
        if c == '5':
            raise error_perm(resp)
        raise error_proto(resp)

    def send_noop(self):
        # https://stackoverflow.com/questions/15170503/checking-a-python-ftp-connection
        self.voidcmd('NOOP')

    def sendcmd(self, cmd):
        self.putline(cmd)
        return self.getresp()

    def voidcmd(self, cmd):
        self.putline(cmd)
        resp = self.getresp()
        if resp[:1] != '2':
            raise error_reply(resp)
        return resp

    def voidresp(self):
        """Expect a response beginning with '2'."""
        resp = self.getresp()
        if resp[:1] != '2':
            raise error_reply(resp)  # empty exception
        return resp




    def login(self, user='', passwd='', acct=''):
        if not user: user = 'anonymous'
        if not passwd: passwd = ''
        if not acct: acct = ''
        if user == 'anonymous' and passwd in {'','-'}:
            passwd = passwd + 'anonymous@'
        resp = self.sendcmd('USER ' + user)
        if resp[0] == '3': resp = self.sendcmd('PASS ' + passwd)
        if resp[0] == '3': resp = self.sendcmd('ACCT ' + acct)
        if resp[0] != '2': raise error_reply(resp)
        return resp

    def connect(self, host=None, port=None, timeout=None, source_address=None):
        # Override presets
        if host is not None:            self.host = host
        if port is not None:            self.port = port
        if timeout is not None:         self.timeout = timeout
        if source_address is not None: self.source_address

        # IPv4 address of FTP host
        host_addr = (self.host, self.port)

        # Convenience function: socket -> bind -> connect
        self.sock = socket.create_connection(
            host_addr, timeout=self.timeout, source_address=self.source_address)
        # self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

        # necessary
        self.af = self.sock.family

        # file-like interface for socket reading
        self.file = self.sock.makefile(mode='r', encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome

    def sendport(self, host, port):
        '''Send a PORT command with the current host and the given
        port number.
        '''
        hbytes = host.split('.')
        pbytes = [repr(port//256), repr(port%256)]
        bytes = hbytes + pbytes
        cmd = 'PORT ' + ','.join(bytes)
        return self.voidcmd(cmd)

    def sendeprt(self, host, port):
        '''Send an EPRT command with the current host and the given port number.'''
        af = 0
        if self.af == socket.AF_INET:
            af = 1
        if self.af == socket.AF_INET6:
            af = 2
        if af == 0:
            raise error_proto('unsupported address family')
        fields = ['', repr(af), host, repr(port), '']
        cmd = 'EPRT ' + '|'.join(fields)
        return self.voidcmd(cmd)

    def makeport(self):
        err = None
        sock = None
        for res in socket.getaddrinfo(None, 0, self.af, socket.SOCK_STREAM, 0, socket.AI_PASSIVE):
            af, socktype, proto, canonname, sa = res
            try:
                sock = socket.socket(af, socktype, proto)
                sock.bind(sa)
            except OSError as _:
                err = _
                if sock:
                    sock.close()
                sock = None
                continue
            break
        if sock is None:
            if err is not None:
                raise err
            else:
                raise OSError("getaddrinfo returns an empty list")
        sock.listen(1)
        port = sock.getsockname()[1]
        host = self.sock.getsockname()[0]
        if self.af == socket.AF_INET:
            resp = self.sendport(host, port)
        else:
            resp = self.sendeprt(host, port)
        if self.timeout is not _GLOBAL_DEFAULT_TIMEOUT:
            sock.settimeout(self.timeout)
        return sock

    def makepasv(self):
        if self.af == socket.AF_INET:
            host, port = parse227(self.sendcmd('PASV'))
        else:
            host, port = parse229(self.sendcmd('EPSV'), self.sock.getpeername())
        return host, port

    def ntransfercmd(self, cmd, rest=None):
        size = None
        if self.passiveserver:
            host, port = self.makepasv()
            conn = socket.create_connection((host, port), self.timeout,
                                            source_address=self.source_address)
            try:
                if rest is not None:
                    self.sendcmd("REST %s" % rest)
                resp = self.sendcmd(cmd)
                if resp[0] == '2':
                    resp = self.getresp()
                if resp[0] != '1':
                    raise error_reply(resp)
            except:
                conn.close()
                raise
        else:
            with self.makeport() as sock:
                if rest is not None:
                    self.sendcmd("REST %s" % rest)
                resp = self.sendcmd(cmd)
                if resp[0] == '2':
                    resp = self.getresp()
                if resp[0] != '1':
                    raise error_reply(resp)
                conn, __ = sock.accept()
                if self.timeout is not _GLOBAL_DEFAULT_TIMEOUT:
                    conn.settimeout(self.timeout)
        if resp[:3] == '150':
            size = parse150(resp)
        return conn, size

    def transfercmd(self, cmd, rest=None):
        return self.ntransfercmd(cmd, rest)[0]




    def retrlines(self, cmd, callback=None):
        if callback is None:
            callback = print
        resp = self.sendcmd('TYPE A')
        # num_lines = sum(1 for l in open('ftp.py', 'r'))
        with self.transfercmd(cmd) as conn, \
                 conn.makefile('r', encoding=self.encoding) as fp:
            # import time
            # for i in tqdm(range(num_lines + 1)):
            while True:
                # time.sleep(0.02)
                line = fp.readline(self.maxline + 1)
                if len(line) > self.maxline:
                    raise Error("got more than %d bytes" % self.maxline)
                if not line:
                    break
                if line[-2:] == CRLF:
                    line = line[:-2]
                elif line[-1:] == '\n':
                    line = line[:-1]
                callback(line);
                # self.send_noop();
        return self.voidresp()

    def storlines(self, cmd, fp, callback=None):
        self.voidcmd('TYPE A')  # type ASCII (text)
        with self.transfercmd(cmd) as conn:
            while True:
                buf = fp.readline(self.maxline + 1)
                if not buf:
                    break
                if buf[-2:] != B_CRLF:
                    if buf[-1] in B_CRLF: buf = buf[:-1]
                    buf = buf + B_CRLF
                conn.sendall(buf)
                if callback:
                    callback(buf)


        return self.voidresp()

    def retrbinary(self, cmd, callback, n_block, blocksize=8192, rest=None):
        self.voidcmd('TYPE I')  # type Image (binary)
        with self.transfercmd(cmd, rest) as conn:
            for i in tqdm(range(n_block)):
                data = conn.recv(blocksize)
                if not data:
                    break
                callback(data)
                if (i + 1) % 5 == 0:
                    self.send_noop()
        return self.voidresp()

    def storbinary(self, cmd, fp, n_block, blocksize=8192, callback=None, rest=None):
        self.voidcmd('TYPE I')
        with self.transfercmd(cmd, rest) as conn:
            for i in tqdm(range(n_block + 1)):
                buf = fp.read(blocksize)
                if not buf:
                    break
                conn.sendall(buf)
                if callback:
                    callback(buf)
                if (i + 1) % 5 == 0:
                    self.send_noop()
        return self.voidresp()





    def pwd(self):
        '''Return current working directory
        '''
        resp = self.voidcmd('PWD')
        return parse257(resp)

    def dir(self, *args):
        callback = None
        if args[-1:] and type(args[-1]) != type(''):
            args, callback = args[:-1], args[-1]
        cmd = ' '.join(['LIST', *args])
        self.retrlines(cmd, callback)

    def nlst(self, *args):
        '''Return a list of files in a given directory (default the current).'''
        cmd = 'NLST'
        for arg in args:
            cmd = cmd + (' ' + arg)
        files = []
        self.retrlines(cmd, files.append)
        return files

    def mlsd(self, path="", facts=[]):
        if facts:
            self.sendcmd("OPTS MLST " + ";".join(facts) + ";")
        if path:
            cmd = "MLSD %s" % path
        else:
            cmd = "MLSD"
        lines = []
        self.retrlines(cmd, lines.append)
        for line in lines:
            facts_found, _, name = line.rstrip(CRLF).partition(' ')
            entry = {}
            for fact in facts_found[:-1].split(";"):
                key, _, value = fact.partition("=")
                entry[key.lower()] = value
            yield (name, entry)

    def size(self, filename):
        self.voidcmd('TYPE I')
        # The SIZE command is defined in RFC-3659
        resp = self.sendcmd('SIZE ' + filename)
        if resp[:3] == '213':
            s = resp[3:].strip()
            return int(s)




    def cwd(self, dirname):
        if dirname == '..':
            try:
                return self.voidcmd('CDUP')
            except Error:
                pass
        elif dirname == '':
            dirname = '.'
        cmd = f'CWD {dirname}'
        return self.voidcmd(cmd)  # expect 2xx response

    def rename(self, fromname, toname):
        resp = self.sendcmd('RNFR ' + fromname)
        if resp[0] != '3':
            raise error_reply(resp)
        return self.voidcmd('RNTO ' + toname)

    def mkd(self, dirname):
        resp = self.voidcmd('MKD ' + dirname)
        if not resp.startswith('257'):
            return ''
        return parse257(resp)

    def rmd(self, dirname):
        return self.voidcmd('RMD ' + dirname)

    def delete(self, filename):
        resp = self.sendcmd('DELE ' + filename)
        if resp[:3] in {'250', '200'}:
            return resp
        else:
            raise error_reply(resp)

    def quit(self):
        resp = self.voidcmd('QUIT')
        if self.file:
            self.file.close()
            self.sock.close()
            self.file = None
            self.sock = None
        return resp




    def format_size_(self, n_byte):
        n_byte = int(n_byte)
        KB, MB, GB = 2**10, 2**20, 2**30
        if n_byte < KB:
            return '{:>6} B  '.format(n_byte)
        elif n_byte < MB:
            return '{:>6} KiB'.format(n_byte // KB)
        elif n_byte < GB:
            return '{:>6} MiB'.format(n_byte // MB)
        else:
            return '{:>6} GiB'.format(n_byte // GB)

    def pretty_mlsd(self, path='', short=False):
        file_list = self.mlsd(path=path, facts=["type", "size", "perm"])
        for f in file_list:
            if f[0].startswith('.'):
                continue
            if not short:
                print("{:<12}\t\t".format(f[1].get('perm', '---------')), end='')
                print(f"{self.format_size_(f[1].get('size', -1))}\t\t", end='')
            if f[1].get('type', 'none') == 'dir':
                print(f'{BOLD}{f[0]}{ENDC}')
            else:
                print(f'{f[0]}')





def parse150(resp):
    if resp[:3] != '150':
        raise error_reply(resp)
    global _150_re
    if _150_re is None:
        import re
        _150_re = re.compile(
            r"150 .* \((\d+) bytes\)", re.IGNORECASE | re.ASCII)
    m = _150_re.match(resp)
    if not m:
        return None
    return int(m.group(1))

def parse227(resp):
    if resp[:3] != '227':
        raise error_reply(resp)
    global _227_re
    if _227_re is None:
        import re
        _227_re = re.compile(r'(\d+),(\d+),(\d+),(\d+),(\d+),(\d+)', re.ASCII)
    m = _227_re.search(resp)
    if not m:
        raise error_proto(resp)
    numbers = m.groups()
    host = '.'.join(numbers[:4])
    port = (int(numbers[4]) << 8) + int(numbers[5])
    return host, port

def parse229(resp, peer):
    if resp[:3] != '229':
        raise error_reply(resp)
    left = resp.find('(')
    if left < 0: raise error_proto(resp)
    right = resp.find(')', left + 1)
    if right < 0:
        raise error_proto(resp)
    if resp[left + 1] != resp[right - 1]:
        raise error_proto(resp)
    parts = resp[left + 1:right].split(resp[left+1])
    if len(parts) != 5:
        raise error_proto(resp)
    host = peer[0]
    port = int(parts[3])
    return host, port

def parse257(resp):
    if resp[:3] != '257':
        raise error_reply(resp)
    if resp[3:5] != ' "':
        return '' # Not compliant to RFC 959, but UNIX ftpd does this
    dirname = ''
    i = 5
    n = len(resp)
    while i < n:
        c = resp[i]
        i = i+1
        if c == '"':
            if i >= n or resp[i] != '"':
                break
            i = i+1
        dirname = dirname + c
    return dirname




def print_warning(warning):
    print(f'{BOLD}{WARNING}{ITALIC}[ERROR] {warning}{ENDC}')

def print_info(info, end=None):
    if end is not None:
        print(f'{BOLD}{ITALIC}[INFO]  {info}{ENDC}', end=end)
    else:
        print(f'{BOLD}{ITALIC}[INFO]  {info}{ENDC}')

def timeout_input(prompt, timeout=10):
    try:
        if prompt:
            print(prompt)
        i, __, __ = select.select([sys.stdin], [], [], timeout)
        return sys.stdin.readline().strip() if i else None
    except:
        raise
    finally:
        print(ENDC, end='')




def test():
    ftp = FTP('127.0.0.1','hatsu3','password')
    resp = ftp.sendcmd("")
    print(repr(resp))
    ftp.quit()

if __name__ == '__main__':
    # run_ftp_server.py
    # - host        =   127.0.0.1:8821 
    # - home        =   /Users/hatsu3
    # - username    =   hatsu3
    # - password    =   password

    host = '127.0.0.1'
    port = 8822
    user = 'username'
    passwd = 'password'


    ftp_client = FTP()

    ftp_client.connect(host=host, port=port)
    # -> 220 pyftpdlib 1.5.4 ready.

    ftp_client.login(user=user, passwd=passwd)
    # -> 331 Username ok, send password.
    # -> 30 Login successful.

    # ftp_client.dir('.', print)  # ftp_client.dir('./Library')
    # # -> 200 Type set to: ASCII.
    # # -> 227 Entering passive mode (127,0,0,1,204,237).
    # # -> 125 Data connection already open. Transfer starting.
    # # -> -rw-r--r--   1 hatsu3   staff         267 Jul 18  2018 .489614.padl
    # # -> -r--------   1 hatsu3   staff           7 Oct 29 12:26 .CFUserTextEncoding
    # # -> drwx------   2 hatsu3   staff          64 Dec 26 16:19 .CMVolumes
    # # -> <OMITTED> ...

    while True:
        # cmd = input(f'{UNDERLINE}{BOLD}FTP ➜ ').split()
        print()
        prompt = f'{UNDERLINE}{BOLD}FTP {OKBLUE}{host}:{port} {OKGREEN}{os.getcwd()} ⌁ {ftp_client.pwd()} ➜{ENDC}{UNDERLINE}{BOLD}'
        cmd = timeout_input(prompt, timeout=20)
        while cmd is None:
            ftp_client.send_noop()
            cmd = timeout_input('', timeout=20)

        cmd = cmd.split()
        if not cmd:  # empty input
            continue
        cmd_type = cmd[0].lower()
        cmd_args = cmd[1:]

        if cmd_type == 'exit' or cmd_type == 'quit':
            ftp_client.quit()
            break

        elif cmd_type == 'll':
            try:
                dirname = '.' if not cmd_args else cmd_args[0]
                ftp_client.dir(dirname, print)
            except error_perm:
                print_warning(f'{dirname}: No such directory')

        elif cmd_type == 'ls':
            try:
                dirname = '.' if not cmd_args else cmd_args[0]
                ftp_client.pretty_mlsd(dirname, short=True)
            except error_perm:
                print_warning(f'{dirname}: No such directory')

        elif cmd_type == 'lh':
            try:
                dirname = '.' if not cmd_args else cmd_args[0]
                ftp_client.pretty_mlsd(dirname, short=False)
            except error_perm:
                print_warning(f'{dirname}: No such directory')

        elif cmd_type == 'cd':
            try:
                dirname = '.' if not cmd_args else cmd_args[0]
                print_info(f'Changing working directory to {dirname}')
                ftp_client.cwd(dirname)
            except error_perm:
                print_warning(f'{dirname}: No such directory')

        elif cmd_type == 'pwd':
            print_info(f'Current working directory: {ftp_client.pwd()}')

        elif cmd_type == 'download_text':
            try:
                if len(cmd_args) != 1:
                    print('download <FILENAME>')
                    continue
                filename = cmd_args[0]
                # local_path = Path(filename).name
                ftp_client.retrlines(f'RETR {filename}', callback=print)
                remote_path = Path(ftp_client.pwd()) / filename
                print_info(f'Downloaded text file {remote_path}')
            except error_perm:
                print_warning(f'{filename}: No such directory')

        elif cmd_type == 'store_text':
            if len(cmd_args) != 1:
                print('store <FILENAME>')
                continue
            filename = cmd_args[0]
            file_path = Path(filename)
            print_info(f'Checking {file_path}...')
            if not file_path.is_file():
                print_warning(f'No such file')
                continue
            fp = file_path.open(mode='rb')
            ftp_client.storlines(f'STOR {filename}', fp=fp, callback=None)
            remote_path = Path(ftp_client.pwd()) / Path(filename).name
            print_info(f'{filename} saved at {remote_path}')

        elif cmd_type == 'help':
            print('''
            - exit
            - ls </./../DIRNAME>
            - cd </./../DIRNAME>
            - pwd
            - download_text / download <FILENAME>
            - store_text / store <FILENAME>
            - help
            - mkdir <DIRNAME>
            - rmdir <DIRNAME>
            - rename <FROM_NAME> <TO_NAME>
            - sz <FILENAME>
            - rm <FILENAME>
            - ccd <PATH>
            - cpwd
            - cls
            ''')

        elif cmd_type == 'download':
            # download binary files
            try:
                if len(cmd_args) != 1:
                    print('download <FILENAME>')
                    continue
                filename = cmd_args[0]
                local_path = Path(filename).name
                sz = ftp_client.size(filename)
                blocksize = 8192
                n_block = sz // blocksize + 1
                with open(local_path, 'wb') as fp:
                    ftp_client.retrbinary(f'RETR {filename}', callback=(lambda x: fp.write(x)), \
                                          blocksize=blocksize, n_block=n_block)
                remote_path = Path(ftp_client.pwd()) / filename
                print_info(f'Downloaded binary file {remote_path}')
            except error_perm:
                print_warning(f'{filename}: No such directory')

        elif cmd_type == 'store':
            # uploas binary files
            if len(cmd_args) != 1:
                print('store <FILENAME>')
                continue
            filename = cmd_args[0]
            file_path = Path(filename)
            print_info(f'Checking {file_path}...')
            if not file_path.is_file():
                print_warning(f'{filename}: No such file')
                continue
            sz = os.path.getsize(filename)
            blocksize = 8192
            n_block = sz // blocksize + 1
            fp = file_path.open(mode='rb')
            ftp_client.storbinary(f'STOR {filename}', fp=fp, callback=None, \
                                blocksize=blocksize, n_block=n_block)
            remote_path = Path(ftp_client.pwd()) / Path(filename).name
            print_info(f'{filename} saved at {remote_path}')

        elif cmd_type == 'rm':
            try:
                if len(cmd_args) != 1:
                    print('rm <FILENAME>')
                    continue
                filename = cmd_args[0]
                ftp_client.delete(filename)
                remote_path = Path(ftp_client.pwd()) / filename
                print_info(f'Deleted {remote_path}')
            except error_perm:
                print_warning(f'{filename}: No such file')

        elif cmd_type == 'mkdir':
            if len(cmd_args) != 1:
                print('mkdir <DIRNAME>')
                continue
            dirname = cmd_args[0]
            ftp_client.mkd(dirname)
            print_info(f'Created directory {dirname}')

        elif cmd_type == 'rmdir':
            try:
                if len(cmd_args) != 1:
                    print('rmdir <DIRNAME>')
                    continue
                dirname = cmd_args[0]
                ftp_client.rmd(dirname)
                print_info(f'Deleted directory {dirname}')
            except error_perm:
                print_warning(f'{dirname}: No such directory')

        elif cmd_type == 'rename':
            try:
                if len(cmd_args) != 2:
                    print('rename <FROM_NAME> <TO_NAME>')
                    continue
                from_name, to_name = cmd_args
                ftp_client.rename(from_name, to_name)
                print_info(f'Renamed {from_name} to {to_name}')
            except error_perm:
                print_warning(f'{from_name}: No such file or directory')

        elif cmd_type == 'sz':
            try:
                if len(cmd_args) != 1:
                    print('sz <FILENAME>')
                    continue
                filename = cmd_args[0]
                sz = ftp_client.size(filename)
                print_info(f'Size of {filename} is {sz} bytes')
            except error_perm:
                print_warning(f'{filename}: No such file or directory')

        elif cmd_type == 'ccd':
            try:
                if len(cmd_args) != 1:
                    print('ccd <PATH>')
                    continue
                new_path = cmd_args[0]
                os.chdir(new_path)
                print_info(f'[client] Working directory changed to {os.getcwd()}')
            except FileNotFoundError:
                print_warning(f'{new_path}: No such directory')
            except:
                print_warning(f'Failed to cd to {new_path}')

        elif cmd_type == 'cpwd':
            print(f'[client] Current working directory is {os.getcwd()}')

        elif cmd_type == 'cls':
            for f in os.listdir('.'):
                if f.startswith('.'):
                    continue
                sz = os.path.getsize(f)
                print_info(ftp_client.format_size_(sz) + '\t\t', end='')
                print(f if os.path.isfile(f) else f'{BOLD}{f}{ENDC}')

        elif cmd_type == 'continue_download':
            try:
                if len(cmd_args) != 1:
                    print('download <FILENAME>')
                    continue
                filename = cmd_args[0]

                print_info(f'Checking {filename}...')
                if not Path(filename).is_file():
                    print_warning(f'{filename}: No such file')
                    continue

                local_sz = os.path.getsize(Path(filename).name)
                remote_sz = ftp_client.size(filename)
                remain_sz = remote_sz - local_sz
                blocksize = 8192
                n_block = remain_sz // blocksize + 1

                if n_block == 0:
                    print_warning('Tranfer completed. Nothing to download')
                    continue

                print_info(f'Continue downloading {filename}, remaining {ftp_client.format_size_(remain_sz)}')
                local_path = Path(filename).name
                remote_path = Path(ftp_client.pwd()) / filename

                with open(local_path, 'ab') as fp:
                    ftp_client.retrbinary(f'RETR {filename}', callback=(lambda x: fp.write(x)), \
                                          blocksize=blocksize, n_block=n_block, rest=local_sz)

                print_info(f'Downloaded binary file {remote_path}')
            except error_perm:
                print_warning(f'{filename}: No such directory')

        else:
            print_warning('Invalid command. Try help')

    # filename = input('Which file to retrieve: ')
    # # <- Users/hatsu3/Documents/GitHub/ftpclient/ftp.py
    # ftp_client.retrlines('RETR ' + filename, callback=print)
    # # -> 200 Type set to: ASCII.
    # # -> 227 Entering passive mode (127,0,0,1,243,131).
    # # -> 125 Data connection already open. Transfer starting.
    # # -> import socket
    # # -> <OMITTED> ...
    # # -> 226 Transfer complete.

    # ftp_client.quit()
    # # -> 21 Goodbye.
