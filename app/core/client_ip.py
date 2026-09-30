"""
Client IP Resolution & Proxy Topology Module.

Safely extracts client IP addresses across Cloudflare edge, Railway origin,
local development, and test environments.

HARD SECURITY INVARIANT:
Never blindly trust client-supplied headers (such as CF-Connecting-IP, X-Forwarded-For,
or caller-supplied headers) without verifying that the upstream peer observed by Railway
belongs to an authenticated, trusted proxy network.

Production Request Flow:
Client (End User)
  ↓
Cloudflare Edge Proxy (IP in CLOUDFLARE_NETWORKS)
  ↓
Railway Edge / Ingress Proxy (Envoy)
  ↓
FastAPI / Uvicorn (app.core.client_ip)

Documented Platform Guarantees:
- Railway Edge explicitly documents `X-Real-IP` as identifying the client's remote IP
  seen by Railway.
- Cloudflare documents `CF-Connecting-IP` as the visitor IP delivered from Cloudflare to origin.
- We DO NOT rely on undocumented assumptions about Railway's internal X-Forwarded-For hop sequencing.
- If a request arrived through Cloudflare, Railway's documented `X-Real-IP` is an authentic
  Cloudflare edge node. In that case, Cloudflare has already validated and set
  `CF-Connecting-IP`, which we trust.
- If a request arrived directly at the Railway origin domain (*.up.railway.app),
  Railway's `X-Real-IP` is the direct caller's remote IP (NOT Cloudflare). Any `CF-Connecting-IP`
  sent by the caller is untrusted/forged and MUST BE DISCARDED. Quotas are bound to `X-Real-IP`.
"""

import ipaddress
import logging
from typing import Optional
from fastapi import Request

logger = logging.getLogger("app.security.client_ip")

# Official Cloudflare IP CIDRs (https://www.cloudflare.com/ips/)
CLOUDFLARE_IPV4_CIDRS = (
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
)

CLOUDFLARE_IPV6_CIDRS = (
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
)

CLOUDFLARE_NETWORKS = [
    ipaddress.ip_network(cidr) for cidr in (*CLOUDFLARE_IPV4_CIDRS, *CLOUDFLARE_IPV6_CIDRS)
]

# RFC 1918, loopback, CGNAT, and private IPv6 networks used by internal proxies / Docker / Railway
INTERNAL_PROXY_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # Carrier-grade NAT / Railway private wireguard
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local
    ipaddress.ip_network("fc00::/7"),  # IPv6 Unique Local
    ipaddress.ip_network("::1/128"),  # IPv6 Loopback
)


def parse_ip_safe(ip_str: Optional[str]) -> Optional[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """
    Parses a string into an IPv4Address or IPv6Address, stripping ports if present.
    Returns None if invalid.
    """
    if not ip_str:
        return None
    raw = ip_str.strip()
    if not raw:
        return None

    # Strip port if format is "ip:port" (IPv4) or "[ipv6]:port"
    if raw.startswith("[") and "]" in raw:
        raw = raw[1 : raw.index("]")]
    elif ":" in raw and raw.count(":") == 1:
        raw = raw.split(":")[0]

    try:
        return ipaddress.ip_address(raw)
    except ValueError:
        return None


def is_cloudflare_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """
    Checks if an IP address belongs to the official Cloudflare IP ranges.
    """
    for net in CLOUDFLARE_NETWORKS:
        if ip_obj in net:
            return True
    return False


def is_internal_proxy_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """
    Checks if an IP address belongs to internal proxy/container networks.
    """
    for net in INTERNAL_PROXY_NETWORKS:
        if ip_obj in net:
            return True
    return False


def extract_client_ip(request: Request) -> str:
    """
    Extracts the authenticated or safe client IP address from a FastAPI/Starlette Request.

    Resolution Strategy based on Documented Platform Guarantees:
    1. Read Railway-controlled `X-Real-IP` as the Railway-observed remote peer.
    2. Validate `X-Real-IP` syntactically.
    3. If `X-Real-IP` belongs to an official Cloudflare network (`CLOUDFLARE_NETWORKS`):
       - Request legitimately arrived at Railway from Cloudflare.
       - Accept `CF-Connecting-IP` ONLY if it contains a valid IP.
       - Use `CF-Connecting-IP` as the rate-limit client identity.
       - If `CF-Connecting-IP` is missing or malformed, fallback safely to `str(real_ip_obj)`.
    4. If `X-Real-IP` is valid but NOT Cloudflare:
       - Request arrived directly at Railway origin (*.up.railway.app) or untrusted proxy.
       - Discard `CF-Connecting-IP` regardless of its value (untrusted/forged).
       - Use `str(real_ip_obj)` as the rate-limit client identity.
    5. If `X-Real-IP` is absent or malformed:
       - DO NOT trust `CF-Connecting-IP`.
       - Fallback to safest deterministic `request.client.host` (or "unknown").
    """
    x_real_ip_raw = request.headers.get("x-real-ip")
    cf_connecting_ip_raw = request.headers.get("cf-connecting-ip")

    # 1 & 2. Validate X-Real-IP syntactically
    real_ip_obj = parse_ip_safe(x_real_ip_raw)

    if real_ip_obj is not None:
        # 3. Check if X-Real-IP belongs to official Cloudflare networks
        if is_cloudflare_ip(real_ip_obj):
            # Arrived from Cloudflare: accept CF-Connecting-IP if valid
            cf_ip_obj = parse_ip_safe(cf_connecting_ip_raw)
            if cf_ip_obj is not None and not is_internal_proxy_ip(cf_ip_obj):
                return str(cf_ip_obj)
            # If CF-Connecting-IP missing or malformed, fallback to Cloudflare peer IP
            return str(real_ip_obj)
        else:
            # 4. Valid peer, but NOT Cloudflare (direct Railway origin call or other proxy).
            # Discard CF-Connecting-IP unconditionally to prevent quota evasion.
            if cf_connecting_ip_raw:
                logger.debug(
                    "Discarded untrusted CF-Connecting-IP %s from non-Cloudflare peer %s",
                    cf_connecting_ip_raw,
                    real_ip_obj,
                )
            return str(real_ip_obj)

    # 5. X-Real-IP is absent or malformed: DO NOT trust CF-Connecting-IP.
    # Safest deterministic fallback: request.client.host (local dev, testclient)
    if request.client and request.client.host:
        client_host = request.client.host.strip()
        parsed_client = parse_ip_safe(client_host)
        if parsed_client is not None:
            return str(parsed_client)
        return client_host

    return "unknown"


def mask_ip(ip_str: str) -> str:
    """
    Masks an IP address for privacy-safe logging without leaking complete user IP.
    IPv4: 203.0.113.195 -> 203.0.113.***
    IPv6: 2001:db8:85a3::8a2e:370:7334 -> 2001:db8:85a3:****
    """
    ip_obj = parse_ip_safe(ip_str)
    if ip_obj is None:
        return ip_str

    if isinstance(ip_obj, ipaddress.IPv4Address):
        octets = str(ip_obj).split(".")
        if len(octets) == 4:
            return f"{octets[0]}.{octets[1]}.{octets[2]}.***"
    elif isinstance(ip_obj, ipaddress.IPv6Address):
        hextets = str(ip_obj.exploded).split(":")
        if len(hextets) >= 4:
            return f"{hextets[0]}:{hextets[1]}:{hextets[2]}:****"

    return "***"
