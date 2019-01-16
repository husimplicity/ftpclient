import socket
import os
import sys

CRLF = '\r\n'
FTP_PORT = 21

# Exception raised when an error or invalid response is received
class Error(Exception): pass
class error_reply(Error): pass          # unexpected [123]xx reply
class error_temp(Error): pass           # 4xx errors
class error_perm(Error): pass           # 5xx errors
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
#        self.host, self.port, self.sock, self.file, self.welcome

        if host:
            self.connect(host)
            if user:
                self.login(user, passwd, acct)

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
        with self.transfercmd(cmd) as conn, \
                 conn.makefile('r', encoding=self.encoding) as fp:
            while 1:
                line = fp.readline(self.maxline + 1)
                if len(line) > self.maxline:
                    raise Error("got more than %d bytes" % self.maxline)
                if not line:
                    break
                if line[-2:] == CRLF:
                    line = line[:-2]
                elif line[-1:] == '\n':
                    line = line[:-1]
                callback(line)
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
    # -> 200 Type set to: ASCII.
    # -> 227 Entering passive mode (127,0,0,1,204,237).
    # -> 125 Data connection already open. Transfer starting.
    # -> -rw-r--r--   1 hatsu3   staff         267 Jul 18  2018 .489614.padl
    # -> -r--------   1 hatsu3   staff           7 Oct 29 12:26 .CFUserTextEncoding
    # -> drwx------   2 hatsu3   staff          64 Dec 26 16:19 .CMVolumes
    # -> <OMITTED> ...

    while True:
        cmd = input('FTP > ').split()
        if not cmd:  # empty input
            continue
        cmd_type = cmd[0].lower()
        cmd_args = cmd[1:]
        if cmd_type == 'exit' or cmd_type == 'quit':
            ftp_client.quit()
            break
        elif cmd_type == 'ls':
            dirname = '.' if not cmd_args else cmd_args[0]
            ftp_client.dir('.', print)
        elif cmd_type == 'cd':
            dirname = '' if not cmd_args else cmd_args[0]
            print(f'Changing working directory to {dirname}')
            try:
                ftp_client.cwd(dirname)
            except error_perm:
                print('No such file or directory')
        elif cmd_type == 'pwd':
            print(f'Current working directory: {ftp_client.pwd()}')
        elif cmd_type == 'download':
            if not cmd_args:
                print('download <FILENAME>')
                continue
            filename = cmd_args[0]
            ftp_client.retrlines('RETR ' + filename, callback=print)
        elif cmd_type == 'help':
            print('''
            - exit
            - ls </./../DIRNAME>
            - cd </./../DIRNAME>
            - pwd
            - download <FILENAME>
            - help
            ''')
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

