from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
from operator import attrgetter
from socket import inet_ntoa
from urllib import urlopen, urlencode
from urlparse import urlparse, parse_qs
from xml.etree import ElementTree
from zeroconf import zeroconf
from zeroconf.zeroconf import ServiceBrowser, Zeroconf

wcs_port = 8080

def send_wcs_command(command, host='localhost', port=wcs_port):
    page = urlopen('http://' + str(host) + ':' + str(port) + '/command',
                   urlencode({'edge_command': command}))
    return ElementTree.fromstring(page.read()).find('result').text

def get_client_count(host='localhost', port=wcs_port):
    return int(send_wcs_command('get_global_var wcs_num_clients', host, port))

def get_cameras(host='localhost', port=wcs_port):
    return tuple(send_wcs_command('doug.scene get -cameras', host, port).split())

def get_views(host='localhost', port=wcs_port):
    return [view.split('.')[1] for view in send_wcs_command('doug.display get -views', host, port).split()]

def is_view_visible(view, host='localhost', port=wcs_port):
    result = send_wcs_command('doug.view ' + view + ' get -flags', host, port)
    return not result or 'HIDE' not in result

def get_camera(view, host='localhost', port=wcs_port):
    return send_wcs_command('doug.view ' + view + ' get -camera', host, port)

def set_camera(view, camera, host='localhost', port=wcs_port):
    send_wcs_command('doug.view ' + view + ' set -camera ' + camera, host, port)

class WebCommandingServer(object):
    def __init__(self, address, port):
        self.address = inet_ntoa(address)
        self.port = port
        self.video_address = 'http://' + self.address + ':' + str(self.port) + '/video'
        self.cameras = get_cameras(self.address, port)
        self.views = get_views(self.address, port)
        self.update()

    def update(self):
        self.num_clients = get_client_count(self.address, self.port)
        self.visible_cameras = [self.get_camera(view) for view in self.views
                                if self.is_view_visible(view)]

    def is_view_visible(self, view):
        return is_view_visible(view, self.address, self.port)

    def get_camera(self, view):
        return get_camera(view, self.address, self.port)

    def set_camera(self, camera):
        for view in self.views:
            if self.is_view_visible(view):
                set_camera(view, camera, self.address, self.port)
                return

class VideoStreamManager(HTTPServer):

    class RequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            request = urlparse(self.path)

            if request.path != '/':
                self.send_error(404)
                return

            if not request.query:
                return self.send_status_page()

            query = parse_qs(request.query)

            try:
                stream = query['stream'][0]
            except:
                self.send_error(400, 'Query string must contain "stream=". For example: <address>?stream=camera1')
                return

            exists, wcs = self.server.get_wcs_for_camera(stream)

            if not exists:
                self.send_error(404, 'No such camera exists')
                return

            if not wcs:
                self.send_error(503, 'This camera is unavailable because all EDGE clients capable of rendering it are already rendering a different camera for another client')
                return

            redirect = wcs.video_address
            query.pop('stream')
            if query:
                redirect += '?' + urlencode(query, doseq=True)
            self.send_response(307)
            self.send_header('Location', redirect)
            self.end_headers()

        def get_link_for_camera(self, camera):
            return '<a href="' + self.path + '?' + urlencode({'stream': camera}) + '">' + camera + '<a><br/>'

        def send_status_page(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write('<html><head><title>Video Stream Manager</title></head><body>')
            camera_sets = set()
            for cameras in {wcs.cameras for wcs in self.server.web_commanding_servers.values()}:
                self.wfile.write('<p>')
                for camera in cameras:
                    self.wfile.write(self.get_link_for_camera(camera))
                self.wfile.write('</p>')
            self.wfile.write('</body></html>')

    def __init__(self, port=12345):
        HTTPServer.__init__(self, ('localhost', port), self.RequestHandler)
        self.web_commanding_servers = {}
        self.browser = ServiceBrowser(Zeroconf(), '_doug_wcs._tcp.local.', self)
        self.serve_forever()

    def __del__(self):
        browser.close()

    def add_service(self, zeroconf, service, name):
        info = zeroconf.get_service_info(service, name)
        if info:
            self.web_commanding_servers[name] = WebCommandingServer(info.address, info.port)
            print 'Added ' + name

    def remove_service(self, zeroconf, service, name):
        try:
            self.web_commanding_servers.pop(name)
            print 'Removed ' + name
        except:
            pass

    def update_web_commanding_servers(self):
        for _, wcs in self.web_commanding_servers.iteritems():
            wcs.update()

    def get_wcs_for_camera(self, camera):
        self.update_web_commanding_servers()

        # Find servers with the camera
        servers = [wcs for wcs in self.web_commanding_servers.values() if camera in wcs.cameras]

        # No such camera exists
        if not servers:
            return False, None

        # Filter out multi-view servers
        servers = [wcs for wcs in servers if len(wcs.visible_cameras) == 1]

        # Camera exists, but no server can render it individually
        if not servers:
            return True, None

        # Look for servers already rendering the camera, sorted descendingly
        # by number of clients
        rendering_servers = sorted(
            [wcs for wcs in servers if camera in wcs.visible_cameras],
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
    VideoStreamManager()
