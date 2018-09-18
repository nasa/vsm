#!/usr/bin/env python

from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement
from xml.dom import minidom
from zeroconf import zeroconf
from zeroconf.zeroconf import ServiceBrowser, Zeroconf
import ast
import ifaddr
import inspect
import json
import logging
import operator
import os
import socket
import sys
import traceback
import urllib
import urlparse

vsm_home = os.path.dirname(os.path.abspath(inspect.getsourcefile(lambda:0)))

logging.basicConfig(filename=vsm_home + os.sep + 'log.txt', level=logging.DEBUG, format='[%(asctime)s.%(msecs)03d %(levelname)s] %(message)s', datefmt='%m/%d/%Y %I:%M:%S')

wcs_port = 8080

def send_wcs_command(command, host='localhost', port=wcs_port):
    page = urllib.urlopen('http://' + str(host) + ':' + str(port) + '/command',
                          urllib.urlencode({'edge_command': command}))
    return ElementTree.fromstring(page.read()).find('result').text

def get_client_count(host='localhost', port=wcs_port):
    return int(send_wcs_command('get_global_var wcs_num_clients', host, port))

def get_cameras(host='localhost', port=wcs_port):
    return tuple(send_wcs_command('doug.scene get -cameras', host, port).split())

def get_update(host='localhost', port=wcs_port):
    command = """
        set result "\["
        if [doug.cmd get_fps != 0] {
            foreach view [doug.display get -views] {
                set view [lindex [split $view '.'] end]
                if {[string first "HIDE" [split [doug.view $view get -flags]]] == -1} {
                    append result '[doug.view $view get -camera]',
                }
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

    def __init__(self, address, port):
        self.address = socket.inet_ntoa(address)
        self.port = port
        self.video_address = 'http://' + self.address + ':' + str(self.port) + '/video'
        self.cameras = get_cameras(self.address, port)
        self.views = get_views(self.address, port)
        self.num_clients = 'unsupported'
        self.rendered_cameras = []

    def update(self):
        self.num_clients, self.rendered_cameras = get_update(self.address, self.port)

    def set_camera(self, camera):
        set_camera(camera, self.address, self.port)

class RequestHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        logging.debug('%s - %s' % (self.client_address[0], format%args))

    def do_GET(self):
        request = urlparse.urlparse(self.path)

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
        self.wfile.write('<a href="status">status</a></br>')
        self.wfile.write('<a href="streams">streams</a>')

    def send_status_page(self):
        self.send_response(200)
        self.end_headers()
        root = Element('web_commanding_servers')
        for key, servers in self.server.web_commanding_servers.iteritems():
            group = SubElement(root, 'group', type=key)
            for wcs in servers.values():
                try:
                    wcs.update()
                except:
                    pass
                wcs_element = SubElement(group, 'wcs', host=socket.gethostbyaddr(wcs.address)[0], port=str(wcs.port), num_clients=str(wcs.num_clients))
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
        exists, wcs = self.server.get_wcs_for_camera(request.path[9:])

        if not exists:
            self.send_error(404, 'No such camera exists')
            return

        if not wcs:
            self.send_error(503,
                'This camera is temporarily unavailable because all EDGE '
                'clients capable of rendering it are already rendering '
                'different cameras for other clients')
            return

        redirect = wcs.video_address
        if request.query:
            redirect += '?' + request.query
        self.send_response(307)
        self.send_header('Location', redirect)
        self.end_headers()
        logging.info('Redirecting to {}'.format(wcs.video_address))

    def send_xsl_page(self, path):
        try:
            xsl = open(vsm_home + os.sep + path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(xsl.read())
        except Exception, e:
            self.send_error(404, str(e))

class VideoStreamManager(HTTPServer):

    def __init__(self, config_file=None):
        default_port = 12345
        if config_file:
            with open(config_file) as config_json:
                self.configuration = json.load(config_json)
            if 'port' not in self.configuration:
                self.configuration['port'] = default_port
            else:
                self.configuration['port'] = int(self.configuration['port'])
        else:
            self.configuration = {'port': default_port, 'whitelist': 'localhost'}

        for machine_list in ['whitelist', 'blacklist']:
            if machine_list in self.configuration:
                if isinstance(self.configuration[machine_list], (str, unicode)):
                    self.configuration[machine_list] = self.resolve_name(self.configuration[machine_list])
                else:
                    self.configuration[machine_list] = set([entry
                        for name in self.configuration[machine_list]
                        for entry in self.resolve_name(name)])

        HTTPServer.__init__(self, ('0.0.0.0', self.configuration['port']), RequestHandler)
        self.web_commanding_servers = {'Active': {}, 'Incompatible': {}, 'Blacklisted': {}}
        self.browser = ServiceBrowser(Zeroconf(), '_doug_wcs._tcp.local.', self)
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
            return wcs.address not in self.configuration['whitelist']
        return 'blacklist' in self.configuration and wcs.address in self.configuration['blacklist']

    def add_service(self, zeroconf, service, name):
        info = zeroconf.get_service_info(service, name)
        if info:
            wcs = WebCommandingServer(info.address, info.port)
            try:
                wcs.update()
                if self.is_blacklisted(wcs):
                    key = 'Blacklisted'
                else:
                    key = 'Active'
            except:
                key = 'Incompatible'
            self.web_commanding_servers[key][name] = wcs
            logging.info('Found {} {}'.format(key, name))

    def remove_service(self, zeroconf, service, name):
        for servers in self.web_commanding_servers.values():
            servers.pop(name, None)
        logging.info('Lost {}'.format(name))

    def update_web_commanding_servers(self):
        for name, wcs in self.web_commanding_servers['Active'].items():
            try:
                wcs.update()
            except:
                self.remove_service(None, None, name)

    def get_wcs_for_camera(self, camera):
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

        # Look for servers already rendering the camera, sorted descendingly
        # by number of clients
        rendering_servers = sorted(
            [wcs for wcs in servers if camera in wcs.rendered_cameras],
            key=operator.attrgetter('num_clients'),
            reverse=True)

        # Return the server, if any, with the most clients
        if rendering_servers:
            return True, rendering_servers[0]

        # No servers are currently rendering the camera. Return the first server
        # with no clients
        for wcs in servers:
            if not wcs.num_clients:
                wcs.set_camera(camera)
                return True, wcs

        # All servers are busy rendering different cameras for other clients.
        # The requested camera cannot be rendered at this time.
        return True, None

if __name__ == '__main__':
    if len(sys.argv) > 1:
        VideoStreamManager(sys.argv[1])
    else:
        try:
            VideoStreamManager()
        except Exception as e:
            sys.stdout.write('[Video Stream Manager] Failed to start: ')
            print e
            logging.error(traceback.format_exc())
