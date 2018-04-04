from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
from operator import attrgetter
from os import curdir, sep
from socket import inet_ntoa
from urllib import urlopen, urlencode, pathname2url
from urlparse import urlparse, parse_qs
from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement
from xml.dom import minidom
from zeroconf import zeroconf
from zeroconf.zeroconf import ServiceBrowser, Zeroconf
import ast
import json
import socket
import sys

wcs_port = 8080

def send_wcs_command(command, host='localhost', port=wcs_port):
    page = urlopen('http://' + str(host) + ':' + str(port) + '/command',
                   urlencode({'edge_command': command}))
    return ElementTree.fromstring(page.read()).find('result').text

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
    send_wcs_command(command % camera, host, port)

class WebCommandingServer(object):
    def __init__(self, address, port):
        self.address = inet_ntoa(address)
        self.port = port
        self.video_address = 'http://' + self.address + ':' + str(self.port) + '/video'
        self.cameras = get_cameras(self.address, port)
        self.views = get_views(self.address, port)
        self.num_clients = 'unsupported'
        self.rendered_cameras = []

    def update(self):
        self.num_clients, self.rendered_cameras = get_update(self.address, self.port)

    def is_view_visible(self, view):
        return is_view_visible(view, self.address, self.port)

    def get_camera(self, view):
        return get_camera(view, self.address, self.port)

    def set_camera(self, camera):
        set_camera(camera, self.address, self.port)

class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        request = urlparse(self.path)

        if request.path.endswith('.xsl'):
            return self.send_xsl_page(request.path)

        if request.path == '/status':
            return self.send_status_page()

        if request.path == '/streams':
            return self.send_streams_page()

        if request.path.startswith('/streams/'):
            return self.send_stream(request)

        return self.send_error(404)

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
            redirect += '?' + urlencode(query, doseq=True)
        self.send_response(307)
        self.send_header('Location', redirect)
        self.end_headers()

    def send_xsl_page(self, path):
        try:
            xsl = open(curdir + sep + path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(xsl.read())
        except Exception, e:
            self.send_error(404, str(e))

class VideoStreamManager(HTTPServer):

    def __init__(self, config_file=None):
        if config_file:
            with open(config_file) as config_json:
                self.configuration = json.load(config_json)
            if 'port' not in self.configuration:
                self.configuration['port'] = 12345
            else:
                self.configuration['port'] = int(self.configuration['port'])
        else:
            self.configuration = {'port': 12345}

        for machine_list in ['whitelist', 'blacklist']:
            if machine_list in self.configuration:
                self.configuration[machine_list] = [socket.gethostbyname(name)
                    for name in self.configuration[machine_list]]

        HTTPServer.__init__(self, ('localhost', self.configuration['port']), RequestHandler)
        self.web_commanding_servers = {'Active': {}, 'Incompatible': {}, 'Blacklisted': {}}
        self.browser = ServiceBrowser(Zeroconf(), '_doug_wcs._tcp.local.', self)
        self.serve_forever()

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

    def remove_service(self, zeroconf, service, name):
        for servers in self.web_commanding_servers.values():
            servers.pop(name, None)

    def update_web_commanding_servers(self):
        for _, wcs in self.web_commanding_servers['Active'].iteritems():
            wcs.update()

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
            key=attrgetter('num_clients'),
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
        VideoStreamManager()
