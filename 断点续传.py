import ftp
import sys
import os.path

##在FTP的基础上实现。
##先补充FTPLIB里有我们没实现的FTP模块
##ftp_login用于connect和login
##ftp_download用于从远程服务器下载数据，其中实现断点续传

class my_FTP(ftp.FTP):
        def __init__(self):
            super().__init__()
            print("A FTP is established.")
        def size(self, filename):
                '''Retrieve the size of a file.'''
                # The SIZE command is defined in RFC-3659
                print('SIZE ' + filename)
                resp = self.sendcmd('SIZE ' + filename)
                if resp[:3] == '213':
                        s = resp[3:].strip()
                return int(s)


        ##与服务器连接并登陆
        def ftp_login(self,host_ip,host_port,username,password):
                print(f'self.connect({host_ip},{host_port})')
                print(f'self.login(user={username},passwd={password})')
                try:
                    self.connect(host_ip,host_port) #,timeout=100)
                except Exception as e:
                    print(e)
                    print('错误：连接失败')
                    return 0
                try:
                    self.login(user=username,passwd=password)
                except:
                    print('错误：用户名或密码错误')
                    return 0
                return 1

        def ftp_download(self,remote_host_ip,remote_port,username,password,remote_path,local_path,log_info):
                if(log_info==0):
                        sys.exit()
                root_position=remote_path.rfind('/')
                remote_path_root=remote_path[:root_position+1]
                remote_file_name=remote_path[root_position+1:]     #获取远程文件名
                print(remote_file_name)
                print(remote_path_root)

                if remote_path_root:  ##问题在这里
                        try:
                                remote_path_root=self.cwd(remote_path_root)
                        except ftp.error_perm:
                                print ('错误：不能读取文件')
                                return
                self.sendcmd('TYPE I') #规定为binary模式
                remote_file_size=self.size(remote_file_name)
                print(remote_file_size)

                if remote_file_size==0 : #远程文件大小为0则返回
                        print ('远程文件大小为0，无需下载')
                        return
                local_file_size=0
                if os.path.exists(local_path):    #表示本地路径已经存在，即文件已经下载了一部分了
                        local_file_size=os.stat(local_path).st_size-1 #如果本地已经有文件则读取本地文件的大小
                        with open(local_path, 'ab') as f:
                            f.truncate(local_file_size)

                print(local_file_size)
                if local_file_size == remote_file_size:    #如果两个文件大小相当则表示已经下载完了
                        print('远程文件已经下载完毕，任务结束')
                        return
                block_size=1024 #每次传输数据的数据块的大小
                local_file_size_current=local_file_size #定义为目前本地文件的大小
                print('RETR '+remote_file_name,local_file_size)
                conn=self.transfercmd('RETR '+remote_file_name,local_file_size) #开始续传,从指定位置开始下载数据，第二个参数说明现在的文件位置
                while 1:
                        data_current=conn.recv(block_size) #接收数据块
                        with open(local_path, 'ab') as fp:
                            print(data_current)
                            fp.write(data_current)
                        print('数据下载中...')
                        if not data_current:  #没有数据块被接收则结束
                            break
                        local_file_size_current+=len(data_current) #更新本地现有文件大小
                        if (local_file_size_current==remote_file_size):
                            print('传输完成')
                            conn.close()
                            break
                self.quit()

def test():
    ftp=my_FTP()
    loginfo=ftp.ftp_login('127.0.0.1','8821','username','password')
    ftp.ftp_download('127.0.0.1','8821','username','password','/home/huxley/pytest/ftpclient-master/1','/home/huxley/pytest/ftpclient-master/2',loginfo)

test()


