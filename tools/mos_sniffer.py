#!/usr/bin/env python3
"""Passive MOS sniffer for spike S1. Prints/logs every MOS message Blaze sends. Never replies.
Usage: python3 mos_sniffer.py [port ...]  (default 10540 10541)"""
import codecs, datetime, socketserver, sys, threading
PORTS = [int(p) for p in sys.argv[1:]] or [10540, 10541]
def ts(): return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def out(text):
    print(text, flush=True)
    with open("mos_capture.log", "a", encoding="utf-8") as f: f.write(text + "\n")
class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        peer = "%s:%s" % self.client_address; port = self.server.server_address[1]
        out("[%s] connect %s -> port %d" % (ts(), peer, port))
        dec = codecs.getincrementaldecoder("utf-16-be")(errors="replace"); buf = ""
        while True:
            data = self.request.recv(65536)
            if not data: break
            buf += dec.decode(data)
            while "</mos>" in buf:
                msg, buf = buf.split("</mos>", 1)
                out("[%s] %s port %d\n%s</mos>\n" % (ts(), peer, port, msg.strip()))
        out("[%s] disconnect %s" % (ts(), peer))
class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True; daemon_threads = True
if __name__ == "__main__":
    for p in PORTS:
        threading.Thread(target=Server(("0.0.0.0", p), Handler).serve_forever, daemon=True).start(); out("[%s] listening on %d" % (ts(), p))
    threading.Event().wait()
