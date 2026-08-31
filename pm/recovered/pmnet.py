"""Polymarket network helper.

Igor's ISP sinkholes *.polymarket.com -> 195.80.107.145 (verified still active 2026-08-30).
Fix: pin a Cloudflare edge IP by patching socket.getaddrinfo, while leaving the hostname
intact so SNI + cert validation still work normally.
"""
import socket
import json
import urllib.request

PIN = "104.18.34.205"
_real_getaddrinfo = socket.getaddrinfo


def _patched(host, port, *a, **k):
    if isinstance(host, str) and host.endswith("polymarket.com"):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PIN, port))]
    return _real_getaddrinfo(host, port, *a, **k)


socket.getaddrinfo = _patched

UA = {"User-Agent": "Mozilla/5.0"}


def get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def post(url, payload, timeout=20):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={**UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# Endpoints that worked in the 2026-08 session:
#   gamma-api.polymarket.com/markets, /events        (tag_slug filter works)
#   clob.polymarket.com/books  (batch POST)
#   clob.polymarket.com/rewards/markets/current
#   data-api.polymarket.com/trades  (tape, ~1000 cap, returns BOTH YES+NO tokens;
#                                    normalize NO: flip side and price -> 1-p)
