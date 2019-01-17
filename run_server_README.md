# ftpclient

`run_ftp_server.py` 依赖于第三方库 [**pyftpdlib**](https://github.com/giampaolo/pyftpdlib)

```bash
cd ftpclient
. ./setup_pyftpdlib.sh
python run_ftp_server.py
python ftp.py
```

```
» tree
.
├── README.md
├── __pycache__
│   └── ftp.cpython-36.pyc
├── ftp.py
├── pyftpdlib
│   ├── __init__.py
│   ├── __main__.py
│   ├── __pycache__
│   │   ├── ...
│   ├── _compat.py
│   ├── authorizers.py
│   ├── ...
├── run_ftp_server.py
├── setup_pyftpdlib.sh
└── 断点续传.py
```

```
» python run_ftp_server.py -h
usage: run_ftp_server.py [-h] [--username USERNAME] [--password PASSWORD]
                         [--root ROOT] [--port PORT]

Run Local FTP Server

optional arguments:
  -h, --help            show this help message and exit
  --username USERNAME, -u USERNAME
  --password PASSWORD, -p PASSWORD
  --root ROOT, -r ROOT
  --port PORT, -P PORT



» python run_ftp_server.py -P 8823
[I 2019-01-15 23:38:31] >>> starting FTP server on 127.0.0.1:8823, pid=61216 <<<
[I 2019-01-15 23:38:31] concurrency model: async
[I 2019-01-15 23:38:31] masquerade (NAT) address: None
[I 2019-01-15 23:38:31] passive ports: None



» python ftp.py
220 pyftpdlib 1.5.4 ready.
331 Username ok, send password.
230 Login successful.
200 Type set to: ASCII.
227 Entering passive mode (127,0,0,1,220,197).
125 Data connection already open. Transfer starting.
-rw-rw-r--   1 root     admin       14340 Jan 11 03:35 .DS_Store
d--x--x--x   9 root     wheel         288 Jan 08 04:05 .DocumentRevisions-V100
```


