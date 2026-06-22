"""
WindowLocator 模块 - 统一管理游戏窗口检测与坐标转换

职责:
  1. 自动检测 Path of Exile 2 / Path of Exile 游戏窗口
  2. 提供「相对游戏窗口的坐标」↔「屏幕绝对坐标」的双向转换
  3. 排除浏览器窗口（避免误识别）

使用方式:
    from window_locator import locator
    locator.detect("global")                # 检测游戏窗口
    locator.to_screen(rel_x, rel_y)          # 相对坐标 -> 屏幕坐标
    locator.to_relative(screen_x, screen_y)  # 屏幕坐标 -> 相对坐标
    locator.to_screen_monitor(x1, y1, x2, y2)  # 生成 mss 截图用的 monitor dict
"""

import ctypes
from ctypes import wintypes


# 需要排除的窗口标题关键词（浏览器）
BROWSER_KEYWORDS = ["chrome", "firefox", "edge", "iexplore", "safari", "opera", "brave", "浏览器"]


class WindowLocator:
    """游戏窗口定位器 - 单例模式"""

    def __init__(self):
        self._window = None  # {"hwnd","title","left","top","right","bottom","width","height"}

    @property
    def window(self):
        """返回当前检测到的窗口信息 dict，若未检测返回 None"""
        return self._window

    @property
    def detected(self):
        """是否已经检测到窗口"""
        return self._window is not None

    # ------------------------------------------------------------------
    # 窗口检测
    # ------------------------------------------------------------------
    def detect(self, server="global"):
        """检测游戏窗口

        Args:
            server: "global"（国际服，搜索 "Path of Exile 2"/"Path of Exile"）
                    或 "china"（国服，搜索 "流放之路"）

        Returns:
            bool: 是否检测成功。成功后可通过 .window 获取详情
        """
        if server == "china":
            terms = ["流放之路"]
        elif server == "global":
            terms = ["Path of Exile 2", "Path of Exile"]
        else:
            terms = ["流放之路", "Path of Exile 2", "Path of Exile"]

        all_windows = []
        for term in terms:
            found = self._find_windows_by_title(term)
            all_windows.extend(found)

        # 排除浏览器窗口
        game_windows = [
            w for w in all_windows
            if not any(bk in w["title"].lower() for bk in BROWSER_KEYWORDS)
        ]

        if not game_windows:
            self._window = None
            return False

        # 优先选标题含 "Path of Exile 2"（更精确），其次按标题长度排序
        if len(game_windows) > 1:
            exact = [w for w in game_windows if "path of exile 2" in w["title"].lower()]
            if exact:
                game_windows.sort(key=lambda w: len(w["title"]))
                self._window = game_windows[0]
            else:
                game_windows.sort(key=lambda w: len(w["title"]))
                self._window = game_windows[0]
        else:
            self._window = game_windows[0]

        return True

    def _find_windows_by_title(self, title_substring):
        """枚举所有包含子串的窗口，返回窗口矩形列表"""
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        results = []

        def _enum_callback(hwnd, _lparam):
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value
            if title_substring.lower() in title.lower():
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                results.append({
                    "hwnd": hwnd,
                    "title": title,
                    "left": rect.left,
                    "top": rect.top,
                    "right": rect.right,
                    "bottom": rect.bottom,
                    "width": rect.right - rect.left,
                    "height": rect.bottom - rect.top,
                })
            return True

        user32.EnumWindows(WNDENUMPROC(_enum_callback), 0)
        return results

    # ------------------------------------------------------------------
    # 坐标转换
    # ------------------------------------------------------------------
    def to_screen(self, rel_x, rel_y):
        """相对游戏窗口的坐标 -> 屏幕绝对坐标

        Args:
            rel_x, rel_y: 相对于游戏窗口左上角的坐标

        Returns:
            (screen_x, screen_y) 元组。若窗口未检测，则原样返回 (rel_x, rel_y)
        """
        if self._window is None:
            return (rel_x, rel_y)
        return (self._window["left"] + int(rel_x),
                self._window["top"] + int(rel_y))

    def to_relative(self, screen_x, screen_y):
        """屏幕绝对坐标 -> 相对游戏窗口的坐标

        Args:
            screen_x, screen_y: 屏幕绝对坐标

        Returns:
            (rel_x, rel_y) 元组。若窗口未检测，则原样返回 (screen_x, screen_y)
        """
        if self._window is None:
            return (screen_x, screen_y)
        return (int(screen_x) - self._window["left"],
                int(screen_y) - self._window["top"])

    def to_screen_monitor(self, rel_x1, rel_y1, rel_x2, rel_y2):
        """将相对游戏窗口的矩形区域转换为 mss 截图所需的 monitor dict

        Args:
            rel_x1, rel_y1, rel_x2, rel_y2: 相对游戏窗口的矩形

        Returns:
            dict: {"top", "left", "width", "height"}，可直接传入 mss.grab()
        """
        if self._window is None:
            return {
                "top": int(rel_y1),
                "left": int(rel_x1),
                "width": int(rel_x2 - rel_x1),
                "height": int(rel_y2 - rel_y1),
            }
        return {
            "top": self._window["top"] + int(rel_y1),
            "left": self._window["left"] + int(rel_x1),
            "width": int(rel_x2 - rel_x1),
            "height": int(rel_y2 - rel_y1),
        }

    def grab_region(self, rel_x1, rel_y1, rel_x2, rel_y2):
        """截取游戏窗口内的相对区域，返回 numpy 数组（BGR 格式）

        这是一个便捷方法：封装 mss 调用。

        Returns:
            np.ndarray 图像 (y2-y1, x2-x1, 3)
            失败返回 None
        """
        try:
            import mss as _mss
            import numpy as _np
            monitor = self.to_screen_monitor(rel_x1, rel_y1, rel_x2, rel_y2)
            with _mss.mss() as sct:
                shot = sct.grab(monitor)
                return _np.array(shot)[:, :, :3]
        except Exception:
            return None

    def grab_window(self):
        """截取整个游戏窗口，返回 numpy 数组（BGR 格式）

        这是 TemplateLocator 等模块需要的基础方法：获取游戏窗口的完整截图，
        以便在其上做 matchTemplate。

        Returns:
            np.ndarray 图像 (height, width, 3)，BGR 格式
            若未检测到窗口或失败，返回 None
        """
        if self._window is None:
            return None
        return self.grab_region(0, 0, self._window["width"], self._window["height"])

    def click(self, rel_x, rel_y, pyautogui_ref=None, duration=0.0):
        """在相对游戏窗口的坐标处点击

        Args:
            rel_x, rel_y: 相对游戏窗口的坐标
            pyautogui_ref: 可选的 pyautogui 模块引用。若为 None，则内部 import
            duration: 鼠标移动动画时长（秒）
        """
        pg = pyautogui_ref
        if pg is None:
            import pyautogui as _pg
            pg = _pg
        sx, sy = self.to_screen(rel_x, rel_y)
        if duration > 0:
            pg.moveTo(sx, sy, duration=duration)
        pg.click(sx, sy)


# 模块级单例
locator = WindowLocator()
