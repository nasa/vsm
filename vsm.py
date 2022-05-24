#!/usr/bin/env python3

# The name of the Python executable and which version of Python it invokes is
# not standardized, making a shebang unreliable. We therefore try `python3`
# first and then fall back to `python`.
# See https://www.python.org/dev/peps/pep-0394/

"""":
if type python3 > /dev/null 2>&1
then
    exec python3 "$0" "$@"
else
    exec python "$0" "$@"
fi
exit 1
""" #"

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, urlencode
from urllib.request import urlopen
from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement
from xml.dom import minidom
from zeroconf import InterfaceChoice, ServiceBrowser, Zeroconf
import ast
import ifaddr
import inspect
import json
import logging
import operator
import os
import socket
import struct
import sys
import traceback

vsm_home = os.path.dirname(os.path.abspath(inspect.getsourcefile(lambda:0)))
wcs_port = 8080

def ip2int(address):
    return struct.unpack(">L", socket.inet_aton(address))[0]

def send_wcs_command(command, host='localhost', port=wcs_port):
    page = urlopen('http://' + str(host) + ':' + str(port) + '/command',
                   urlencode({'edge_command': command}).encode('utf-8'))
    return ElementTree.fromstring(page.read()).find('result').text

def is_headless(host='localhost', port=wcs_port):
    return float(send_wcs_command('doug.cmd get_fps', host, port)) == 0

def get_client_count(host='localhost', port=wcs_port):
    return int(send_wcs_command('get_global_var wcs_num_clients', host, port))

def get_cameras(host='localhost', port=wcs_port):
    return tuple(send_wcs_command('doug.scene get -cameras', host, port).split())

def get_update(host='localhost', port=wcs_port):
    command = """
        set result "\["
        foreach view [doug.display get -views] {
            set view [lindex [split $view '.'] end]
            if {[string first "HIDE" [split [doug.view $view get -flags]]] == -1} {
                append result '[doug.view $view get -camera]',
            }
        }
        return "[get_global_var wcs_num_clients], $result]"
    """
    return ast.literal_eval(send_wcs_command(command, host, port))

def get_views(host='localhost', port=wcs_port):
    return [view.split('.')[1] for view in send_wcs_command('doug.display get -views', host, port).split()]

def is_view_visible(view, host='localhost', port=wcs_port):
    result = send_wcs_command('doug.view ' + view + ' get -flags', host, port)
    return not result or 'HIDE' not in result

def get_camera(view, host='localhost', port=wcs_port):
    return send_wcs_command('doug.view ' + view + ' get -camera', host, port)

def set_camera(camera, host='localhost', port=wcs_port):
    command = """
        foreach view [doug.display get -views] {
            set view [lindex [split $view '.'] end]
            if {[string first "HIDE" [split [doug.view $view get -flags]]] == -1} {
                doug.view $view set -camera %s
                return
            }
        }
    """
    logging.info('Commanding {}:{} to render "{}"'.format(host, port, camera))
    send_wcs_command(command % camera, host, port)

class WebCommandingServer(object):

    def __init__(self, addresses, port):
        self.addresses = [socket.inet_ntoa(address) for address in addresses]
        try:
            self.hostname = socket.gethostbyaddr(self.addresses[0])[0]
        except socket.herror as e:
            self.hostname = e.strerror
        self.port = port
        self.views = []
        self.cameras = []
        self.rendered_cameras = []
        self.num_clients = 'unsupported'

    def initialize(self):
        self.views = get_views(self.addresses[0], self.port)
        self.cameras = get_cameras(self.addresses[0], self.port)
        self.update()

    def update(self):
        self.num_clients, self.rendered_cameras = get_update(self.addresses[0], self.port)

    # addresses is sorted on each call to get_camera_url
    def get_video_url(self):
        return 'http://' + self.addresses[0] + ':' + str(self.port) + '/video'

    def set_camera(self, camera):
        set_camera(camera, self.addresses[0], self.port)

    def is_headless(self):
        return is_headless(self.addresses[0], self.port)

    def update_service():
        pass

class RequestHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        logging.debug('%s - %s' % (self.client_address[0], format%args))

    def do_GET(self):
        request = urlparse(self.path)

        if request.path.endswith('.xsl'):
            return self.send_xsl_page(request.path)

        if request.path == '/':
            return self.send_landing_page()

        if request.path == '/status':
            return self.send_status_page()

        if request.path == '/streams':
            return self.send_streams_page()

        if request.path.startswith('/streams/'):
            return self.send_stream(request)

        return self.send_error(404)

    def send_landing_page(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write('<a href="status">status</a></br>'.encode('utf-8'))
        self.wfile.write('<a href="streams">streams</a>'.encode('utf-8'))

    def send_status_page(self):
        self.server.check_headless_servers()
        self.send_response(200)
        self.end_headers()
        root = Element('web_commanding_servers')
        for key, servers in self.server.web_commanding_servers.items():
            group = SubElement(root, 'group', type=key)
            for wcs in servers.values():
                try:
                    wcs.update()
                except:
                    pass
                wcs_element = SubElement(group, 'wcs', port=str(wcs.port), num_clients=str(wcs.num_clients))
                for address in wcs.addresses:
                    SubElement(wcs_element, 'address', host=socket.getfqdn(address), ip=address)
                for camera in wcs.cameras:
                    SubElement(wcs_element, 'camera', rendered=str(camera in wcs.rendered_cameras)).text = camera
        self.send_xml(root, 'status')

    def send_streams_page(self):
        self.send_response(200)
        self.end_headers()
        root = Element('streams')

        for streams in {wcs.cameras for wcs in self.server.web_commanding_servers['Active'].values()}:
            stream_set = SubElement(root, 'set')
            for stream in streams:
                SubElement(stream_set, 'stream', url=self.path + '/' + stream).text = stream
        self.send_xml(root, 'streams')

    def send_xml(self, root, stylesheet):
        xml = minidom.parseString(ElementTree.tostring(root))
        stylesheet = xml.createProcessingInstruction(
            'xml-stylesheet', 'type="text/xsl" href="xsl/' + stylesheet + '.xsl"')
        xml.insertBefore(stylesheet, xml.firstChild)
        self.wfile.write(xml.toprettyxml(encoding='utf8'))

    def send_stream(self, request):
        exists, url = self.server.get_camera_url(request.path[9:], ip2int(self.client_address[0]))

        if not exists:
            self.send_error(404, 'No such camera exists')
            return

        if not url:
            self.send_error(503,
                'This camera is temporarily unavailable because all EDGE '
                'clients capable of rendering it are already rendering '
                'different cameras for other clients')
            return

        if request.query:
            url += '?' + request.query
        self.send_response(307)
        self.send_header('Location', url)
        self.end_headers()
        logging.info('Redirecting to {}'.format(url))

    def send_xsl_page(self, path):
        try:
            xsl = open(vsm_home + os.sep + path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(xsl.read().encode('utf8'))
        except Exception as e:
            self.send_error(404, str(e))

class VideoStreamManager(HTTPServer):

    def __init__(self, config_file=None):
        # default configuration
        self.configuration = {'interfaces': InterfaceChoice.All,
                              'log_file': vsm_home + os.sep + 'log.txt',
                              'port': 12345}

        # overwrite defaults with config file contents
        if config_file:
            with open(config_file) as config_json:
                self.configuration.update(json.load(config_json))
                # in case the port was specified as a string
                self.configuration['port'] = int(self.configuration['port'])

        # This isn't in the initial assignment because the presence of a whitelist
        # causes any blacklist to be ignored, which would make it impossible to
        # specify only a blacklist in the config file.
        if 'whitelist' not in self.configuration and 'blacklist' not in self.configuration:
            self.configuration['whitelist'] = 'localhost'

        logging.basicConfig(
          filename=self.configuration['log_file'], level=logging.DEBUG,
          format='[%(asctime)s.%(msecs)03d %(levelname)s] %(message)s',
          datefmt='%m/%d/%Y %I:%M:%S')

        for machine_list in ['whitelist', 'blacklist']:
            if machine_list in self.configuration:
                if isinstance(self.configuration[machine_list], str):
                    self.configuration[machine_list] = self.resolve_name(self.configuration[machine_list])
                else:
                    self.configuration[machine_list] = set([entry
                        for name in self.configuration[machine_list]
                        for entry in self.resolve_name(name)])

        HTTPServer.__init__(self, ('0.0.0.0', self.configuration['port']), RequestHandler)
        self.web_commanding_servers = {'Active': {}, 'Incompatible': {}, 'Blacklisted': {}, 'Headless': {}}
        self.browser = ServiceBrowser(Zeroconf(self.configuration['interfaces']), '_doug_wcs._tcp.local.', self)
        logging.info('VSM running at http://{}:{}'.format(*self.server_address))
        self.serve_forever()

    def resolve_name(self, name):
        if name == 'localhost' or socket.gethostbyname(name) == '127.0.0.1':
            return set([ip.ip
                for adapter in ifaddr.get_adapters()
                for ip in adapter.ips
                if isinstance(ip.ip, str)])
        return [socket.gethostbyname(name)]

    def is_blacklisted(self, wcs):
        if 'whitelist' in self.configuration:
            return all(address not in self.configuration['whitelist'] for address in wcs.addresses)
        return 'blacklist' in self.configuration and any(address in self.configuration['blacklist'] for address in wcs.addresses)

    def add_service(self, zeroconf, service, name):
        info = zeroconf.get_service_info(service, name)
        if info:
            wcs = WebCommandingServer(info.addresses, info.port)
            if self.is_blacklisted(wcs):
                key = 'Blacklisted'
            else:
                try:
                    wcs.initialize()
                    if wcs.is_headless():
                        key = 'Headless'
                    else:
                        key = 'Active'
                except:
                    key = 'Incompatible'
                    logging.error(traceback.format_exc())
            self.web_commanding_servers[key][name] = wcs
            logging.info('Found {} {} @ {}:{}'.format(key, name, wcs.addresses[0], wcs.port))
        else:
            logging.error('Failed to retrieve service information for ' + name)

    def remove_service(self, zeroconf, service, name):
        for servers in self.web_commanding_servers.values():
            servers.pop(name, None)
        logging.info('Lost {}'.format(name))

    def check_headless_servers(self):
        for name, wcs in self.web_commanding_servers['Headless'].items():
            try:
                if (not wcs.is_headless()):
                    del self.web_commanding_servers['Headless'][name]
                    self.web_commanding_servers['Active'][name] = wcs
                    logging.info('Moved {} @ {}:{} from Headless to Active'
                      .format(name, wcs.address, wcs.port))
            except:
                self.remove_service(None, None, name)

    def update_web_commanding_servers(self):
        self.check_headless_servers()
        for name, wcs in self.web_commanding_servers['Active'].items():
            try:
                wcs.update()
            except:
                self.remove_service(None, None, name)

    def get_camera_url(self, camera, client_address):
        self.update_web_commanding_servers()

        # Find servers with the camera
        servers = [wcs for wcs in self.web_commanding_servers['Active'].values()
                   if camera in wcs.cameras]

        # No such camera exists
        if not servers:
            return False, None

        # Filter out multi-view servers
        servers = [wcs for wcs in servers if len(wcs.rendered_cameras) == 1]

        # Camera exists, but no server can render it individually
        if not servers:
            return True, None

        # Sort each WCS's address list by how closely they match the client's address
        def rank(address):
            return len(bin(ip2int(address) ^ client_address))

        for wcs in servers:
            wcs.addresses.sort(key=rank)

        # Sort servers by number of clients (negated to cause descending order),
        # then by length of address mismatch
        servers.sort(key=lambda server: (-server.num_clients, rank(wcs.addresses[0])))

        # Look for servers already rendering the camera
        rendering_servers = [wcs for wcs in servers if camera in wcs.rendered_cameras]

        # Return the server, if any, with the most clients
        if rendering_servers:
            return True, rendering_servers[0].get_video_url()

        # No servers are currently rendering the camera. Return the first server
        # with no clients
        for wcs in servers:
            if not wcs.num_clients:
                wcs.set_camera(camera)
                return True, wcs.get_video_url()

        # All servers are busy rendering different cameras for other clients.
        # The requested camera cannot be rendered at this time.
        return True, None

    def update_service():
        pass
            

if __name__ == '__main__':
    try:
        if len(sys.argv) > 1:
            VideoStreamManager(sys.argv[1])
        else:
            VideoStreamManager()
    except Exception as e:
        sys.stdout.write('[Video Stream Manager] Failed to start: ')
        print(e)
        logging.error(traceback.format_exc())
