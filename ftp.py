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

class FTP:
    host = ''
    port = FTP_PORT
    sock = None
    file = None
    welcome = None
    passiveserver = 1

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

    def login(self, user='', passwd='', acct=''):
        if not user: user = 'anonymous'
        if not passwd: passwd = ''
        if not acct: acct = ''
        if user == 'anonymous' and passwd in {'','-'}:
            passwd = passwd + 'anonymous@'
        resp = self.sendcmd('USER' + user)
        if resp[0] == '3': resp = self.sendcmd('PASS' + passwd)
        if resp[0] == '3': resp = self.sendcmd('ACCT' + acct)
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

def test():
    ftp = FTP('127.0.0.1','','')
    resp = ftp.sendcmd("")
    print(repr(resp))
    ftp.quit()

test()
