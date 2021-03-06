# Copyright 2013, 2014, 2015, 2016, 2017 Kevin Reid <kpreid@switchb.org>
# 
# This file is part of ShinySDR.
# 
# ShinySDR is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# ShinySDR is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with ShinySDR.  If not, see <http://www.gnu.org/licenses/>.

"""Code defining the API that is actually exposed over HTTP."""

from __future__ import absolute_import, division

import os
import urllib

from twisted.application.service import Service
from twisted.internet import defer
from twisted.internet import endpoints
from twisted.plugin import getPlugins
from twisted.python import log
from twisted.web import static
from twisted.web import server
from twisted.web import template
from twisted.web.resource import Resource
from twisted.web.util import Redirect
from zope.interface import Interface

import txws

import shinysdr.i.db
from shinysdr.i.ephemeris import EphemerisResource
from shinysdr.i.json import serialize
from shinysdr.i.modes import get_modes
from shinysdr.i.network.base import CAP_OBJECT_PATH_ELEMENT, SlashedResource, UNIQUE_PUBLIC_CAP, deps_path, prepath_escaped, renderElement, static_resource_path, endpoint_string_to_url, template_path
from shinysdr.i.network.export_http import BlockResource, CapAccessResource, FlowgraphVizResource
from shinysdr.i.network.export_ws import OurStreamProtocol
from shinysdr.twisted_ext import FactoryWithArgs


def not_deletable():
    # TODO audit uses of this function
    # TODO plumb up a user-friendly (proper HTTP code) error
    raise Exception('Attempt to delete session root')


class IClientResourceDef(Interface):
    """
    Client plugin interface object
    """
    # Only needed to make the plugin system work
    # TODO write interface methods anyway


def _make_static_resource(pathname):
    r = static.File(pathname,
        defaultType='text/plain',
        ignoredExts=['.html'])
    r.contentTypes['.csv'] = 'text/csv'
    r.indexNames = ['index.html']
    return r


class _RadioIndexHtmlElement(template.Element):
    loader = template.XMLFile(os.path.join(template_path, 'index.template.xhtml'))
    
    def __init__(self, wcommon, title):
        self.__wcommon = wcommon
        self.__title = unicode(title)
    
    @template.renderer
    def title(self, request, tag):
        return tag(self.__title)

    @template.renderer
    def quoted_state_url(self, request, tag):
        return tag(serialize(self.__wcommon.make_websocket_url(request, prepath_escaped(request) + CAP_OBJECT_PATH_ELEMENT)))

    @template.renderer
    def quoted_audio_url(self, request, tag):
        return tag(serialize(self.__wcommon.make_websocket_url(request, prepath_escaped(request) + 'audio')))


class _RadioIndexHtmlResource(Resource):
    isLeaf = True

    def __init__(self, wcommon, title):
        Resource.__init__(self)
        self.__element = _RadioIndexHtmlElement(wcommon, title)

    def render_GET(self, request):
        return renderElement(request, self.__element)


class WebService(Service):
    # TODO: Too many parameters
    def __init__(self, reactor, cap_table, read_only_dbs, writable_db, http_endpoint, ws_endpoint, root_cap, title, flowgraph_for_debug):
        # Constants
        self.__http_endpoint_string = http_endpoint
        self.__http_endpoint = endpoints.serverFromString(reactor, http_endpoint)
        self.__ws_endpoint = endpoints.serverFromString(reactor, ws_endpoint)
        self.__visit_path = _make_cap_url(root_cap)
        
        wcommon = WebServiceCommon(ws_endpoint_string=ws_endpoint)
        
        def BoundSessionResource(session):
            return SessionResource(session, wcommon, reactor, title, read_only_dbs, writable_db, flowgraph_for_debug)
        
        server_root = CapAccessResource(cap_table=cap_table, resource_ctor=BoundSessionResource)
        _put_root_static(server_root)
        
        if UNIQUE_PUBLIC_CAP in cap_table:
            # TODO: consider factoring out "generate URL for cap"
            server_root.putChild('', Redirect(_make_cap_url(UNIQUE_PUBLIC_CAP)))
            
        self.__ws_protocol = txws.WebSocketFactory(
            FactoryWithArgs.forProtocol(OurStreamProtocol, cap_table))
        self.__site = _SiteWithHeaders(server_root)
        
        self.__ws_port_obj = None
        self.__http_port_obj = None
    
    @defer.inlineCallbacks
    def startService(self):
        Service.startService(self)
        if self.__ws_port_obj is not None:
            raise Exception('Already started')
        self.__http_port_obj = yield self.__http_endpoint.listen(self.__site)
        self.__ws_port_obj = yield self.__ws_endpoint.listen(self.__ws_protocol)
    
    def stopService(self):
        Service.stopService(self)
        if self.__ws_port_obj is None:
            raise Exception('Not started, cannot stop')
        # TODO: Does Twisted already have something to bundle up a bunch of ports for shutdown?
        return defer.DeferredList([
            self.__http_port_obj.stopListening(),
            self.__ws_port_obj.stopListening()])
    
    def get_host_relative_url(self):
        """Get the host-relative URL of the service.
        
        This method exists primarily for testing purposes."""
        return self.__visit_path
    
    def get_url(self):
        """Get the absolute URL of the service. Cannot be used before startService is called.
        
        This method exists primarily for testing purposes."""
        # TODO: need to know canonical domain name (endpoint_string_to_url defaults to localhost); can we extract the information from the certificate when applicable?
        return endpoint_string_to_url(self.__http_endpoint_string, listening_port=self.__http_port_obj, path=self.get_host_relative_url())

    def announce(self, open_client):
        """interface used by shinysdr.main"""
        url = self.get_url()
        if open_client:
            log.msg('Opening ' + url)
            import webbrowser  # lazy load
            webbrowser.open(url, new=1, autoraise=True)
        else:
            log.msg('Visit ' + url)


def _put_root_static(container_resource):
    """Place all the simple static files."""
    
    for name in ['', 'client', 'test', 'manual', 'tools']:
        container_resource.putChild(name, _make_static_resource(os.path.join(static_resource_path, name if name != '' else 'index.html')))
    
    # Link deps into /client/.
    client = container_resource.children['client']
    for name in ['require.js', 'text.js']:
        client.putChild(name, _make_static_resource(os.path.join(deps_path, name)))
    for name in ['measviz.js', 'measviz.css']:
        client.putChild(name, _make_static_resource(os.path.join(deps_path, 'measviz/src', name)))
    
    # Link deps into /test/.
    test = container_resource.children['test']
    jasmine = SlashedResource()
    test.putChild('jasmine', jasmine)
    for name in ['jasmine.css', 'jasmine.js', 'jasmine-html.js']:
        jasmine.putChild(name, _make_static_resource(os.path.join(
            deps_path, 'jasmine/lib/jasmine-core/', name)))
    
    _put_plugin_resources(client)


def _put_plugin_resources(client_resource):
    # Plugin resources and plugin info
    load_list_css = []
    load_list_js = []
    mode_table = {}
    plugin_resources = Resource()
    client_resource.putChild('plugins', plugin_resources)
    for resource_def in getPlugins(IClientResourceDef, shinysdr.plugins):
        # Add the plugin's resource to static serving
        plugin_resources.putChild(resource_def.key, resource_def.resource)
        plugin_resource_url = '/client/plugins/' + urllib.quote(resource_def.key, safe='') + '/'
        # Tell the client to load the plugins
        # TODO constrain path values to be relative (not on a different origin, to not leak urls)
        if resource_def.load_css_path is not None:
            load_list_css.append(plugin_resource_url + resource_def.load_cs_path)
        if resource_def.load_js_path is not None:
            # TODO constrain value to be in the directory
            load_list_js.append(plugin_resource_url + resource_def.load_js_path)
    for mode_def in get_modes():
        mode_table[mode_def.mode] = {
            u'info_enum_row': mode_def.info.to_json(),
            u'can_transmit': mode_def.mod_class is not None
        }
    # Client gets info about plugins through this resource
    client_resource.putChild('plugin-index.json', static.Data(serialize({
        u'css': load_list_css,
        u'js': load_list_js,
        u'modes': mode_table,
    }).encode('utf-8'), 'application/json'))


class SessionResource(SlashedResource):
    # TODO Too many parameters; some of this stuff shouldn't be per-session in the same way
    def __init__(self, session, wcommon, reactor, title, read_only_dbs, writable_db, flowgraph_for_debug):
        SlashedResource.__init__(self)
        
        # UI entry point
        self.putChild('', _RadioIndexHtmlResource(wcommon=wcommon, title=title))
        
        # Exported radio control objects
        self.putChild(CAP_OBJECT_PATH_ELEMENT, BlockResource(session, wcommon, not_deletable))
        
        # Frequency DB
        self.putChild('dbs', shinysdr.i.db.DatabasesResource(read_only_dbs))
        self.putChild('wdb', shinysdr.i.db.DatabaseResource(writable_db))
        
        # Debug graph
        self.putChild('flow-graph', FlowgraphVizResource(reactor, flowgraph_for_debug))
        
        # Ephemeris
        self.putChild('ephemeris', EphemerisResource())


class _SiteWithHeaders(server.Site):
    """Subclass of Site which provides some default headers for all resources."""
    
    def getResourceFor(self, request):
        """overrides Site"""
        # TODO remove unsafe-inline (not that it really matters as we are not doing sloppy templating)
        # TODO: Once we know our own hostname(s), or if we start using the same port for WebSockets, tighten the connect-src policy
        request.setHeader('Content-Security-Policy', ';'.join([
            "default-src 'self' 'unsafe-inline'",
            "connect-src 'self' ws://*:* wss://*:*",
            "img-src 'self' data: blob:",
            "object-src 'none'",
            "base-uri 'self'",
            "block-all-mixed-content",
        ]))
        request.setHeader('Referrer-Policy', 'no-referrer')
        request.setHeader('X-Content-Type-Options', 'nosniff')
        return server.Site.getResourceFor(self, request)


class WebServiceCommon(object):
    """Ugly collection of stuff web resources need which is not noteworthy authority."""
    def __init__(self, ws_endpoint_string):
        self.__ws_endpoint_string = ws_endpoint_string

    def make_websocket_url(self, request, path):
        return endpoint_string_to_url(self.__ws_endpoint_string,
            hostname=request.getRequestHostname(),
            scheme='ws',
            path=path)


def _make_cap_url(cap):
    assert isinstance(cap, unicode)
    return '/' + urllib.quote(cap.encode('utf-8'), safe='') + '/'
