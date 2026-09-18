"""
分辨率切换器 — Windows 显示分辨率 / 刷新率 设置工具

功能:
    * 列出所有已连接显示器
    * 列出显卡驱动支持的全部分辨率 / 刷新率，一键应用
    * 自定义输入任意 宽 x 高 @ 刷新率（驱动支持的才能生效）
    * 「测试 15 秒」：应用后倒计时，不确认自动还原，防止黑屏
    * 一键恢复启动时的原始分辨率

    * 列表里没有的分辨率 → 自动添加到虚拟显示器（Virtual Display Driver）并切换
    * 物理 NVIDIA 显示器 → 通过 NVAPI 创建自定义分辨率
    * 首次运行可一键安装虚拟显示器驱动（内置）

源码运行: python src/app.py     打包: build.bat
"""

import ctypes
import ctypes.wintypes as wt
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import nvcustom
except Exception:
    nvcustom = None
try:
    import vdd
except Exception:
    vdd = None
try:
    import vdd_install
except Exception:
    vdd_install = None

APP_VERSION = "1.0.0"

user32 = ctypes.windll.user32

# ---------------------------------------------------------------------------
# Win32 常量 / 结构体
# ---------------------------------------------------------------------------

ENUM_CURRENT_SETTINGS = -1
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
DM_DISPLAYFREQUENCY = 0x00400000
DM_BITSPERPEL = 0x00040000

CDS_TEST = 0x00000002
CDS_UPDATEREGISTRY = 0x00000001

DISP_CHANGE_SUCCESSFUL = 0
DISP_CHANGE_RESTART = 1
DISP_CHANGE_FAILED = -1
DISP_CHANGE_BADMODE = -2
DISP_CHANGE_NOTUPDATED = -3
DISP_CHANGE_BADFLAGS = -4
DISP_CHANGE_BADPARAM = -5
DISP_CHANGE_BADDUALVIEW = -6

DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x00000001
DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004

CHANGE_MSG = {
    DISP_CHANGE_SUCCESSFUL: "成功",
    DISP_CHANGE_RESTART: "需要重启电脑才能生效",
    DISP_CHANGE_FAILED: "显示驱动拒绝了该模式",
    DISP_CHANGE_BADMODE: "显卡驱动不支持该分辨率/刷新率",
    DISP_CHANGE_NOTUPDATED: "无法写入注册表",
    DISP_CHANGE_BADFLAGS: "参数标志无效",
    DISP_CHANGE_BADPARAM: "参数无效",
    DISP_CHANGE_BADDUALVIEW: "多显示器模式不允许",
}


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", wt.WCHAR * 32),
        ("dmSpecVersion", wt.WORD),
        ("dmDriverVersion", wt.WORD),
        ("dmSize", wt.WORD),
        ("dmDriverExtra", wt.WORD),
        ("dmFields", wt.DWORD),
        ("dmPositionX", ctypes.c_long),
        ("dmPositionY", ctypes.c_long),
        ("dmDisplayOrientation", wt.DWORD),
        ("dmDisplayFixedOutput", wt.DWORD),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wt.WCHAR * 32),
        ("dmLogPixels", wt.WORD),
        ("dmBitsPerPel", wt.DWORD),
        ("dmPelsWidth", wt.DWORD),
        ("dmPelsHeight", wt.DWORD),
        ("dmDisplayFlags", wt.DWORD),
        ("dmDisplayFrequency", wt.DWORD),
        ("dmICMMethod", wt.DWORD),
        ("dmICMIntent", wt.DWORD),
        ("dmMediaType", wt.DWORD),
        ("dmDitherType", wt.DWORD),
        ("dmReserved1", wt.DWORD),
        ("dmReserved2", wt.DWORD),
        ("dmPanningWidth", wt.DWORD),
        ("dmPanningHeight", wt.DWORD),
    ]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("DeviceName", wt.WCHAR * 32),
        ("DeviceString", wt.WCHAR * 128),
        ("StateFlags", wt.DWORD),
        ("DeviceID", wt.WCHAR * 128),
        ("DeviceKey", wt.WCHAR * 128),
    ]


user32.EnumDisplayDevicesW.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.POINTER(DISPLAY_DEVICEW), wt.DWORD]
user32.EnumDisplaySettingsW.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.POINTER(DEVMODEW)]
user32.ChangeDisplaySettingsExW.argtypes = [wt.LPCWSTR, ctypes.POINTER(DEVMODEW), wt.HWND, wt.DWORD, wt.LPVOID]
user32.ChangeDisplaySettingsExW.restype = ctypes.c_long


# ---------------------------------------------------------------------------
# 显示器操作
# ---------------------------------------------------------------------------

def list_monitors():
    """返回 [(设备名 如 \\\\.\\DISPLAY1, 描述, 是否主屏)]"""
    out = []
    i = 0
    while True:
        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(dd)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
            break
        if dd.StateFlags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP:
            # 再查一层拿到显示器本身的名字（比显卡名直观）
            mon = DISPLAY_DEVICEW()
            mon.cb = ctypes.sizeof(mon)
            desc = dd.DeviceString
            if user32.EnumDisplayDevicesW(dd.DeviceName, 0, ctypes.byref(mon), 0) and mon.DeviceString:
                desc = mon.DeviceString
            out.append((dd.DeviceName, desc, bool(dd.StateFlags & DISPLAY_DEVICE_PRIMARY_DEVICE)))
        i += 1
    return out


def current_mode(dev):
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(dm)
    if user32.EnumDisplaySettingsW(dev, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
        return dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency, dm.dmBitsPerPel
    return None


def list_modes(dev):
    """驱动支持的所有 (宽, 高, 刷新率)，只取 32 位色，去重后按大小降序"""
    modes = set()
    i = 0
    while True:
        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(dm)
        if not user32.EnumDisplaySettingsW(dev, i, ctypes.byref(dm)):
            break
        if dm.dmBitsPerPel == 32:
            modes.add((dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency))
        i += 1
    return sorted(modes, key=lambda m: (m[0] * m[1], m[0], m[2]), reverse=True)


def set_mode(dev, width, height, hz=0, test_only=False):
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(dm)
    dm.dmPelsWidth = width
    dm.dmPelsHeight = height
    dm.dmBitsPerPel = 32
    dm.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT | DM_BITSPERPEL
    if hz:
        dm.dmDisplayFrequency = hz
        dm.dmFields |= DM_DISPLAYFREQUENCY
    flags = CDS_TEST if test_only else CDS_UPDATEREGISTRY
    return user32.ChangeDisplaySettingsExW(dev, ctypes.byref(dm), None, flags, None)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("分辨率切换器")
        self.resizable(False, False)
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        self.monitors = list_monitors()
        self.original = {dev: current_mode(dev) for dev, _, _ in self.monitors}
        self._countdown_job = None
        self._nv_trial = None

        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self, padding=12)
        frm.grid()

        # 显示器选择
        ttk.Label(frm, text="显示器:").grid(row=0, column=0, sticky="w", **pad)
        self.mon_var = tk.StringVar()
        self.mon_cb = ttk.Combobox(frm, textvariable=self.mon_var, state="readonly", width=42)
        self.mon_cb["values"] = [
            f"{desc}  ({dev.replace(chr(92), '')}){'  [主屏]' if prim else ''}"
            for dev, desc, prim in self.monitors
        ]
        self.mon_cb.grid(row=0, column=1, columnspan=3, sticky="w", **pad)
        self.mon_cb.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        # 当前模式
        self.cur_lbl = ttk.Label(frm, text="", foreground="#555")
        self.cur_lbl.grid(row=1, column=0, columnspan=4, sticky="w", **pad)

        # 支持的模式列表
        ttk.Label(frm, text="可用模式（双击应用；绿色 = 自定义添加，右键可删除）:").grid(row=2, column=0, columnspan=4, sticky="w", **pad)
        lst_frame = ttk.Frame(frm)
        lst_frame.grid(row=3, column=0, columnspan=4, sticky="we", padx=8)
        self.tree = ttk.Treeview(lst_frame, columns=("res", "hz"), show="headings", height=12)
        self.tree.heading("res", text="分辨率")
        self.tree.heading("hz", text="刷新率")
        self.tree.column("res", width=200, anchor="center")
        self.tree.column("hz", width=120, anchor="center")
        sb = ttk.Scrollbar(lst_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-1>", lambda e: self.apply_selected())
        self.tree.bind("<<TreeviewSelect>>", self.fill_from_selection)
        self.tree.bind("<Button-3>", self._tree_menu)

        # 自定义输入
        ttk.Separator(frm).grid(row=4, column=0, columnspan=4, sticky="we", pady=8)
        ttk.Label(frm, text="自定义:").grid(row=5, column=0, sticky="w", **pad)
        box = ttk.Frame(frm)
        box.grid(row=5, column=1, columnspan=3, sticky="w", **pad)
        self.w_var, self.h_var, self.hz_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        ttk.Entry(box, textvariable=self.w_var, width=7, justify="center").pack(side="left")
        ttk.Label(box, text=" × ").pack(side="left")
        ttk.Entry(box, textvariable=self.h_var, width=7, justify="center").pack(side="left")
        ttk.Label(box, text="  @ ").pack(side="left")
        ttk.Entry(box, textvariable=self.hz_var, width=5, justify="center").pack(side="left")
        ttk.Label(box, text=" Hz  (刷新率留空=自动)").pack(side="left")
        ttk.Label(frm, text="输入任意分辨率点「应用」：列表里没有的会自动添加到虚拟显示器并切换",
                  foreground="#888").grid(row=8, column=0, columnspan=4, sticky="w", padx=8)

        # 按钮
        btns = ttk.Frame(frm)
        btns.grid(row=6, column=0, columnspan=4, pady=(10, 0))
        ttk.Button(btns, text="应用", command=self.apply_custom, width=12).pack(side="left", padx=4)
        ttk.Button(btns, text="测试 15 秒", command=lambda: self.apply_custom(test=True), width=12).pack(side="left", padx=4)
        ttk.Button(btns, text="恢复原始", command=self.restore, width=12).pack(side="left", padx=4)
        ttk.Button(btns, text="刷新列表", command=self.refresh, width=12).pack(side="left", padx=4)

        self.status = ttk.Label(frm, text="", foreground="#0a7")
        self.status.grid(row=7, column=0, columnspan=4, sticky="w", **pad)

        # 菜单：虚拟显示器驱动 安装/卸载
        menubar = tk.Menu(self)
        drv = tk.Menu(menubar, tearoff=0)
        drv.add_command(label="安装虚拟显示器驱动", command=self.install_vdd)
        drv.add_command(label="卸载虚拟显示器驱动", command=self.uninstall_vdd)
        drv.add_separator()
        drv.add_command(label="打开配置文件夹", command=self.open_config_dir)
        menubar.add_cascade(label="虚拟显示器", menu=drv)
        helpm = tk.Menu(menubar, tearoff=0)
        helpm.add_command(label="关于", command=self.about)
        menubar.add_cascade(label="帮助", menu=helpm)
        self.config(menu=menubar)

        if self.monitors:
            idx = next((i for i, m in enumerate(self.monitors) if m[2]), 0)
            self.mon_cb.current(idx)
            self.refresh()
        else:
            messagebox.showerror("错误", "未检测到显示器")
            self.destroy()
            return

        self.after(300, self._first_run_check)

    # --- 虚拟显示器驱动 安装 / 卸载 ------------------------------------------

    def about(self):
        messagebox.showinfo(
            "关于",
            f"分辨率切换器 v{APP_VERSION}\n\n"
            "· 切换显示器分辨率 / 刷新率\n"
            "· 输入任意分辨率自动添加到虚拟显示器\n"
            "· 物理 NVIDIA 显示器支持 NVAPI 自定义分辨率\n\n"
            "虚拟显示器驱动: Virtual Display Driver (MIT)\n"
            "https://github.com/VirtualDrivers/Virtual-Display-Driver")

    def open_config_dir(self):
        if vdd_install and os.path.isdir(vdd_install.TARGET_DIR):
            os.startfile(vdd_install.TARGET_DIR)
        else:
            messagebox.showinfo("提示", "虚拟显示器驱动尚未安装。")

    def _first_run_check(self):
        if vdd is None or vdd_install is None or vdd.installed():
            return
        if messagebox.askyesno(
                "安装虚拟显示器驱动",
                "未检测到虚拟显示器驱动。\n\n"
                "安装后可以输入任意分辨率（如 3300×1300）直接使用，\n"
                "特别适合远程桌面 / 无显示器主机 / 串流。\n\n"
                "驱动为开源的 Virtual Display Driver，安装只需几秒。\n"
                "现在安装吗？（以后也可在「虚拟显示器」菜单里安装）"):
            self.install_vdd()

    def install_vdd(self):
        if vdd_install is None:
            return
        if not vdd_install.is_admin():
            messagebox.showerror("需要管理员权限", "请以管理员身份重新运行本程序。")
            return
        if vdd.installed():
            messagebox.showinfo("已安装", "虚拟显示器驱动已经安装。")
            return
        try:
            vdd_install.install(lambda m: (self.status.config(text=m), self.update_idletasks()))
        except Exception as e:
            messagebox.showerror("安装失败", str(e))
            self.status.config(text="")
            return
        self.after(3000, lambda: (self._reload_monitors(), self.refresh(),
                                  self.status.config(text="虚拟显示器已安装，现在可以输入任意分辨率了")))

    def uninstall_vdd(self):
        if vdd_install is None:
            return
        if not vdd_install.is_admin():
            messagebox.showerror("需要管理员权限", "请以管理员身份重新运行本程序。")
            return
        if not messagebox.askyesno("确认", "卸载虚拟显示器驱动？\n如果当前正通过它显示画面，屏幕会切回其他显示器。"):
            return
        try:
            vdd_install.uninstall(lambda m: (self.status.config(text=m), self.update_idletasks()))
        except Exception as e:
            messagebox.showerror("卸载失败", str(e))
            return
        self.after(3000, lambda: (self._reload_monitors(), self.refresh(), self.status.config(text="已卸载")))

    # --- helpers ---------------------------------------------------------

    @property
    def dev(self):
        return self.monitors[self.mon_cb.current()][0]

    def refresh(self):
        cur = current_mode(self.dev)
        if cur:
            self.cur_lbl.config(text=f"当前: {cur[0]} × {cur[1]} @ {cur[2]} Hz")
            self.w_var.set(cur[0]); self.h_var.set(cur[1]); self.hz_var.set(cur[2])
        self.tree.delete(*self.tree.get_children())
        custom = {(w, h) for w, h, _ in (vdd.list_res() if vdd and vdd.installed() else [])}
        for w, h, hz in list_modes(self.dev):
            tags = []
            if cur and (w, h, hz) == cur[:3]:
                tags.append("cur")
            if (w, h) in custom:
                tags.append("vdd")
            self.tree.insert("", "end", values=(f"{w} × {h}", f"{hz} Hz"), tags=tuple(tags))
        self.tree.tag_configure("cur", background="#d8efff")
        self.tree.tag_configure("vdd", foreground="#0a7")

    def fill_from_selection(self, _=None):
        sel = self.tree.selection()
        if not sel:
            return
        res, hz = self.tree.item(sel[0], "values")
        w, h = res.split(" × ")
        self.w_var.set(w); self.h_var.set(h); self.hz_var.set(hz.split()[0])

    def read_custom(self):
        try:
            w, h = int(self.w_var.get()), int(self.h_var.get())
            hz = int(self.hz_var.get()) if self.hz_var.get().strip() else 0
            if w < 320 or h < 240 or w > 16384 or h > 16384:
                raise ValueError
            return w, h, hz
        except ValueError:
            messagebox.showwarning("输入无效", "请输入合法的宽、高（320~16384）和刷新率")
            return None

    # --- actions ---------------------------------------------------------

    def apply_selected(self):
        self.fill_from_selection()
        self.apply_custom()

    def apply_custom(self, test=False):
        vals = self.read_custom()
        if not vals:
            return
        w, h, hz = vals
        self._cancel_countdown()

        # 先用 CDS_TEST 探测，避免真的切到一个驱动不支持的模式
        r = set_mode(self.dev, w, h, hz, test_only=True)
        if r != DISP_CHANGE_SUCCESSFUL:
            self._bad_mode(w, h, hz, r)
            return

        before = current_mode(self.dev)
        r = set_mode(self.dev, w, h, hz)
        if r != DISP_CHANGE_SUCCESSFUL:
            self._bad_mode(w, h, hz, r)
            return

        self.refresh()
        if test:
            self._start_countdown(before, 15)
        else:
            self.status.config(text=f"已应用 {w} × {h} @ {hz or '自动'} Hz")

    def _bad_mode(self, w, h, hz, code):
        msg = CHANGE_MSG.get(code, f"未知错误 {code}")
        if code in (DISP_CHANGE_BADMODE, DISP_CHANGE_FAILED):
            # 驱动没有这个模式 → 虚拟显示器直接加；物理 NVIDIA 显示器走 NVAPI
            if self._vdd_add_custom(w, h, hz or 60):
                return
            if self._nvidia_add_custom(w, h, hz or 60):
                return
        messagebox.showerror("无法应用", f"{w} × {h} @ {hz or '自动'} Hz\n{msg}")
        self.status.config(text="")

    # ---- 虚拟显示器（Virtual Display Driver）自定义分辨率 ----------------------

    def _vdd_add_custom(self, w, h, hz) -> bool:
        """写入 vdd_settings.xml → 重启虚拟显示器 → 切换过去。成功处理返回 True。"""
        if vdd is None or not vdd.installed():
            return False
        self.status.config(text=f"正在把 {w} × {h} @ {hz} Hz 添加到虚拟显示器…")
        self.update_idletasks()
        try:
            vdd.add(w, h, hz)
        except Exception as e:
            messagebox.showerror("写入配置失败", str(e))
            return True
        if not vdd.restart_device():
            messagebox.showerror("重启虚拟显示器失败", "需要管理员权限。请在 UAC 弹窗中点「是」，或以管理员身份运行本程序。")
            return True
        self.status.config(text="虚拟显示器重启中，等待新分辨率出现…")
        self.update_idletasks()
        dev = vdd.wait_for_mode(list_monitors, list_modes, w, h, hz)
        if not dev:
            messagebox.showwarning("超时", "虚拟显示器已重启，但没等到新分辨率出现。\n可稍后点「刷新列表」再试。")
            self._reload_monitors()
            self.refresh()
            return True
        self._reload_monitors(select=dev)
        r = set_mode(dev, w, h, hz)
        self.refresh()
        if r == DISP_CHANGE_SUCCESSFUL:
            self.status.config(text=f"已添加并切换到 {w} × {h} @ {hz} Hz")
        else:
            self.status.config(text=f"已添加，但切换失败: {CHANGE_MSG.get(r, r)}")
        return True

    def _reload_monitors(self, select=None):
        """重启设备后显示器编号可能变化，重新枚举"""
        self.monitors = list_monitors()
        self.mon_cb["values"] = [
            f"{desc}  ({dev.replace(chr(92), '')}){'  [主屏]' if prim else ''}"
            for dev, desc, prim in self.monitors
        ]
        for dev, _, _ in self.monitors:
            self.original.setdefault(dev, current_mode(dev))
        idx = 0
        for i, m in enumerate(self.monitors):
            if (select and m[0] == select) or (not select and m[2]):
                idx = i
                break
        if self.monitors:
            self.mon_cb.current(idx)

    def _tree_menu(self, e):
        row = self.tree.identify_row(e.y)
        if not row or "vdd" not in self.tree.item(row, "tags"):
            return
        self.tree.selection_set(row)
        res, _ = self.tree.item(row, "values")
        w, h = (int(x) for x in res.split(" × "))
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label=f"从虚拟显示器删除 {w} × {h}", command=lambda: self._vdd_remove(w, h))
        menu.tk_popup(e.x_root, e.y_root)

    def _vdd_remove(self, w, h):
        cur = current_mode(self.dev)
        if cur and (cur[0], cur[1]) == (w, h):
            messagebox.showwarning("无法删除", "当前正在使用这个分辨率，请先切换到其他分辨率。")
            return
        if not messagebox.askyesno("确认", f"删除自定义分辨率 {w} × {h}？"):
            return
        vdd.remove(w, h)
        self.status.config(text="已删除，正在重启虚拟显示器…")
        self.update_idletasks()
        vdd.restart_device()
        self.after(3000, lambda: (self._reload_monitors(), self.refresh(), self.status.config(text="已删除")))

    # ---- 物理 NVIDIA 显示器：NVAPI 自定义分辨率 -----------------------------

    def _nvidia_add_custom(self, w, h, hz) -> bool:
        """用 NVAPI 创建自定义分辨率（= NVIDIA 控制面板的「自定义分辨率」）。成功处理返回 True。"""
        if nvcustom is None:
            return False
        try:
            nv = nvcustom.NvApi()
            did = nv.display_id(self.dev)
        except Exception as e:
            messagebox.showerror(
                "无法创建自定义分辨率",
                f"{w} × {h} @ {hz} Hz 不在驱动支持列表中。\n\n"
                f"尝试通过 NVIDIA 驱动创建失败：{e}\n\n"
                "当前显示器不是接在 NVIDIA 显卡上的物理显示器，\n"
                "且未检测到虚拟显示器驱动。")
            return True
        if not messagebox.askyesno(
                "创建自定义分辨率",
                f"驱动没有 {w} × {h} @ {hz} Hz。\n\n"
                "是否通过 NVIDIA 驱动创建该自定义分辨率？\n"
                "屏幕会立刻切换过去试用 15 秒：\n"
                "  • 画面正常 → 按 Enter 保存\n"
                "  • 黑屏/花屏 → 等待或按 Esc 自动还原"):
            return True
        try:
            timing = nv.get_timing(did, w, h, float(hz), nvcustom.TIMING_CVT_RB)
            cd = nv.build_custom(w, h, timing)
            nv.try_custom(did, cd)
        except Exception as e:
            messagebox.showerror("创建失败", f"NVIDIA 驱动拒绝了该分辨率：\n{e}")
            return True
        self._nv_trial = (nv, did)
        self._countdown_before = None
        self._countdown_left = 15
        self._tick_countdown()
        return True

    def _start_countdown(self, before, secs):
        self._countdown_before = before
        self._countdown_left = secs
        self._tick_countdown()

    def _tick_countdown(self):
        if self._countdown_left <= 0:
            self._revert()
            return
        self.status.config(text=f"测试中… {self._countdown_left} 秒后自动还原（按 Enter 保留，Esc 立即还原）")
        self.bind("<Return>", lambda e: self._keep())
        self.bind("<Escape>", lambda e: self._revert())
        self._countdown_left -= 1
        self._countdown_job = self.after(1000, self._tick_countdown)

    def _cancel_countdown(self):
        if self._countdown_job:
            self.after_cancel(self._countdown_job)
            self._countdown_job = None
        self.unbind("<Return>"); self.unbind("<Escape>")

    def _keep(self):
        self._cancel_countdown()
        trial = getattr(self, "_nv_trial", None)
        if trial:
            nv, did = trial
            self._nv_trial = None
            try:
                nv.save_custom(did)
                self.refresh()
                self.status.config(text="自定义分辨率已保存到 NVIDIA 驱动")
            except Exception as e:
                messagebox.showerror("保存失败", str(e))
            return
        self.status.config(text="已保留新设置")

    def _revert(self):
        self._cancel_countdown()
        trial = getattr(self, "_nv_trial", None)
        if trial:
            nv, did = trial
            self._nv_trial = None
            try:
                nv.revert_trial(did)
            except Exception:
                pass
            self.refresh()
            self.status.config(text="已取消试用并还原")
            return
        b = getattr(self, "_countdown_before", None)
        if b:
            set_mode(self.dev, b[0], b[1], b[2])
        self.refresh()
        self.status.config(text="已还原")

    def restore(self):
        self._cancel_countdown()
        o = self.original.get(self.dev)
        if o:
            r = set_mode(self.dev, o[0], o[1], o[2])
            self.refresh()
            self.status.config(text="已恢复启动时的分辨率" if r == 0 else CHANGE_MSG.get(r, str(r)))


def _ensure_admin():
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return
    except Exception:
        return
    if "--no-elevate" in sys.argv:
        return
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, "--no-elevate"
    else:
        exe = sys.executable.replace("python.exe", "pythonw.exe")
        params = f'"{os.path.abspath(__file__)}" --no-elevate'
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    if r > 32:
        sys.exit(0)   # 提权成功，退出当前普通权限实例


if __name__ == "__main__":
    _ensure_admin()
    App().mainloop()
