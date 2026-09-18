"""
nvcustom.py — 通过 NVAPI 直接给 NVIDIA 显卡添加自定义分辨率
（等价于 NVIDIA 控制面板 → 更改分辨率 → 自定义 → 创建自定义分辨率）

流程: try_custom() 先试用 → 用户确认 → save_custom() 永久保存；不确认则 revert_trial()。
保存后该分辨率会出现在 Windows 的可用模式列表里，之后可以正常切换。
"""

import ctypes
from ctypes import c_uint32, c_uint16, c_uint8, c_float, c_char, c_void_p, POINTER, byref

# ---- NVAPI 函数 ID -----------------------------------------------------------
_ID = {
    "Initialize": 0x0150E828,
    "GetErrorMessage": 0x6C2D048C,
    "DISP_GetDisplayIdByDisplayName": 0xAE457190,
    "DISP_GetTiming": 0x175167E9,
    "DISP_TryCustomDisplay": 0x1F7DB630,
    "DISP_SaveCustomDisplay": 0x49882876,
    "DISP_RevertCustomDisplayTrial": 0xCBBD40F0,
    "DISP_EnumCustomDisplay": 0xA2072D59,
    "DISP_DeleteCustomDisplay": 0x552E9B9E,
}

NVAPI_OK = 0
NV_FORMAT_A8R8G8B8 = 21

# NV_TIMING_OVERRIDE 枚举
TIMING_CURRENT, TIMING_AUTO, TIMING_EDID, TIMING_DMT, TIMING_DMT_RB, TIMING_CVT, TIMING_CVT_RB, TIMING_GTF = range(8)


# ---- 结构体（与 nvapi.h 一致，自然对齐） ---------------------------------------
class NV_TIMINGEXT(ctypes.Structure):
    _fields_ = [("flag", c_uint32), ("rr", c_uint16), ("rrx1k", c_uint32), ("aspect", c_uint32),
                ("rep", c_uint16), ("status", c_uint32), ("name", c_uint8 * 40)]


class NV_TIMING(ctypes.Structure):
    _fields_ = [("HVisible", c_uint16), ("HBorder", c_uint16), ("HFrontPorch", c_uint16),
                ("HSyncWidth", c_uint16), ("HTotal", c_uint16), ("HSyncPol", c_uint8),
                ("VVisible", c_uint16), ("VBorder", c_uint16), ("VFrontPorch", c_uint16),
                ("VSyncWidth", c_uint16), ("VTotal", c_uint16), ("VSyncPol", c_uint8),
                ("interlaced", c_uint16), ("pclk", c_uint32), ("etc", NV_TIMINGEXT)]


class NV_TIMING_INPUT(ctypes.Structure):
    _fields_ = [("version", c_uint32), ("width", c_uint32), ("height", c_uint32),
                ("rr", c_float), ("flag", c_uint32), ("type", c_uint32)]


class NV_VIEWPORTF(ctypes.Structure):
    _fields_ = [("x", c_float), ("y", c_float), ("w", c_float), ("h", c_float)]


class NV_CUSTOM_DISPLAY(ctypes.Structure):
    _fields_ = [("version", c_uint32), ("width", c_uint32), ("height", c_uint32), ("depth", c_uint32),
                ("colorFormat", c_uint32), ("srcPartition", NV_VIEWPORTF),
                ("xRatio", c_float), ("yRatio", c_float), ("timing", NV_TIMING),
                ("hwModeSetOnly", c_uint32, 1)]


def _ver(struct, v):
    return ctypes.sizeof(struct) | (v << 16)


NV_TIMING_INPUT_VER = _ver(NV_TIMING_INPUT, 1)
NV_CUSTOM_DISPLAY_VER = _ver(NV_CUSTOM_DISPLAY, 1)


class NvapiError(Exception):
    pass


class NvApi:
    def __init__(self):
        try:
            self._dll = ctypes.WinDLL("nvapi64.dll")
        except OSError:
            raise NvapiError("未找到 nvapi64.dll — 需要 NVIDIA 显卡和驱动")
        qi = self._dll.nvapi_QueryInterface
        qi.restype = c_void_p
        qi.argtypes = [c_uint32]
        self._qi = qi
        self._fn = {}
        self._call("Initialize", ctypes.CFUNCTYPE(ctypes.c_int))

    def _get(self, name, proto):
        if name not in self._fn:
            addr = self._qi(_ID[name])
            if not addr:
                raise NvapiError(f"驱动不支持 NvAPI_{name}")
            self._fn[name] = proto(addr)
        return self._fn[name]

    def _call(self, name, proto, *args):
        r = self._get(name, proto)(*args)
        if r != NVAPI_OK:
            raise NvapiError(f"NvAPI_{name} 失败: {self.error_message(r)} ({r})")
        return r

    def error_message(self, code):
        buf = ctypes.create_string_buffer(64)
        try:
            self._get("GetErrorMessage", ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_char_p))(code, buf)
            return buf.value.decode(errors="ignore") or str(code)
        except Exception:
            return str(code)

    # ---- 公开 API ------------------------------------------------------------

    def display_id(self, gdi_name: str) -> int:
        """'\\\\.\\DISPLAY1' → NVAPI displayId"""
        did = c_uint32()
        self._call("DISP_GetDisplayIdByDisplayName",
                   ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, POINTER(c_uint32)),
                   gdi_name.encode("ascii"), byref(did))
        return did.value

    def get_timing(self, display_id: int, width: int, height: int, hz: float, kind=TIMING_AUTO) -> NV_TIMING:
        """让驱动按标准（CVT-RB / 自动）算出该分辨率的显示时序"""
        ti = NV_TIMING_INPUT(version=NV_TIMING_INPUT_VER, width=width, height=height, rr=hz, flag=0, type=kind)
        t = NV_TIMING()
        self._call("DISP_GetTiming",
                   ctypes.CFUNCTYPE(ctypes.c_int, c_uint32, POINTER(NV_TIMING_INPUT), POINTER(NV_TIMING)),
                   display_id, byref(ti), byref(t))
        return t

    def build_custom(self, width, height, timing: NV_TIMING) -> NV_CUSTOM_DISPLAY:
        cd = NV_CUSTOM_DISPLAY()
        cd.version = NV_CUSTOM_DISPLAY_VER
        cd.width, cd.height, cd.depth = width, height, 32
        cd.colorFormat = NV_FORMAT_A8R8G8B8
        cd.srcPartition = NV_VIEWPORTF(0.0, 0.0, 1.0, 1.0)
        cd.xRatio = cd.yRatio = 1.0
        cd.timing = timing
        cd.hwModeSetOnly = 0
        return cd

    def try_custom(self, display_id: int, cd: NV_CUSTOM_DISPLAY):
        """立即切换到该自定义分辨率（试用，未保存）"""
        ids = (c_uint32 * 1)(display_id)
        self._call("DISP_TryCustomDisplay",
                   ctypes.CFUNCTYPE(ctypes.c_int, POINTER(c_uint32), c_uint32, POINTER(NV_CUSTOM_DISPLAY)),
                   ids, 1, byref(cd))

    def revert_trial(self, display_id: int):
        ids = (c_uint32 * 1)(display_id)
        self._call("DISP_RevertCustomDisplayTrial",
                   ctypes.CFUNCTYPE(ctypes.c_int, POINTER(c_uint32), c_uint32), ids, 1)

    def save_custom(self, display_id: int):
        """把试用中的自定义分辨率永久保存到驱动"""
        ids = (c_uint32 * 1)(display_id)
        self._call("DISP_SaveCustomDisplay",
                   ctypes.CFUNCTYPE(ctypes.c_int, POINTER(c_uint32), c_uint32, c_uint32, c_uint32),
                   ids, 1, 0, 0)

    def enum_custom(self, display_id: int):
        """列出驱动里已保存的自定义分辨率"""
        out = []
        i = 0
        fn = self._get("DISP_EnumCustomDisplay",
                       ctypes.CFUNCTYPE(ctypes.c_int, c_uint32, c_uint32, POINTER(NV_CUSTOM_DISPLAY)))
        while True:
            cd = NV_CUSTOM_DISPLAY(version=NV_CUSTOM_DISPLAY_VER)
            if fn(display_id, i, byref(cd)) != NVAPI_OK:
                break
            out.append((cd.width, cd.height, cd.timing.etc.rr))
            i += 1
        return out

    def delete_custom(self, display_id: int, index: int):
        ids = (c_uint32 * 1)(display_id)
        self._call("DISP_DeleteCustomDisplay",
                   ctypes.CFUNCTYPE(ctypes.c_int, POINTER(c_uint32), c_uint32, c_uint32),
                   ids, 1, index)


def timing_str(t: NV_TIMING) -> str:
    return (f"{t.HVisible}x{t.VVisible} pclk={t.pclk / 100:.2f}MHz "
            f"HTotal={t.HTotal} VTotal={t.VTotal} rr={t.etc.rr} rrx1k={t.etc.rrx1k}")
