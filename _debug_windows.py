import ctypes
from ctypes import wintypes

EnumWindowsProc = ctypes.WINFUNCTYPE(
    ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
)

user32 = ctypes.windll.user32

all_windows = []

def _enum_cb(hwnd, _lparam):
    if not user32.IsWindowVisible(hwnd):
        return True
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return True
    buff = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buff, length + 1)
    title = buff.value
    if not title.strip():
        return True
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    if w < 100 or h < 100:
        return True
    all_windows.append({
        "hwnd": hwnd,
        "title": title,
        "left": rect.left,
        "top": rect.top,
        "width": w,
        "height": h,
    })
    return True

user32.EnumWindows(EnumWindowsProc(_enum_cb), 0)

# 先按关键字搜
keywords_global = ["Path of Exile 2", "Path of Exile", "poe2", "POE2", "POE"]
keywords_china = ["流放之路", "流放"]
matches_global = [w for w in all_windows if any(k.lower() in w["title"].lower() for k in keywords_global)]
matches_china = [w for w in all_windows if any(k in w["title"] for k in keywords_china)]

print("=" * 80)
print("  检测到的所有可见窗口 (宽高 >= 100):", len(all_windows))
print("=" * 80)
for i, w in enumerate(all_windows[:40]):
    print("  [{:2d}]  {}x{}  @({},{})  |  {}".format(
        i, w["width"], w["height"], w["left"], w["top"], w["title"][:60]))
if len(all_windows) > 40:
    print("  ... 还有 {} 个窗口未显示".format(len(all_windows) - 40))

print()
print("=" * 80)
print("  [global] 匹配的窗口 (Path of Exile 2/Path of Exile):", len(matches_global))
print("=" * 80)
for w in matches_global:
    print("  {}x{} @({},{}) | {}".format(w["width"], w["height"], w["left"], w["top"], w["title"]))

print()
print("=" * 80)
print("  [china] 匹配的窗口 (流放之路):", len(matches_china))
print("=" * 80)
for w in matches_china:
    print("  {}x{} @({},{}) | {}".format(w["width"], w["height"], w["left"], w["top"], w["title"]))

if not matches_global and not matches_china:
    print()
    print(">>> 建议: 看看上面列表里哪个标题是你的游戏窗口，告诉我准确标题")
