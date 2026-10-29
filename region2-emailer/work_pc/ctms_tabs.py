"""
Edge's tabs, by name - so `use ctms` / `use tracker` can bring up the tab they need (29/10).

The bridge itself never sees Edge's tab strip: its pictures are cut to the page, its clicks stay inside
the page, and the browser's own tab keys are refused there. So this picks the tab the way a screen
reader does - Windows UI Automation, built into Windows, asked through ctypes like the rest of work_pc -
and only ever a tab whose name is CTMS's (CTMS_TAB_WORDS) or the tracker's (ctms_window.PAGE_WORDS).
No other tab is selected, pictured or named back, nothing is clicked or typed to do it, and UI
Automation is told to leave the keyboard focus alone, so Edge gives the tab's own page its focus back,
as it does when the tab is clicked.

Standard library only, like everything else in work_pc\\.
"""
import os
import threading
import time

import ctms_window

IS_WIN = os.name == "nt"

# CTMS's tab by its name - the title Oracle Forms gives it ("Oracle Fusion Middleware Forms Services" on
# the work PC). Not plain "ctms": SharePoint pages, emails and the dashboard's own page say that too.
CTMS_TAB_WORDS = ("oracle fusion middleware", "forms services", "frmservlet", "calidus")
WHAT = {"ctms": "CTMS's tab", "page": "the DigiHaul Job Tracker's tab"}

# UI Automation as UIAutomationClient.h lays it out: the class, the interfaces, and the slot of each method used.
CLSID_CUIAutomation8 = "{E22AD333-B25F-460C-83D0-0581107395C9}"
IID_IUIAutomation2 = "{34723AFF-0C9D-49D0-9896-7AB52DF8CD8A}"
IID_SELECTION_ITEM = "{A8EFA66A-0FDA-421A-9194-38021F3578EA}"
IID_LEGACY = "{828055AD-355B-4435-86D5-3B51C14A9B1B}"
IID_INVOKE = "{FB377FBE-8EA6-46D5-9C73-6499642D3059}"
RELEASE = 2
UIA_ELEMENT_FROM_HANDLE, UIA_FOCUSED, UIA_CONTROL_WALKER = 6, 8, 14
UIA_GET_AUTOSETFOCUS, UIA_PUT_AUTOSETFOCUS = 58, 59
EL_PATTERN_AS, EL_CONTROL_TYPE, EL_NAME, EL_CLASS = 14, 21, 23, 30
WALK_FIRST_CHILD, WALK_NEXT = 4, 6
SELECT, DEFAULT_ACTION, INVOKE = 3, 4, 3                  # SelectionItem.Select, LegacyIAccessible's, Invoke's
PATTERN_INVOKE, PATTERN_SELECTION_ITEM, PATTERN_LEGACY = 10000, 10010, 10018
TAB_ITEM, DOCUMENT = 50019, 50030
# What a page is drawn in - never walked into: only the browser's own bars have its tabs.
CONTENT_CLASSES = ("Chrome_RenderWidgetHostHWND", "Internet Explorer_Server", "Shell DocObject View",
                   "TabWindowClass", "Intermediate D3D Window")
MAX_NODES, MAX_DEPTH = 800, 16

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    ole32 = ctypes.WinDLL("ole32")
    oleaut32 = ctypes.WinDLL("oleaut32")

    class GUID(ctypes.Structure):
        _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort),
                    ("d", ctypes.c_ubyte * 8)]

    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(GUID)]
    ole32.CLSIDFromString.restype = ctypes.c_long
    ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD,
                                       ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    ole32.CoCreateInstance.restype = ctypes.c_long
    oleaut32.SysStringLen.argtypes = [ctypes.c_void_p]
    oleaut32.SysStringLen.restype = ctypes.c_uint
    oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]
    oleaut32.SysFreeString.restype = None


def _guid(text):
    g = GUID()
    ole32.CLSIDFromString(text, ctypes.byref(g))
    return g


def _fn(p, slot, *argtypes):
    """Method `slot` of the COM interface at p, called as f(p, *args). A failing HRESULT raises OSError."""
    vtbl = ctypes.cast(p, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtbl[slot])


def _matches(name, target):
    """Is a tab (or Edge's title - the selected tab's) the one `target` wants?"""
    n = (name or "").lower()
    tracker = any(w in n for w in ctms_window.PAGE_WORDS)
    if target == "page":
        return tracker
    return not tracker and any(w in n for w in CTMS_TAB_WORDS)


class _Session:
    """UI Automation on this thread. Every interface it is handed is released at close()."""

    def __init__(self):
        self.held = []
        p = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(_guid(CLSID_CUIAutomation8)), None, 1,     # in-process
                                    ctypes.byref(_guid(IID_IUIAutomation2)), ctypes.byref(p))
        if hr < 0 or not p.value:
            raise OSError(f"UI Automation is not available on this PC (0x{hr & 0xFFFFFFFF:08X})")
        self.uia = self._keep(p.value)
        # Leave the keyboard focus where it is: Edge then gives the tab's page its focus back
        _fn(self.uia, UIA_PUT_AUTOSETFOCUS, wintypes.BOOL)(self.uia, False)
        self.walker = self._get(self.uia, UIA_CONTROL_WALKER)

    def _keep(self, p):
        if p:
            self.held.append(p)
        return p

    def _get(self, p, slot, *args):
        """A method whose last argument hands back an interface: that interface, or None."""
        out = ctypes.c_void_p()
        _fn(p, slot, *[t for t, _ in args], ctypes.POINTER(ctypes.c_void_p))(p, *[v for _, v in args],
                                                                             ctypes.byref(out))
        return self._keep(out.value)

    def _text(self, el, slot):
        out = ctypes.c_void_p()
        _fn(el, slot, ctypes.POINTER(ctypes.c_void_p))(el, ctypes.byref(out))
        if not out.value:
            return ""
        try:
            return ctypes.wstring_at(out.value, oleaut32.SysStringLen(out.value))
        finally:
            oleaut32.SysFreeString(out.value)

    def element(self, hwnd):
        return self._get(self.uia, UIA_ELEMENT_FROM_HANDLE, (ctypes.c_void_p, ctypes.c_void_p(int(hwnd))))

    def control_type(self, el):
        out = ctypes.c_int()
        _fn(el, EL_CONTROL_TYPE, ctypes.POINTER(ctypes.c_int))(el, ctypes.byref(out))
        return out.value

    def name(self, el):
        return self._text(el, EL_NAME)

    def class_name(self, el):
        return self._text(el, EL_CLASS)

    def children(self, el):
        child = self._get(self.walker, WALK_FIRST_CHILD, (ctypes.c_void_p, el))
        while child:
            yield child
            child = self._get(self.walker, WALK_NEXT, (ctypes.c_void_p, child))

    def tabs(self, hwnd):
        """(element, name) of each tab in this Edge window's own bars - a page is never walked into."""
        found, seen, level = [], 0, [self.element(hwnd)]
        for _ in range(MAX_DEPTH):
            deeper = []
            for el in level:
                for child in self.children(el):
                    seen += 1
                    kind = self.control_type(child)
                    if kind == TAB_ITEM:
                        found.append((child, self.name(child)))
                    elif kind != DOCUMENT and self.class_name(child) not in CONTENT_CLASSES:
                        deeper.append(child)
                    if seen >= MAX_NODES:
                        return found
            if not deeper:
                break
            level = deeper
        return found

    def select(self, el):
        """Select a tab: as a SelectionItem, else by its default action, else Invoke. False = none took."""
        for pattern, iid, slot in ((PATTERN_SELECTION_ITEM, IID_SELECTION_ITEM, SELECT),
                                   (PATTERN_LEGACY, IID_LEGACY, DEFAULT_ACTION),
                                   (PATTERN_INVOKE, IID_INVOKE, INVOKE)):
            try:
                pat = self._get(el, EL_PATTERN_AS, (ctypes.c_int, pattern), (ctypes.POINTER(GUID), _guid(iid)))
                if pat:
                    _fn(pat, slot)(pat)
                    return True
            except OSError:
                continue
        return False

    def close(self):
        for p in reversed(self.held):
            vtbl = ctypes.cast(p, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[RELEASE])(p)
        self.held = []


def _edge_windows():
    return [h for h in ctms_window._enum()
            if ctms_window.user32.IsWindowVisible(h) and ctms_window._cls(h) == ctms_window.EDGE_CLASS
            and ctms_window._exe(h) == "msedge.exe"]


def _select(target):
    hr = ole32.CoInitializeEx(None, 0)          # COINIT_MULTITHREADED, as UI Automation clients are told to
    try:
        s = _Session()
        try:
            for hwnd in _edge_windows():
                for el, name in s.tabs(hwnd):
                    if not _matches(name, target):
                        continue
                    if not s.select(el):
                        return False, f"Edge would not bring up {WHAT[target]} - select it yourself."
                    end = time.time() + 3
                    while time.time() < end:            # Edge's title is the selected tab's
                        if _matches(ctms_window._text(hwnd), target):
                            return True, f"Brought up {WHAT[target]} in Edge."
                        time.sleep(0.1)
                    return False, f"Edge did not bring up {WHAT[target]} - select it yourself."
            return False, ("CTMS is not open in any Edge tab." if target == "ctms"
                           else "The DigiHaul Job Tracker is not open in any Edge tab.")
        finally:
            s.close()
    except OSError as e:
        return False, f"UI Automation could not reach Edge ({e}) - select {WHAT[target]} yourself."
    finally:
        if hr >= 0:
            ole32.CoUninitialize()


def select(target, timeout=10.0):
    """Bring up CTMS's tab ("ctms") or the tracker's ("page") in Edge -> (True, what was done) or (False, why not).

    On a thread of its own: UI Automation wants COM set up its own way, and an Edge that has stopped
    answering must not stop the bridge.
    """
    if target not in WHAT:
        return False, "Which tab? ctms, or page (the tracker)."
    if not IS_WIN:
        return False, "Bringing up Edge's tabs works on Windows only."
    out = []
    t = threading.Thread(target=lambda: out.append(_select(target)), daemon=True, name="ctms-tabs")
    t.start()
    t.join(timeout)
    if not out:
        return False, f"Edge did not answer in time, so {WHAT[target]} was not brought up - select it yourself."
    return out[0]
