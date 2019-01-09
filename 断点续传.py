from ftp import FTP
import sys    
import os.path

##在FTP的基础上实现。
##先补充FTPLIB里有我们没实现的FTP模块
##ftp_login用于connect和login
##ftp_download用于从远程服务器下载数据，其中实现断点续传
##！！老哥们，我在test的时候不知道为什么connect不上，求帮助。因为这个原因debug不了后面。。。里面肯定还有不少bug。。。
    
class my_FTP(FTP):    
        def __init__(self):
            print("A FTP is established.")
        ##补充我们没有实现的FTP模块
        def cwd(self, dirname):
            if dirname == '..':
                try:
                    return self.voidcmd('CDUP')
                except error_perm as msg:
                    if msg.args[0][:3] != '500':
                        raise
            elif dirname == '':
                dirname = '.'  # does nothing, but could return error
            cmd = 'CWD ' + dirname
            return self.voidcmd(cmd)
        
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
                    conn, sockaddr = sock.accept()
                    if self.timeout is not _GLOBAL_DEFAULT_TIMEOUT:
                        conn.settimeout(self.timeout)
            if resp[:3] == '150':
                # this is conditional in case we received a 125
                size = parse150(resp)
            return conn, size
        
        def transfercmd(self, cmd, rest=None):
            """Like ntransfercmd() but returns only the socket."""
            return self.ntransfercmd(cmd, rest)[0]
        
        ##与服务器连接并登陆
        def ftp_login(self,host_ip,host_port,username,password):
                ftp=my_FTP()
                try:  
                    ftp.connect(host_ip,host_port,timeout=100)  
                except :
                    print('连接失败')
                    return [0,'failed']   
                try:    
                    ftp.login(user=username,passwd=password)    
                except:
                    print('用户名或密码错误')
                    return [0,'failed']  
                return [1,ftp]
	
        def ftp_download(self,remote_host_ip,remote_port,username,password,remote_path,local_path):    
                loginfo=self.ftp_login(remote_host_ip,remote_port,username,password)    
                if(loginfo[0]!=1):
                        sys.exit()	  
                ftp=loginfo[1]
                ftp.set_pasv(0) #设置为主动模式
                root_position=remote_path.rfind('/')
                remote_path_root=remote_path[:root_position+1]
                if remote_path_root:
                        ftp.cwd(remote_path_root)   # 如果文件不在FTP根目录，就指定其他目录 
                remote_file_name=remote_path[root_position+1:]     #获取远程文件名
                remote_file_size=ftp.size(remote_file_name)    
                if remote_file_size==0 : #远程文件大小为0则返回
                        return  
                local_file_size=0
                if os.path.exists(local_path):    #表示本地路径已经存在，即文件已经下载了一部分了
                        local_file_size=os.stat(local_path).st_size #如果本地已经有文件则读取本地文件的大小   
                if local_file_size == remote_file_size:    #如果两个文件大小相当则表示已经下载完了
                        print('远程文件已经下载完毕，任务结束')    
                        return
                ftp.sendcmd('TYPE A') #规定为ASCII模式
                block_size=1024 #每次传输数据的数据块的大小
                local_file_size_current=local_file_size #定义为目前本地文件的大小
                conn=ftp.transfercmd('RETR '+remote_file_name,local_file_size) #开始续传,从指定位置开始下载数据，第二个参数说明剩下的需要传的文件长度
                while 1:
                        data_current=conn.recv(block_size) #接收数据块
                        if not data_current:  #没有数据块被接收则结束
                                break 
                        local_file_size_current+=len(data_current) #更新本地现有文件大小
                        print('下载已完成:%f%'%(float(local_file_size_current)/remote_file_size*100))
                conn.close()
                ftp.quit()
def test():
    ftp=my_FTP()
    ftp.ftp_login('127.0.0.1','21','','') 
    ftp.ftp_download('127.0.0.1','21','','','/remote','/local/local_file') 

test()
