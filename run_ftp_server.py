# https://github.com/giampaolo/pyftpdlib

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

authorizer = DummyAuthorizer()
authorizer.add_user("hatsu3", "password", "/Users/hatsu3", perm="elradfmwMT")
authorizer.add_anonymous("/Users/Guest")

handler = FTPHandler
handler.authorizer = authorizer

server = FTPServer(('127.0.0.1', 8821), handler)
server.serve_forever()
