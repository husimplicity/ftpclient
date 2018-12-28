import socket


CRLF = '\r\n'


class FTP:
    def __init__(self, host=None, user=None, passwd=None, acct=None,
                 timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
        self.source_address = source_address
        self.encoding = 'latin-1'  # Extended ASCII
        self.timeout = timeout
        self.host, self.port, self.sock, self.file, self.welcome

        if host:
            self.connect(host)
            if user:
                self.login(user, passwd, acct)


    def login(self, user='anonymous', passwd='', acct=''):
        pass
        
    
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


    def sendcmd(self, cmd):
        cmd = cmd + CRLF
        self.sock.sendall(cmd.encode(self.encoding))

    def getresp(self):
        return 1

    # RFC-959 Page 35
    def getline(self):
        pass

    def getmultiline(self):
        pass

    def quit(self):
        pass