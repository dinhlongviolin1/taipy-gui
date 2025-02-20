# Copyright 2023 Avaiga Private Limited
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
# an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

import contextlib
import typing as t
from threading import Thread
from urllib.parse import quote as urlquote
from urllib.parse import urlparse

from twisted.internet import reactor
from twisted.web.proxy import ProxyClient, ProxyClientFactory
from twisted.web.resource import Resource
from twisted.web.server import NOT_DONE_YET, Site

from .singleton import _Singleton

if t.TYPE_CHECKING:
    from ..gui import Gui


def modifiedHandleResponseEnd(self):
    if self._finished:
        return
    self._finished = True
    with contextlib.suppress(Exception):
        self.father.finish()
    self.transport.loseConnection()


setattr(ProxyClient, "handleResponseEnd", modifiedHandleResponseEnd)


class TaipyReverseProxyResource(Resource):
    proxyClientFactoryClass = ProxyClientFactory

    def __init__(self, host, path, gui: "Gui", reactor=reactor):
        Resource.__init__(self)
        self.host = host
        self.path = path
        self.reactor = reactor
        self._gui = gui

    def getChild(self, path, request):
        return TaipyReverseProxyResource(
            self.host,
            self.path + b"/" + urlquote(path, safe=b"").encode("utf-8"),
            self._gui,
            self.reactor,
        )

    def _get_port(self):
        return self._gui._server._port

    def render(self, request):
        port = self._get_port()
        host = self.host if port == 80 else "%s:%d" % (self.host, port)
        request.requestHeaders.setRawHeaders(b"host", [host.encode("ascii")])
        request.content.seek(0, 0)
        rest = self.path + b"?" + qs if (qs := urlparse(request.uri)[4]) else self.path
        clientFactory = self.proxyClientFactoryClass(
            request.method,
            rest,
            request.clientproto,
            request.getAllHeaders(),
            request.content.read(),
            request,
        )
        self.reactor.connectTCP(self.host, port, clientFactory)
        return NOT_DONE_YET


class NotebookProxy(object, metaclass=_Singleton):
    def __init__(self, gui: "Gui", listening_port: int) -> None:
        self._listening_port = listening_port
        self._gui = gui
        self._is_running = False

    def run(self):
        if self._is_running:
            return
        self._is_running = True
        site = Site(TaipyReverseProxyResource(self._gui._get_config("host", "127.0.0.1"), b"", self._gui))
        reactor.listenTCP(self._listening_port, site)
        Thread(target=reactor.run, args=(False,)).start()

    def stop(self):
        if not self._is_running:
            return
        self._is_running = False
        reactor.stop()
