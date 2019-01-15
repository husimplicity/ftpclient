# https://github.com/giampaolo/pyftpdlib

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
import argparse

parser = argparse.ArgumentParser(description='Run Local FTP Server')
parser.add_argument('--username', '-u', default='username')
parser.add_argument('--password', '-p', default='password')
parser.add_argument('--root', '-r', default='/')
parser.add_argument('--port', '-P', default=8821)
args = parser.parse_args()

authorizer = DummyAuthorizer()
authorizer.add_user(args.username, args.password, args.root, perm="elradfmwMT")
# authorizer.add_anonymous("/Users/Guest")

handler = FTPHandler
handler.authorizer = authorizer

server = FTPServer(('127.0.0.1', args.port), handler)
server.serve_forever()
