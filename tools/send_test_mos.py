#!/usr/bin/env python3
"""Send a fake roCreate + roStoryReplace to the gateway (like Blaze would) and print replies.
Usage: python3 send_test_mos.py [host] [port]"""
import socket, sys
host, port = (sys.argv[1] if len(sys.argv) > 1 else "localhost"), int(sys.argv[2] if len(sys.argv) > 2 else 10541)
def send(s, xml):
    s.sendall(xml.encode("utf-16-be")); data = b""
    s.settimeout(3)
    try:
        while not data.decode("utf-16-be", "ignore").endswith("</mos>"): data += s.recv(65536)
    except socket.timeout: pass
    print(data.decode("utf-16-be", "ignore"), "\n")
H = "<mosID>AUTOID.LINKER.MOS</mosID><ncsID>BLAZE.NCS</ncsID><messageID>%d</messageID>"
with socket.create_connection((host, port)) as s:
    send(s, "<mos>%s<heartbeat><time>2026-10-20T10:00:00</time></heartbeat></mos>" % (H % 1))
    send(s, "<mos>%s<roCreate><roID>RO1</roID><roSlug>Evening Bulletin</roSlug>"
            "<story><storyID>S1</storyID><storySlug>Vijay scheme launch</storySlug></story>"
            "<story><storyID>S2</storyID><storySlug>Chennai rain</storySlug></story></roCreate></mos>" % (H % 2))
    send(s, "<mos>%s<roStoryReplace><roID>RO1</roID><storyID>S1</storyID>"
            "<story><storyID>S1</storyID><storySlug>Vijay scheme (edited)</storySlug></story></roStoryReplace></mos>" % (H % 3))
