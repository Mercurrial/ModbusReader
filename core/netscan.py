# core/netscan.py
"""Find Modbus TCP devices on the local network.

Walks a range of IPv4 addresses, knocks on one TCP port (502) of each —
many at a time, every knock bounded by a short timeout — and asks every
open port one Modbus question (read holding register 0) to tell a Modbus
device from any other server. No connection of the app is needed or used:
each probe opens and closes its own socket.

    found = {"ip", "port", "state": "modbus" | "open", "unit": int | None,
             "exception": code (0 = a normal answer), "ms": connect + answer}

"modbus" means the device answered (data or an exception — both prove a
Modbus server decoded the request); "open" means the port accepts
connections but nothing answered the request (another protocol, or a
gateway with nothing behind it).

Also here: the computer's own IPv4 addresses (for the emulator's "connect
to" line) and the range of the local /24 subnet to suggest for a scan.
"""
import ipaddress
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtCore import QThread, pyqtSignal

from core.modbus_client import TcpMaster

MAX_HOSTS = 1024
PARALLEL = 64
CONNECT_S = 0.6             # a LAN device accepts in milliseconds
UNITS = (1, 255, 0)         # unit ids tried, in order


def hosts_between(first: str, last: str) -> list:
    """Every IPv4 address from *first* to *last* inclusive (either order).
    Raises ValueError for a bad address or a range over MAX_HOSTS."""
    a = ipaddress.IPv4Address(str(first).strip())
    b = ipaddress.IPv4Address(str(last).strip())
    if int(b) < int(a):
        a, b = b, a
    n = int(b) - int(a) + 1
    if n > MAX_HOSTS:
        raise ValueError(f"{n} addresses — at most {MAX_HOSTS}")
    return [str(ipaddress.IPv4Address(int(a) + i)) for i in range(n)]


def local_ipv4() -> list:
    """This computer's IPv4 addresses on real networks (no loopback, no
    link-local 169.254.x.x), the one with the default route first."""
    found = []
    try:
        # A UDP "connection" sends nothing; it only makes the OS pick the
        # interface that has the default route.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))           # TEST-NET-1, never routed
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    out = []
    for ip in found:
        try:
            addr = ipaddress.IPv4Address(ip)
        except ValueError:
            continue
        if addr.is_loopback or addr.is_link_local or addr.is_unspecified:
            continue
        if ip not in out:
            out.append(ip)
    return sorted(out, key=_lan_rank)            # stable: the default route first


def _lan_rank(ip: str) -> int:
    """How likely *ip* is the office / plant LAN rather than a virtual
    adapter: the default route is often a VPN or a Hyper-V / WSL / Docker
    switch (172.16–31.x), VirtualBox's host-only net is 192.168.56.x."""
    a = ipaddress.IPv4Address(ip)
    if a in ipaddress.IPv4Network("192.168.56.0/24"):
        return 4
    if a in ipaddress.IPv4Network("192.168.0.0/16"):
        return 0
    if a in ipaddress.IPv4Network("10.0.0.0/8"):
        return 1
    if a in ipaddress.IPv4Network("172.16.0.0/12"):
        return 2
    return 3


def subnet_range(ip: str) -> tuple:
    """(first, last) host of the /24 around *ip*, e.g. 192.168.1.1 … .254."""
    net = ipaddress.IPv4Network(f"{ip}/24", strict=False)
    return str(net.network_address + 1), str(net.broadcast_address - 1)


def suggest_range() -> tuple:
    """The local /24 subnet most likely to hold the devices."""
    ips = local_ipv4()
    return subnet_range(ips[0] if ips else "192.168.1.1")


def probe(ip: str, port: int = 502, connect_s: float = CONNECT_S,
          answer_s: float = 0.6, units=UNITS, stop=None) -> dict | None:
    """One address: None when the port is closed / nobody is there."""
    t0 = time.monotonic()
    try:
        sock = socket.create_connection((ip, int(port)), timeout=connect_s)
    except OSError:
        return None
    hit = {"ip": ip, "port": int(port), "state": "open", "unit": None,
           "exception": 0, "ms": None}
    try:
        master = TcpMaster(ip, port=port, timeout=answer_s, retries=0,
                           socket_factory=lambda *_a, **_k: sock)
        master.connect()
        for unit in units:
            if stop is not None and stop():
                break
            try:
                res = master.read_holding_registers(0, 1, device_id=unit)
            except Exception:
                break                              # the device hung up
            if res.outcome in ("ok", "exception"):
                hit.update(state="modbus", unit=unit,
                           exception=res.exception_code if res.outcome == "exception" else 0)
                break
    finally:
        try:
            sock.close()
        except OSError:
            pass
    hit["ms"] = (time.monotonic() - t0) * 1000.0
    return hit


class NetScanWorker(QThread):
    """Scans *hosts* for an open *port*; reports every hit as it comes."""

    progress = pyqtSignal(int, int)                 # done, total
    found = pyqtSignal(dict)
    finished_scan = pyqtSignal(int, int, float)     # hits, total, seconds

    def __init__(self, hosts, port: int = 502, answer_s: float = 0.6,
                 parallel: int = PARALLEL, parent=None):
        super().__init__(parent)
        self.hosts = list(hosts)
        self.port = int(port)
        self.answer_s = float(answer_s)
        self.parallel = max(1, int(parallel))
        self._stop = threading.Event()

    def request_stop(self):
        self._stop.set()

    def run(self):
        t0 = time.monotonic()
        total, done, hits = len(self.hosts), 0, 0
        stop = self._stop.is_set

        def job(ip):
            if stop():
                return None
            return probe(ip, self.port, answer_s=self.answer_s, stop=stop)

        pool = ThreadPoolExecutor(max_workers=min(self.parallel, max(1, total)),
                                  thread_name_prefix="netscan")
        try:
            futures = [pool.submit(job, ip) for ip in self.hosts]
            for fut in as_completed(futures):
                done += 1
                try:
                    hit = fut.result()
                except Exception:
                    hit = None
                if hit is not None:
                    hits += 1
                    self.found.emit(hit)
                self.progress.emit(done, total)
                if stop():
                    break
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        self.finished_scan.emit(hits, total, time.monotonic() - t0)
