"""Persistent USB serial connection identities for DigiFlot.

An RS-232 converter identifies a connection endpoint, not the physical scale
behind it. Never treat VID/PID, a numeric tty name, or a USB socket as a unique
identity for a scale.
"""
import os
import re
from pathlib import Path

from serial.tools import list_ports


def serial_inventory(ports=None, serial_root="/dev/serial"):
    """Return serial endpoints and their persistent Linux USB identifiers."""
    ports = list(list_ports.comports() if ports is None else ports)
    endpoint_links = {str(info.device): {} for info in ports}
    for folder, key in (("by-id", "usb_id"), ("by-path", "usb_path")):
        directory = Path(serial_root) / folder
        if not directory.is_dir():
            continue
        for link in sorted(directory.iterdir()):
            if not link.is_symlink():
                continue
            endpoint = os.path.realpath(link)
            if endpoint in endpoint_links and key not in endpoint_links[endpoint]:
                endpoint_links[endpoint][key] = link.name

    return [{
        "port": str(info.device),
        "description": getattr(info, "description", None),
        "manufacturer": getattr(info, "manufacturer", None),
        "adapter_serial": getattr(info, "serial_number", None),
        "interface": getattr(info, "interface", None),
        "location": getattr(info, "location", None),
        "vid": getattr(info, "vid", None),
        "pid": getattr(info, "pid", None),
        **endpoint_links[str(info.device)],
    } for info in ports]


def connection_from_port(endpoint):
    """Snapshot the endpoint; do not claim this identifies the scale itself."""
    return {key: endpoint.get(key) for key in (
        "usb_id", "usb_path", "adapter_serial", "interface",
        "vid", "pid", "last_port",
    )} | {"transport": "rs232", "last_port": endpoint["port"]}


def strong_match(connection, endpoints):
    """Match only a unique serial/interface identity, never just VID/PID."""
    if not isinstance(connection, dict):
        return None
    usb_id = connection.get("usb_id")
    if usb_id:
        matches = [item for item in endpoints if item.get("usb_id") == usb_id]
        if len(matches) == 1:
            return matches[0]
    serial = connection.get("adapter_serial")
    interface = connection.get("interface")
    vid, pid = connection.get("vid"), connection.get("pid")
    if serial and interface and vid is not None and pid is not None:
        matches = [item for item in endpoints if (
            item.get("adapter_serial") == serial and item.get("interface") == interface
            and item.get("vid") == vid and item.get("pid") == pid
        )]
        if len(matches) == 1:
            return matches[0]
    return None


def configured_endpoint_map(configs, endpoints):
    """Map known scales only to proven endpoints, not to reused tty numbers."""
    mapping, duplicates = {}, set()
    for config in configs:
        connection = config.get("connection") or {}
        strong_identity = connection.get("usb_id") or (
            connection.get("adapter_serial") and connection.get("interface")
        )
        match = strong_match(connection, endpoints) if strong_identity else None
        port = match["port"] if match else (None if strong_identity else str(config.get("port")))
        if port is None or port in duplicates:
            continue
        if port in mapping:
            duplicates.add(port)
            mapping.pop(port, None)
        else:
            mapping[port] = config
    return mapping


def resolve_runtime_ports(configs, endpoints):
    """Resolve saved sensors on boot without changing their logical IDs.

    When a known converter is missing and its old tty belongs to a different
    device, use an unavailable path rather than read a different scale.
    """
    result, claimed = {}, set()
    by_port = {item["port"]: item for item in endpoints}
    for config in configs:
        sensor_id = str(config.get("id") or config.get("port"))
        connection = config.get("connection") or {}
        match = strong_match(connection, endpoints)
        if match is not None and match["port"] not in claimed:
            result[sensor_id] = match["port"]
            claimed.add(match["port"])
        elif connection.get("usb_id") or (connection.get("adapter_serial") and connection.get("interface")):
            old_port = str(config.get("port"))
            if old_port in by_port:
                safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", sensor_id)
                result[sensor_id] = "/dev/digiflot-unresolved/" + safe_id
        elif str(config.get("port")) in by_port:
            claimed.add(str(config["port"]))
    return result
