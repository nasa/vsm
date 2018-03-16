from zeroconf import zeroconf
from zeroconf.zeroconf import ServiceBrowser, Zeroconf
from urllib import urlopen, urlencode
from xml.etree import ElementTree
import socket

rcs_port = 5451
wcs_port = 8080

def read_char(socket):
    return socket.recv(1)

def read_rcs_response(socket):
    response = ''
    char = read_char(socket)
    while (ord(char) != 4):
        response += str(char)
        char = read_char(socket)
    return response

def create_rcs_connection(host='localhost', port=rcs_port):
    connection = socket.socket()
    connection.connect((host, port))
    read_rcs_response(connection)
    return connection

def send_rcs_command(command, host='localhost', port=rcs_port):
    connection = create_rcs_connection(host, port)
    connection.sendall(command + '\n')
    return connection

def send_rcs_inquiry(command, host='localhost', port=rcs_port):
    return read_rcs_response(send_command(command, host, port))

def send_wcs_command(command, host='localhost', port=wcs_port):
    page = urlopen('http://' + str(host) + ':' + str(port) + '/command',
                   urlencode({'edge_command': command}))
    return ElementTree.fromstring(page.read()).find('result').text

def get_client_count(host='localhost', port=wcs_port):
    return int(send_wcs_command('get_global_var wcs_num_clients', host, port))

def get_cameras(host='localhost', port=wcs_port):
    return send_wcs_command('doug.scene get -cameras', host, port).split()

def set_camera(camera, host='localhost', port=wcs_port):
    send_wcs_command('doug.view [doug.display get -curview] set -camera ' + camera, host, port)

def get_input(host='localhost', port=wcs_port):
    return send_wcs_command('doug.cmd get_input', host, port)

def get_load(host='localhost', port=wcs_port):
    return send_wcs_command('doug.cmd get_load', host, port)

def get_display(host='localhost', port=wcs_port):
    return send_wcs_command('doug.cmd get_display', host, port)

def get_scene(host='localhost', port=wcs_port):
    return send_wcs_command('doug.cmd get_scene', host, port)

class WebCommandingServer(object):
    def __init__(self, address, port):
        self.address = socket.inet_ntoa(address)
        self.port = port
        self.cameras = get_cameras(self.address, port)
        self.num_clients = get_client_count(self.address, port)

    def __repr__(self):
        return str(vars(self))

class VideoStreamManager(object):

    def __init__(self):
        self.servers = {}
        ServiceBrowser(Zeroconf(), "_doug_wcs._tcp.local.", self)

    def __del__(self):
        zeroconf.close()

    def add_service(self, zeroconf, service, name):
        info = zeroconf.get_service_info(service, name)
        print "Added " + str(info)
        try:
            self.servers[name] = WebCommandingServer(info.address, info.port)
        except:
            pass

    def remove_service(self, zeroconf, service, name):
        print "Removed " + name
        del self.servers[name]

if __name__ == "__main__":
    VideoStreamManager()
