"""
vdd_install.py — 安装 / 卸载 Virtual Display Driver（等价于 devcon install MttVDD.inf Root\\MttVDD）
需要管理员权限。
"""

import ctypes
import ctypes.wintypes as wt
import os
import shutil
import subprocess
import sys

TARGET_DIR = r"C:\VirtualDisplayDriver"
HWID = "Root\\MttVDD"
DEVICE_ID = r"ROOT\MTTVDD\0000"
FILES = ("MttVDD.dll", "MttVDD.inf", "mttvdd.cat")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def bundled_driver_dir() -> str:
    """打包后驱动在 sys._MEIPASS/driver，源码运行时在 ../driver"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "driver")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "driver")


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def device_present() -> bool:
    r = subprocess.run(["pnputil", "/enum-devices", "/instanceid", DEVICE_ID],
                       capture_output=True, creationflags=NO_WINDOW)
    return r.returncode == 0 and b"MTTVDD" in r.stdout.upper()


# ---- SetupAPI ---------------------------------------------------------------

class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("ClassGuid", GUID), ("DevInst", wt.DWORD), ("Reserved", ctypes.c_void_p)]


GUID_DEVCLASS_DISPLAY = GUID(0x4D36E968, 0xE325, 0x11CE,
                             (ctypes.c_ubyte * 8)(0xBF, 0xC1, 0x08, 0x00, 0x2B, 0xE1, 0x03, 0x18))
DICD_GENERATE_ID = 0x00000001
SPDRP_HARDWAREID = 0x00000001
DIF_REGISTERDEVICE = 0x00000019
INSTALLFLAG_FORCE = 0x00000001

setupapi = ctypes.windll.setupapi
newdev = ctypes.windll.newdev
setupapi.SetupDiCreateDeviceInfoList.restype = ctypes.c_void_p
setupapi.SetupDiCreateDeviceInfoList.argtypes = [ctypes.POINTER(GUID), wt.HWND]
setupapi.SetupDiCreateDeviceInfoW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, ctypes.POINTER(GUID), wt.LPCWSTR,
                                              wt.HWND, wt.DWORD, ctypes.POINTER(SP_DEVINFO_DATA)]
setupapi.SetupDiSetDeviceRegistryPropertyW.argtypes = [ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA), wt.DWORD,
                                                       ctypes.c_void_p, wt.DWORD]
setupapi.SetupDiCallClassInstaller.argtypes = [wt.DWORD, ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA)]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
newdev.UpdateDriverForPlugAndPlayDevicesW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                                      ctypes.POINTER(wt.BOOL)]


class InstallError(Exception):
    pass


def install(progress=lambda msg: None):
    """安装驱动并创建虚拟显示器。失败抛 InstallError。"""
    if not is_admin():
        raise InstallError("需要管理员权限")
    src = bundled_driver_dir()
    for f in FILES:
        if not os.path.exists(os.path.join(src, f)):
            raise InstallError(f"缺少驱动文件 {f}")

    progress("复制驱动文件…")
    os.makedirs(TARGET_DIR, exist_ok=True)
    for f in FILES:
        shutil.copy2(os.path.join(src, f), os.path.join(TARGET_DIR, f))
    settings = os.path.join(TARGET_DIR, "vdd_settings.xml")
    if not os.path.exists(settings):
        shutil.copy2(os.path.join(src, "vdd_settings.xml"), settings)

    inf = os.path.join(TARGET_DIR, "MttVDD.inf")
    progress("加入驱动库…")
    r = subprocess.run(["pnputil", "/add-driver", inf, "/install"], capture_output=True, creationflags=NO_WINDOW)
    if r.returncode not in (0, 259, 3010):
        raise InstallError(f"pnputil /add-driver 失败 ({r.returncode})")

    if device_present():
        progress("设备已存在，跳过创建")
        return

    progress("创建虚拟显示器设备…")
    devs = setupapi.SetupDiCreateDeviceInfoList(ctypes.byref(GUID_DEVCLASS_DISPLAY), None)
    if not devs or devs == (1 << 64) - 1:
        raise InstallError("SetupDiCreateDeviceInfoList 失败 " + str(ctypes.GetLastError()))
    did = SP_DEVINFO_DATA()
    did.cbSize = ctypes.sizeof(did)
    if not setupapi.SetupDiCreateDeviceInfoW(devs, "MttVDD", ctypes.byref(GUID_DEVCLASS_DISPLAY), None, None,
                                              DICD_GENERATE_ID, ctypes.byref(did)):
        raise InstallError("SetupDiCreateDeviceInfoW 失败 " + str(ctypes.GetLastError()))
    hwid_buf = ctypes.create_unicode_buffer(HWID + "\0\0")
    if not setupapi.SetupDiSetDeviceRegistryPropertyW(devs, ctypes.byref(did), SPDRP_HARDWAREID,
                                                       ctypes.cast(hwid_buf, ctypes.c_void_p),
                                                       ctypes.sizeof(hwid_buf)):
        raise InstallError("SetupDiSetDeviceRegistryPropertyW 失败 " + str(ctypes.GetLastError()))
    if not setupapi.SetupDiCallClassInstaller(DIF_REGISTERDEVICE, devs, ctypes.byref(did)):
        raise InstallError("SetupDiCallClassInstaller 失败 " + str(ctypes.GetLastError()))
    setupapi.SetupDiDestroyDeviceInfoList(devs)

    progress("安装驱动到设备…")
    reboot = wt.BOOL(False)
    if not newdev.UpdateDriverForPlugAndPlayDevicesW(None, HWID, inf, INSTALLFLAG_FORCE, ctypes.byref(reboot)):
        raise InstallError("UpdateDriverForPlugAndPlayDevices 失败 " + str(ctypes.GetLastError()))
    progress("安装完成")


def uninstall(progress=lambda msg: None):
    if not is_admin():
        raise InstallError("需要管理员权限")
    progress("移除虚拟显示器设备…")
    subprocess.run(["pnputil", "/remove-device", DEVICE_ID], capture_output=True, creationflags=NO_WINDOW)
    # 从驱动库删除（找到发布名 oemNN.inf）
    r = subprocess.run(["pnputil", "/enum-drivers"], capture_output=True, creationflags=NO_WINDOW)
    text = r.stdout.decode("utf-8", errors="ignore") + r.stdout.decode("gbk", errors="ignore")
    blocks = text.replace("\r", "").split("\n\n")
    for b in blocks:
        if "mttvdd.inf" in b.lower():
            for line in b.splitlines():
                if "oem" in line.lower() and ".inf" in line.lower():
                    name = line.split(":")[-1].strip()
                    progress(f"删除驱动包 {name}…")
                    subprocess.run(["pnputil", "/delete-driver", name, "/uninstall", "/force"],
                                   capture_output=True, creationflags=NO_WINDOW)
                    break
    progress("卸载完成（配置文件保留在 C:\\VirtualDisplayDriver）")
