import socket
import os
import sys
from tqdm import tqdm
from pathlib import Path

CRLF = '\r\n'
B_CRLF = b'\r\n'
FTP_PORT = 21

# https://stackoverflow.com/questions/287871/print-in-terminal-with-colors
BOLD = '\033[1m'
ENDC = '\033[0m'
WARNING = '\033[93m'
BGCOLOR = '\033[6;30;42m'
UNDERLINE = '\033[4m'

# Exception raised when an error or invalid response is received
class Error(Exception): pass
class error_reply(Error): pass          # unexpected [123]xx reply
class error_temp(Error): pass           # 4xx errors
class error_perm(Error): pass           # 5xx errors
class error_proto(Error): pass          # response does not begin with [1-5]
all_errors = {Error, IOError, EOFError}

MAXLINE = 8192
class FTP:
    host = ''
    port = FTP_PORT
    sock = None
    file = None
    welcome = None
    passiveserver = 1
    maxline = MAXLINE


    def __init__(self, host=None, user=None, passwd=None, acct=None,
                 timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
        self.source_address = source_address
        self.encoding = 'latin-1'  # Extended ASCII
        self.timeout = timeout
        # self.host, self.port, self.sock, self.file, self.welcome

        if host:
            self.connect(host)
            if user:
                self.login(user, passwd, acct)

    def send_noop(self):
        # https://stackoverflow.com/questions/15170503/checking-a-python-ftp-connection
        self.voidcmd('NOOP')

    def sendcmd(self, cmd):
        self.putline(cmd)
        return self.getresp()

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

    def putline(self, cmd):
        cmd = cmd + CRLF
        self.sock.sendall(cmd.encode(self.encoding))

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

    # RFC-959 Page 35
    def getline(self):
        line = self.file.readline()
        if not line:
            raise EOFError
        if line[-2:] == CRLF:
            line = line[:2]
        elif line[-1:] in CRLF:
            line = line[:-1]
        print(line)
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

    def voidcmd(self, cmd):
        self.putline(cmd)
        resp = self.getresp()
        if resp[:1] != '2':
            raise error_reply(resp)
        return resp

    def quit(self):
        resp = self.voidcmd('QUIT')
        if self.file:
            self.file.close()
            self.sock.close()
            self.file = None
            self.sock = None
        return resp

    def dir(self, *args):
        callback = None
        if args[-1:] and type(args[-1]) != type(''):
            args, callback = args[:-1], args[-1]
        cmd = ' '.join(['LIST', *args])
        self.retrlines(cmd, callback)

    def retrlines(self, cmd, callback=None):
        if callback is None:
            callback = print
        resp = self.sendcmd('TYPE A')
        # num_lines = sum(1 for l in open('ftp.py', 'r'))
        with self.transfercmd(cmd) as conn, \
                 conn.makefile('r', encoding=self.encoding) as fp:
            import time
            # for i in tqdm(range(num_lines + 1)):
            while True:
                time.sleep(0.02)
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

    def retrbinary(self, cmd, callback, blocksize=8192, rest=None):
        self.voidcmd('TYPE I')
        with self.transfercmd(cmd, rest) as conn:
            while 1:
                data = conn.recv(blocksize)
                if not data:
                    break
                callback(data)
        return self.voidresp()

    def storbinary(self, cmd, fp, blocksize=8192, callback=None, rest=None):
        self.voidcmd('TYPE I')
        with self.transfercmd(cmd, rest) as conn:
            while 1:
                buf = fp.read(blocksize)
                if not buf:
                    break
                conn.sendall(buf)
                if callback:
                    callback(buf)
        return self.voidresp()

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
                # See above.
                if resp[0] == '2':
                    resp = self.getresp()
                if resp[0] != '1':
                    raise error_reply(resp)
                conn, sockaddr = sock.accept()
                if self.timeout is not _GLOBAL_DEFAULT_TIMEOUT:
                    conn.settimeout(self.timeout)
        if resp[:3] == '150':
            # this is conditional in case we received a 125
            size = parse150(resp)
        return conn, size

    def transfercmd(self, cmd, rest=None):
        return self.ntransfercmd(cmd, rest)[0]

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
        port = sock.getsockname()[1] # Get proper port
        host = self.sock.getsockname()[0] # Get proper host
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

    def cwd(self, dirname):
        '''Change current working directory

        Arguments:
            dirname {str} -- > cd <dirname>
        '''
        if dirname == '..':
            try:
                return self.voidcmd('CDUP')
            except Error:
                pass
        elif dirname == '':
            dirname = '.'
        cmd = f'CWD {dirname}'
        return self.voidcmd(cmd)  # expect 2xx response

    def pwd(self):
        '''Return current working directory
        '''
        resp = self.voidcmd('PWD')
        return parse257(resp)

    def storlines(self, cmd, fp, callback=None):
        self.voidcmd('TYPE A')
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

    def rename(self, fromname, toname):
        resp = self.sendcmd('RNFR ' + fromname)
        if resp[0] != '3':
            raise error_reply(resp)
        return self.voidcmd('RNTO ' + toname)

    def delete(self, filename):
        resp = self.sendcmd('DELE ' + filename)
        if resp[:3] in {'250', '200'}:
            return resp
        else:
            raise error_reply(resp)

    def size(self, filename):
        self.voidcmd('TYPE I')
        # The SIZE command is defined in RFC-3659
        resp = self.sendcmd('SIZE ' + filename)
        if resp[:3] == '213':
            s = resp[3:].strip()
            return int(s)

    def mkd(self, dirname):
        resp = self.voidcmd('MKD ' + dirname)
        # fix around non-compliant implementations such as IIS shipped
        # with Windows server 2003
        if not resp.startswith('257'):
            return ''
        return parse257(resp)

    def rmd(self, dirname):
        return self.voidcmd('RMD ' + dirname)

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
            if short and f[0].startswith('.'):
                continue
            if not short:
                print("{:<12}\t\t".format(f[1].get('perm', '---------')), end='')
                print(f"{self.format_size_(f[1].get('size', -1))}\t\t", end='')
            if f[1].get('type', 'none') == 'dir':
                print(f'{BOLD}{f[0]}{ENDC}')
            else:
                print(f'{f[0]}')
        print()


def test():
    ftp = FTP('127.0.0.1','hatsu3','password')
    resp = ftp.sendcmd("")
    print(repr(resp))
    ftp.quit()


def parse150(resp):
    '''Parse the '150' response for a RETR request.
    Returns the expected transfer size or None; size is not guaranteed to
    be present in the 150 message.
    '''
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


_227_re = None

def parse227(resp):
    '''Parse the '227' response for a PASV request.
    Raises error_proto if it does not contain '(h1,h2,h3,h4,p1,p2)'
    Return ('host.addr.as.numbers', port#) tuple.'''

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
    '''Parse the '229' response for an EPSV request.
    Raises error_proto if it does not contain '(|||port|)'
    Return ('host.addr.as.numbers', port#) tuple.'''

    if resp[:3] != '229':
        raise error_reply(resp)
    left = resp.find('(')
    if left < 0: raise error_proto(resp)
    right = resp.find(')', left + 1)
    if right < 0:
        raise error_proto(resp) # should contain '(|||port|)'
    if resp[left + 1] != resp[right - 1]:
        raise error_proto(resp)
    parts = resp[left + 1:right].split(resp[left+1])
    if len(parts) != 5:
        raise error_proto(resp)
    host = peer[0]
    port = int(parts[3])
    return host, port

def parse257(resp):
    '''Parse the '257' response for a MKD or PWD request.
    This is a response to a MKD or PWD request: a directory name.
    Returns the directoryname in the 257 reply.'''

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

# test()


def print_warning(warning):
    print(WARNING + warning + ENDC)

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
        cmd = input(f'{UNDERLINE}{BOLD}FTP ➜ ').split()
        print(ENDC, end='')
        if not cmd:  # empty input
            continue
        cmd_type = cmd[0].lower()
        cmd_args = cmd[1:]
        if cmd_type == 'exit' or cmd_type == 'quit':
            ftp_client.quit()
            break
        elif cmd_type == 'll':
            dirname = '.' if not cmd_args else cmd_args[0]
            try:
                ftp_client.dir(dirname, print)
            except error_perm:
                print_warning(f'{dirname}: No such directory')
                continue
        elif cmd_type == 'ls':
            dirname = '.' if not cmd_args else cmd_args[0]
            try:
                ftp_client.pretty_mlsd(dirname, short=True)
            except error_perm:
                print_warning(f'{dirname}: No such directory')
                continue
        elif cmd_type == 'lh':
            dirname = '.' if not cmd_args else cmd_args[0]
            try:
                ftp_client.pretty_mlsd(dirname, short=False)
            except error_perm:
                print_warning(f'{dirname}: No such directory')
                continue
        elif cmd_type == 'cd':
            dirname = '' if not cmd_args else cmd_args[0]
            print(f'Changing working directory to {dirname}')
            try:
                ftp_client.cwd(dirname)
            except error_perm:
                print_warning(f'{dirname}: No such directory')
                continue
        elif cmd_type == 'pwd':
            print(f'Current working directory: {ftp_client.pwd()}')
        elif cmd_type == 'download_text':
            if len(cmd_args) != 1:
                print('download <FILENAME>')
                continue
            filename = cmd_args[0]
            try:
                ftp_client.retrlines(f'RETR {filename}', callback=print)
            except error_perm:
                print_warning(f'{filename}: No such directory')
                continue
            remote_path = Path(ftp_client.pwd()) / filename
            print(f'Downloaded text file {remote_path}')
        elif cmd_type == 'store_text':
            if len(cmd_args) != 1:
                print('store <FILENAME>')
                continue
            filename = cmd_args[0]
            file_path = Path(filename)
            print(f'Checking {file_path}...')
            if not file_path.is_file():
                print(f'{WARNING}No such file{ENDC}')
                continue
            fp = file_path.open(mode='rb')
            ftp_client.storlines(f'STOR {filename}', fp=fp, callback=None)
            remote_path = Path(ftp_client.pwd()) / Path(filename).name
            print(f'{filename} saved at {remote_path}')
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
            ''')
        elif cmd_type == 'download':
            # download binary files
            if len(cmd_args) != 1:
                print('download <FILENAME>')
                continue
            filename = cmd_args[0]
            local_path = Path(filename).name
            try:
                with open(local_path, 'wb') as fp:
                    ftp_client.retrbinary(f'RETR {filename}', callback=(lambda x: fp.write(x)))
            except error_perm:
                print_warning(f'{filename}: No such directory')
                continue
            remote_path = Path(ftp_client.pwd()) / filename
            print(f'Downloaded binary file {remote_path}')
        elif cmd_type == 'store':
            # uploas binary files
            if len(cmd_args) != 1:
                print('store <FILENAME>')
                continue
            filename = cmd_args[0]
            file_path = Path(filename)
            print(f'Checking {file_path}...')
            if not file_path.is_file():
                print_warning(f'{filename}: No such file')
                continue
            fp = file_path.open(mode='rb')
            ftp_client.storbinary(f'STOR {filename}', fp=fp, callback=None)
            remote_path = Path(ftp_client.pwd()) / Path(filename).name
            print(f'{filename} saved at {remote_path}')
        elif cmd_type == 'rm':
            if len(cmd_args) != 1:
                print('rm <FILENAME>')
                continue
            filename = cmd_args[0]
            try:
                ftp_client.delete(filename)
            except error_perm:
                print_warning(f'{filename}: No such file')
                continue
            remote_path = Path(ftp_client.pwd()) / filename
            print(f'Deleted {remote_path}')
        elif cmd_type == 'mkdir':
            if len(cmd_args) != 1:
                print('mkdir <DIRNAME>')
                continue
            dirname = cmd_args[0]
            ftp_client.mkd(dirname)
            print(f'Created directory {dirname}')
        elif cmd_type == 'rmdir':
            if len(cmd_args) != 1:
                print('rmdir <DIRNAME>')
                continue
            dirname = cmd_args[0]
            try:
                ftp_client.rmd(dirname)
            except error_perm:
                print_warning(f'{dirname}: No such directory')
                continue
            print(f'Deleted directory {dirname}')
        elif cmd_type == 'rename':
            if len(cmd_args) != 2:
                print('rename <FROM_NAME> <TO_NAME>')
                continue
            from_name, to_name = cmd_args
            try:
                ftp_client.rename(from_name, to_name)
            except error_perm:
                print_warning(f'{from_name}: No such file or directory')
                continue
            print(f'Renamed {from_name} to {to_name}')
        elif cmd_type == 'sz':
            if len(cmd_args) != 1:
                print('sz <FILENAME>')
                continue
            filename = cmd_args[0]
            try:
                sz = ftp_client.size(filename)
            except error_perm:
                print_warning(f'{filename}: No such file or directory')
                continue
            print(f'Size of {filename} is {sz} bytes')
        else:
            print('Invalid command. Try help')

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

