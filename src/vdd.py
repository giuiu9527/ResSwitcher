"""
vdd.py — 管理 Virtual Display Driver 的自定义分辨率
读写 C:\\VirtualDisplayDriver\\vdd_settings.xml，并重启虚拟显示器让配置生效。
"""

import ctypes
import os
import subprocess
import time
import xml.etree.ElementTree as ET

XML_PATH = r"C:\VirtualDisplayDriver\vdd_settings.xml"
DEVICE_ID = r"ROOT\MTTVDD\0000"
MONITOR_TAG = "MTT1337"          # 虚拟显示器的 PnP ID 特征


def installed() -> bool:
    """配置文件存在且虚拟显示器设备已创建"""
    if not os.path.exists(XML_PATH):
        return False
    try:
        r = subprocess.run(["pnputil", "/enum-devices", "/instanceid", DEVICE_ID], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0 and b"MTTVDD" in r.stdout.upper()
    except Exception:
        return False


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def list_res():
    """返回 [(w, h, hz)]"""
    if not installed():
        return []
    root = ET.parse(XML_PATH).getroot()
    out = []
    for r in root.findall("./resolutions/resolution"):
        try:
            out.append((int(r.findtext("width")), int(r.findtext("height")), int(r.findtext("refresh_rate"))))
        except (TypeError, ValueError):
            pass
    return out


def _save(tree):
    tmp = XML_PATH + ".tmp"
    tree.write(tmp, encoding="utf-8", xml_declaration=True)
    os.replace(tmp, XML_PATH)


def add(w: int, h: int, hz: int = 60) -> bool:
    """加入配置；已存在返回 False"""
    tree = ET.parse(XML_PATH)
    res = tree.getroot().find("resolutions")
    for r in res.findall("resolution"):
        if (r.findtext("width"), r.findtext("height"), r.findtext("refresh_rate")) == (str(w), str(h), str(hz)):
            return False
    node = ET.SubElement(res, "resolution")
    ET.SubElement(node, "width").text = str(w)
    ET.SubElement(node, "height").text = str(h)
    ET.SubElement(node, "refresh_rate").text = str(hz)
    node.tail = "\n        "
    _save(tree)
    return True


def remove(w: int, h: int) -> int:
    """删除该宽高的所有条目，返回删除数量"""
    tree = ET.parse(XML_PATH)
    res = tree.getroot().find("resolutions")
    n = 0
    for r in list(res.findall("resolution")):
        if (r.findtext("width"), r.findtext("height")) == (str(w), str(h)):
            res.remove(r)
            n += 1
    if n:
        _save(tree)
    return n


def restart_device() -> bool:
    """重启虚拟显示器设备使配置生效（需要管理员；非管理员时弹 UAC）"""
    if is_admin():
        r = subprocess.run(["pnputil", "/restart-device", DEVICE_ID], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        return r.returncode in (0, 3010)
    # ShellExecuteEx runas 并等待结束
    SEE_MASK_NOCLOSEPROCESS = 0x40

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("fMask", ctypes.c_ulong), ("hwnd", ctypes.c_void_p),
                    ("lpVerb", ctypes.c_wchar_p), ("lpFile", ctypes.c_wchar_p), ("lpParameters", ctypes.c_wchar_p),
                    ("lpDirectory", ctypes.c_wchar_p), ("nShow", ctypes.c_int), ("hInstApp", ctypes.c_void_p),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", ctypes.c_wchar_p), ("hkeyClass", ctypes.c_void_p),
                    ("dwHotKey", ctypes.c_ulong), ("hIcon", ctypes.c_void_p), ("hProcess", ctypes.c_void_p)]

    sei = SHELLEXECUTEINFOW()
    sei.cbSize = ctypes.sizeof(sei)
    sei.fMask = SEE_MASK_NOCLOSEPROCESS
    sei.lpVerb = "runas"
    sei.lpFile = "pnputil.exe"
    sei.lpParameters = f'/restart-device "{DEVICE_ID}"'
    sei.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        return False
    ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, 60000)
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(sei.hProcess)
    return code.value in (0, 3010)


def wait_for_mode(list_monitors, list_modes, w, h, hz, timeout=20):
    """重启后轮询：等虚拟显示器重新出现且带有该模式，返回其设备名或 None"""
    end = time.time() + timeout
    while time.time() < end:
        for dev, desc, prim in list_monitors():
            modes = list_modes(dev)
            if any(m[0] == w and m[1] == h and (not hz or m[2] == hz) for m in modes):
                return dev
        time.sleep(1)
    return None
