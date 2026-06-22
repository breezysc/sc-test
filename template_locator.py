"""
TemplateLocator - MVP 版本

核心功能:
  1. 用 OpenCV matchTemplate 在游戏窗口内定位锚点模板
  2. 多尺度匹配 (template 在 0.7x~1.5x 之间缩放)，提高分辨率鲁棒性
  3. 输出调试截图 (匹配位置 + 候选框) 到 template_debug/ 目录
  4. 所有坐标: 相对游戏窗口的坐标 (与 WindowLocator 坐标系一致)

当前 MVP 目标:
  - 只实现 Inventory 锚点定位
  - 通过锚点 + 偏移表计算完整的检测区域 (roi)
  - 不修改任何业务逻辑

使用示例:
    from window_locator import locator
    from template_locator import TemplateLocator, load_anchor_config

    locator.detect("global")
    tloc = TemplateLocator(locator, config_path="template_locator_config.json")
    result = tloc.locate_inventory(threshold=0.65)
    if result["success"]:
        print("锚点位置 (相对窗口):", result["anchor_rel"])
        print("检测区域 (相对窗口):", result["roi_rel"])
        # 直接写入业务配置:
        # auto_buy_config.json 中的 roi.LEFT/ROI.TOP/... 用 result["roi_rel"] 填充
"""

import os
import json
import time
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    pyautogui = None
    HAS_PYAUTOGUI = False


# ---------------------------------------------------------------------------
# 默认的 Inventory 锚点配置
# 用户首次使用时可以在 Debug Tool 里"采集锚点"，然后这个文件会覆盖下面默认值
# ---------------------------------------------------------------------------

DEFAULT_INVENTORY_CONFIG = {
    "inventory": {
        "template_path": "templates/inventory/anchor.png",
        "threshold": 0.65,
        "scale_min": 0.7,
        "scale_max": 1.5,
        "scale_step": 0.05,
        # 相对偏移: 从锚点左上角到 roi 四个角的偏移量 (像素)
        # 正值 = 向右/向下；负值 = 向左/向上
        "offset": {
            "dx1": -50,
            "dy1": -30,
            "dx2": 750,
            "dy2": 750,
        },
    }
}

DEBUG_DIR = "template_debug"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def load_anchor_config(path="template_locator_config.json"):
    """加载锚点偏移配置。若文件不存在，返回默认配置。

    返回: dict，形如 DEFAULT_INVENTORY_CONFIG
    """
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return dict(DEFAULT_INVENTORY_CONFIG)


def save_anchor_config(config, path="template_locator_config.json"):
    """保存锚点偏移配置到 JSON 文件。

    用于 Debug Tool 采集完锚点后写盘。
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# TemplateLocator 主类 (MVP)
# ---------------------------------------------------------------------------

class TemplateLocator:
    """用 matchTemplate 自动定位游戏 UI 区域 - MVP 版

    依赖:
      - window_locator.WindowLocator (提供游戏窗口截图 + 坐标系统)
      - cv2 (OpenCV)
      - numpy
    """

    def __init__(self, window_locator, config_path="template_locator_config.json",
                 debug=True):
        """
        Args:
            window_locator: WindowLocator 实例（已 detect 过的）
            config_path: 锚点偏移配置文件路径
            debug: 是否输出调试截图
        """
        self.locator = window_locator
        self.config = load_anchor_config(config_path)
        self.debug = debug
        self._template_cache = {}  # 模板图片缓存: path -> np.ndarray

        if self.debug and not os.path.exists(DEBUG_DIR):
            os.makedirs(DEBUG_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # 主 API: Inventory 锚点定位
    # ------------------------------------------------------------------

    def locate_inventory(self, threshold=None):
        """定位 Inventory 区域 - MVP 主方法

        流程:
          1. 截取整个游戏窗口
          2. 加载锚点模板 (templates/inventory/anchor.png)
          3. 多尺度 matchTemplate (0.7x~1.5x)
          4. 取最佳匹配作为锚点
          5. 用偏移表计算完整 roi 区域
          6. [调试] 输出带标注的截图

        Returns: dict，包含以下字段:
          {
            "success": bool,
            "anchor_rel": (x, y) | None,        # 锚点左上角 (相对窗口)
            "anchor_size": (w, h) | None,       # 锚点在最佳匹配尺度下的大小
            "confidence": float,                # matchTemplate 最高置信度
            "scale": float | None,              # 最佳匹配的缩放系数
            "roi_rel": (x1, y1, x2, y2) | None, # 完整检测区域 (相对窗口)
            "roi_dict": {"LEFT":.., "TOP":.., "RIGHT":.., "BOTTOM":..} | None,
            "debug_image": str | None,          # 调试截图路径
            "message": str,
          }
        """
        result = {
            "success": False,
            "anchor_rel": None,
            "anchor_size": None,
            "confidence": 0.0,
            "scale": None,
            "roi_rel": None,
            "roi_dict": None,
            "debug_image": None,
            "message": "",
        }

        # ── 前置检查 ────────────────────────────────────────
        if cv2 is None:
            result["message"] = "未安装 cv2 (OpenCV)"
            return result
        if not self.locator.detected:
            result["message"] = "WindowLocator 尚未检测到游戏窗口，请先调用 .detect()"
            return result

        inv_cfg = self.config.get("inventory", {})
        template_path = inv_cfg.get("template_path", "templates/inventory/anchor.png")
        if threshold is None:
            threshold = inv_cfg.get("threshold", 0.65)
        scale_min = inv_cfg.get("scale_min", 0.7)
        scale_max = inv_cfg.get("scale_max", 1.5)
        scale_step = inv_cfg.get("scale_step", 0.05)
        offset = inv_cfg.get("offset", {"dx1": -50, "dy1": -30, "dx2": 750, "dy2": 750})

        # ── 截图 + 加载模板 ────────────────────────────────
        window_img = self.locator.grab_window()
        if window_img is None:
            result["message"] = "grab_window() 返回 None"
            return result

        template = self._load_template(template_path)
        if template is None:
            result["message"] = f"锚点模板不存在: {template_path}"
            return result

        # 模板不能比搜索图大
        if (template.shape[0] > window_img.shape[0] or
                template.shape[1] > window_img.shape[1]):
            result["message"] = (
                f"模板 ({template.shape[1]}x{template.shape[0]}) "
                f"大于窗口截图 ({window_img.shape[1]}x{window_img.shape[0]})"
            )
            return result

        # ── 多尺度 matchTemplate ────────────────────────────────
        best = self._multi_scale_match(window_img, template,
                                       scale_min, scale_max, scale_step)

        result["confidence"] = best["confidence"]
        result["scale"] = best["scale"]

        if best["confidence"] < threshold:
            result["message"] = (
                f"最佳匹配置信度 {best['confidence']:.3f} 低于阈值 {threshold}"
            )
            # 即便失败也保存调试截图（便于用户看候选位置）
            if self.debug:
                result["debug_image"] = self._save_debug_shot(
                    window_img, template, best, offset, success=False
                )
            return result

        # ── 计算完整区域 ────────────────────────────────────────
        # 锚点左上角 (相对窗口):
        anchor_x, anchor_y = best["match_x"], best["match_y"]
        tpl_w, tpl_h = best["tpl_w"], best["tpl_h"]

        dx1 = offset["dx1"]
        dy1 = offset["dy1"]
        dx2 = offset["dx2"]
        dy2 = offset["dy2"]

        roi_x1 = anchor_x + dx1
        roi_y1 = anchor_y + dy1
        roi_x2 = anchor_x + dx2
        roi_y2 = anchor_y + dy2

        # 裁剪到窗口范围内，避免越界
        win_w = self.locator.window["width"]
        win_h = self.locator.window["height"]
        roi_x1 = max(0, min(roi_x1, win_w - 1))
        roi_y1 = max(0, min(roi_y1, win_h - 1))
        roi_x2 = max(roi_x1 + 1, min(roi_x2, win_w))
        roi_y2 = max(roi_y1 + 1, min(roi_y2, win_h))

        result["success"] = True
        result["anchor_rel"] = (anchor_x, anchor_y)
        result["anchor_size"] = (tpl_w, tpl_h)
        result["roi_rel"] = (roi_x1, roi_y1, roi_x2, roi_y2)
        result["roi_dict"] = {
            "LEFT": int(roi_x1),
            "TOP": int(roi_y1),
            "RIGHT": int(roi_x2),
            "BOTTOM": int(roi_y2),
        }
        result["message"] = (
            f"锚点匹配成功: 置信度={best['confidence']:.3f}, "
            f"尺度={best['scale']:.2f}, roi=({roi_x1},{roi_y1})-({roi_x2},{roi_y2})"
        )

        # ── 调试截图 ────────────────────────────────────────
        if self.debug:
            result["debug_image"] = self._save_debug_shot(
                window_img, template, best, offset, success=True
            )

        return result

    # ------------------------------------------------------------------
    # 主 API: Stash 锚点定位
    # ------------------------------------------------------------------

    def locate_stash(self, threshold=None):
        """定位 Stash 仓库区域。

        与 locate_inventory() 结构类似，但有以下区别：
          - 使用 templates/stash/anchor.png
          - Stash ROI 可能超出游戏窗口范围（因为 Stash 是独立浮动面板）
          - 坐标系统：相对游戏窗口坐标（运行时通过 locator.to_screen() 转成屏幕坐标）

        Returns: dict，字段与 locate_inventory() 相同
        """
        result = {
            "success": False,
            "anchor_rel": None,
            "anchor_size": None,
            "confidence": 0.0,
            "scale": None,
            "roi_rel": None,
            "roi_dict": None,
            "debug_image": None,
            "message": "",
        }

        if cv2 is None:
            result["message"] = "未安装 cv2 (OpenCV)"
            return result
        if not self.locator.detected:
            result["message"] = "WindowLocator 尚未检测到游戏窗口，请先调用 .detect()"
            return result

        stash_cfg = self.config.get("stash", {})
        template_path = stash_cfg.get("template_path", "templates/stash/anchor.png")
        if threshold is None:
            threshold = stash_cfg.get("threshold", 0.7)
        scale_min = stash_cfg.get("scale_min", 0.7)
        scale_max = stash_cfg.get("scale_max", 1.5)
        scale_step = stash_cfg.get("scale_step", 0.05)
        offset = stash_cfg.get("offset", {"dx1": 380, "dy1": 29, "dx2": 1151, "dy2": 357})

        # ── 截图 + 加载模板 ──
        window_img = self.locator.grab_window()
        if window_img is None:
            result["message"] = "grab_window() 返回 None"
            return result

        template = self._load_template(template_path)
        if template is None:
            result["message"] = f"锚点模板不存在: {template_path}"
            return result

        if (template.shape[0] > window_img.shape[0] or
                template.shape[1] > window_img.shape[1]):
            result["message"] = (
                f"模板 ({template.shape[1]}x{template.shape[0]}) "
                f"大于窗口截图 ({window_img.shape[1]}x{window_img.shape[0]})"
            )
            return result

        # ── 多尺度 matchTemplate ──
        best = self._multi_scale_match(window_img, template,
                                       scale_min, scale_max, scale_step)

        result["confidence"] = best["confidence"]
        result["scale"] = best["scale"]

        if best["confidence"] < threshold:
            result["message"] = (
                f"最佳匹配置信度 {best['confidence']:.3f} 低于阈值 {threshold}"
            )
            if self.debug:
                result["debug_image"] = self._save_debug_shot(
                    window_img, template, best, offset, success=False, tag="stash"
                )
            return result

        # ── 计算完整区域（Stash：不裁剪到窗口范围） ──
        anchor_x, anchor_y = best["match_x"], best["match_y"]
        tpl_w, tpl_h = best["tpl_w"], best["tpl_h"]

        roi_x1 = anchor_x + offset["dx1"]
        roi_y1 = anchor_y + offset["dy1"]
        roi_x2 = anchor_x + offset["dx2"]
        roi_y2 = anchor_y + offset["dy2"]

        # 注意：Stash ROI 可能超出游戏窗口范围，不做裁剪

        result["success"] = True
        result["anchor_rel"] = (anchor_x, anchor_y)
        result["anchor_size"] = (tpl_w, tpl_h)
        result["roi_rel"] = (roi_x1, roi_y1, roi_x2, roi_y2)
        result["roi_dict"] = {
            "LEFT": int(roi_x1),
            "TOP": int(roi_y1),
            "RIGHT": int(roi_x2),
            "BOTTOM": int(roi_y2),
        }
        result["message"] = (
            f"Stash 锚点匹配成功: 置信度={best['confidence']:.3f}, "
            f"尺度={best['scale']:.2f}, roi=({roi_x1},{roi_y1})-({roi_x2},{roi_y2})"
        )

        # ── 调试截图（扩展区域，显示 Stash ROI） ──
        if self.debug:
            result["debug_image"] = self._save_stash_debug_shot(
                window_img, template, best, offset, success=True
            )

        return result

    # ------------------------------------------------------------------
    # 通用 Grid 生成（Inventory / Stash 同构实现）
    # ------------------------------------------------------------------

    def _generate_grid(self, locate_fn, roi_rel, cols, rows, tag):
        """通用 Grid 生成逻辑 - Inventory 和 Stash 同构调用

        Args:
            locate_fn: 锚点定位函数 (self.locate_inventory or self.locate_stash)
            roi_rel: (x1, y1, x2, y2) 相对窗口坐标。若为 None，调用 locate_fn 获取
            cols: 列数
            rows: 行数
            tag: "inventory" | "stash" - 用于调试截图文件名

        Returns: dict - 与 generate_inventory_cells 返回结构完全一致
        """
        result = {
            "success": False,
            "cells_map": None,
            "cells_screen_map": None,
            "roi_rel": roi_rel,
            "cell_size": None,
            "debug_image": None,
            "message": "",
        }

        # 若未提供 ROI，自动定位
        if roi_rel is None:
            loc_result = locate_fn()
            if not loc_result["success"]:
                result["message"] = f"{tag.upper()} 定位失败: {loc_result['message']}"
                return result
            roi_rel = loc_result["roi_rel"]
            result["roi_rel"] = roi_rel

        x1, y1, x2, y2 = roi_rel
        roi_w = x2 - x1
        roi_h = y2 - y1
        cell_w = roi_w / cols
        cell_h = roi_h / rows
        result["cell_size"] = (cell_w, cell_h)

        # 生成格子坐标（相对窗口坐标）
        cells_map = []
        for row in range(rows):
            for col in range(cols):
                cx1 = x1 + col * cell_w
                cy1 = y1 + row * cell_h
                cx2 = cx1 + cell_w
                cy2 = cy1 + cell_h
                cells_map.append([[int(cx1), int(cy1)], [int(cx2), int(cy2)]])
        result["cells_map"] = cells_map

        # 生成屏幕坐标版本（用于业务逻辑中直接点击）
        win_left = self.locator.window["left"]
        win_top = self.locator.window["top"]
        cells_screen_map = []
        for cell in cells_map:
            sx1 = cell[0][0] + win_left
            sy1 = cell[0][1] + win_top
            sx2 = cell[1][0] + win_left
            sy2 = cell[1][1] + win_top
            cells_screen_map.append([[sx1, sy1], [sx2, sy2]])
        result["cells_screen_map"] = cells_screen_map

        result["success"] = True
        result["message"] = (
            f"生成 {len(cells_map)} 个格子 ({cols}x{rows}), "
            f"每格 {cell_w:.1f}x{cell_h:.1f} 像素"
        )

        # 调试截图
        if self.debug:
            result["debug_image"] = self._save_cells_debug_shot(
                roi_rel, cells_map, tag=tag
            )

        return result

    def generate_stash_cells(self, roi_rel=None, cols=12, rows=12):
        """基于 Stash ROI 生成 144 个格子坐标（复用通用 Grid 逻辑）。

        与 generate_inventory_cells 同构实现，仅 tag 和定位函数不同。
        """
        return self._generate_grid(self.locate_stash, roi_rel, cols, rows, tag="stash")

    # ------------------------------------------------------------------
    # 主 API: 基于 Inventory ROI 自动生成 60 格坐标
    # ------------------------------------------------------------------

    def generate_inventory_cells(self, roi_rel=None, cols=12, rows=5):
        """基于 Inventory ROI 生成 60 个格子坐标（复用通用 Grid 逻辑）。

        与 generate_stash_cells 同构实现，仅 tag 和定位函数不同。
        """
        return self._generate_grid(
            self.locate_inventory, roi_rel, cols, rows, tag="inventory"
        )

    # ------------------------------------------------------------------
    # Action Layer: 坐标 -> 鼠标操作（不修改 Locator，不新增识别）
    # ------------------------------------------------------------------

    def _get_cell_screen_center(self, cells_screen_map, cell_index):
        """获取指定格子的屏幕中心点坐标。"""
        cell = cells_screen_map[cell_index]
        sx1, sy1 = cell[0]
        sx2, sy2 = cell[1]
        return (sx1 + sx2) // 2, (sy1 + sy2) // 2

    def _validate_index(self, cells_map, cell_index):
        """验证格子索引是否合法。"""
        if cell_index < 0 or cell_index >= len(cells_map):
            raise ValueError(
                f"cell_index {cell_index} 超出范围 [0, {len(cells_map)-1}]"
            )

    # --- Inventory 操作 ---

    def move_to_inventory_cell(self, col, row, cols=12, rows=5):
        """鼠标移动到 Inventory 指定格子中心。

        Args:
            col, row: 行列坐标 (0-based)
            cols, rows: 网格尺寸

        Returns: dict: {success, screen_center, message}
        """
        if not HAS_PYAUTOGUI:
            return {"success": False, "screen_center": None, "message": "pyautogui 未安装"}
        cell_index = row * cols + col
        cells = self.generate_inventory_cells(cols=cols, rows=rows)
        if not cells["success"]:
            return {"success": False, "screen_center": None, "message": cells["message"]}
        self._validate_index(cells["cells_screen_map"], cell_index)
        cx, cy = self._get_cell_screen_center(cells["cells_screen_map"], cell_index)
        pyautogui.moveTo(cx, cy, duration=0.15)
        return {"success": True, "screen_center": (cx, cy),
                "message": f"Inventory ({col},{row}) -> 屏幕({cx},{cy})"}

    def click_inventory_cell(self, col, row, cols=12, rows=5, interval=0.2):
        """点击 Inventory 指定格子中心。

        Args:
            col, row: 行列坐标
            interval: 点击前后停留时间（秒）
        """
        result = self.move_to_inventory_cell(col, row, cols, rows)
        if not result["success"]:
            return result
        time.sleep(interval)
        pyautogui.click(result["screen_center"][0], result["screen_center"][1])
        time.sleep(interval)
        return result

    def hover_inventory_cell(self, col, row, duration=1.0, cols=12, rows=5):
        """悬停在 Inventory 指定格子（调试用）。

        Args:
            duration: 悬停时间（秒）
        """
        result = self.move_to_inventory_cell(col, row, cols, rows)
        if result["success"]:
            time.sleep(duration)
        return result

    # --- Stash 操作 ---

    def move_to_stash_cell(self, col, row, cols=12, rows=12):
        """鼠标移动到 Stash 指定格子中心。"""
        if not HAS_PYAUTOGUI:
            return {"success": False, "screen_center": None, "message": "pyautogui 未安装"}
        cell_index = row * cols + col
        cells = self.generate_stash_cells(cols=cols, rows=rows)
        if not cells["success"]:
            return {"success": False, "screen_center": None, "message": cells["message"]}
        self._validate_index(cells["cells_screen_map"], cell_index)
        cx, cy = self._get_cell_screen_center(cells["cells_screen_map"], cell_index)
        pyautogui.moveTo(cx, cy, duration=0.15)
        return {"success": True, "screen_center": (cx, cy),
                "message": f"Stash ({col},{row}) -> 屏幕({cx},{cy})"}

    def click_stash_cell(self, col, row, cols=12, rows=12, interval=0.2):
        """点击 Stash 指定格子中心。"""
        result = self.move_to_stash_cell(col, row, cols, rows)
        if not result["success"]:
            return result
        time.sleep(interval)
        pyautogui.click(result["screen_center"][0], result["screen_center"][1])
        time.sleep(interval)
        return result

    def hover_stash_cell(self, col, row, duration=1.0, cols=12, rows=12):
        """悬停在 Stash 指定格子（调试用）。"""
        result = self.move_to_stash_cell(col, row, cols, rows)
        if result["success"]:
            time.sleep(duration)
        return result

    # ------------------------------------------------------------------
    # 辅助: 多尺度匹配
    # ------------------------------------------------------------------

    def _multi_scale_match(self, window_img, template,
                           scale_min, scale_max, scale_step):
        """在不同缩放尺度下对模板做 matchTemplate，取最佳结果

        核心思路: 不同分辨率下，锚点的像素大小不同，
        把模板在 0.7x~1.5x 之间缩放，取匹配度最高的那个。

        Returns: dict: {
            "match_x", "match_y", "confidence", "scale",
            "tpl_w", "tpl_h", "candidates": [...]
        }
        """
        gray_win = cv2.cvtColor(window_img, cv2.COLOR_BGR2GRAY)
        gray_tpl = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

        # 预计算所有要尝试的尺度
        scales = []
        s = scale_min
        while s <= scale_max + 0.0001:
            scales.append(round(s, 4))
            s += scale_step
        if 1.0 not in scales:
            scales.append(1.0)
            scales.sort()

        best = {
            "match_x": 0, "match_y": 0,
            "confidence": 0.0, "scale": 1.0,
            "tpl_w": template.shape[1], "tpl_h": template.shape[0],
            "candidates": [],
        }

        for scale in scales:
            new_w = max(1, int(gray_tpl.shape[1] * scale))
            new_h = max(1, int(gray_tpl.shape[0] * scale))
            # 缩放后的模板不能比搜索图大
            if new_h >= gray_win.shape[0] or new_w >= gray_win.shape[1]:
                continue

            scaled = cv2.resize(gray_tpl, (new_w, new_h),
                                interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC)

            result = cv2.matchTemplate(gray_win, scaled, cv2.TM_CCOEFF_NORMED)
            _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)

            # 记录候选 (便于调试输出看到前 N 个最优)
            cand = {
                "scale": scale,
                "confidence": float(max_val),
                "match_x": int(max_loc[0]),
                "match_y": int(max_loc[1]),
                "tpl_w": new_w,
                "tpl_h": new_h,
            }
            best["candidates"].append(cand)

            if max_val > best["confidence"]:
                best["confidence"] = float(max_val)
                best["match_x"] = int(max_loc[0])
                best["match_y"] = int(max_loc[1])
                best["scale"] = scale
                best["tpl_w"] = new_w
                best["tpl_h"] = new_h

        # 按置信度排序，保留 top-3 供调试输出
        best["candidates"].sort(key=lambda c: c["confidence"], reverse=True)
        best["candidates"] = best["candidates"][:3]
        return best

    # ------------------------------------------------------------------
    # 辅助: 模板加载 + 调试截图输出
    # ------------------------------------------------------------------

    def _load_template(self, path):
        """加载模板图片，带文件缓存。失败返回 None"""
        if path in self._template_cache:
            return self._template_cache[path]
        if not os.path.exists(path):
            return None
        img = cv2.imread(path)
        if img is None:
            return None
        self._template_cache[path] = img
        return img

    def _save_debug_shot(self, window_img, template, best, offset, success, tag="inventory"):
        """在游戏窗口截图上画出: 最佳匹配框 + roi 框 + top-3 候选，保存到 template_debug/"""
        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            out_path = os.path.join(DEBUG_DIR, f"{tag}_{ts}.png")

            # 拷贝一份，避免直接修改原截图
            disp = window_img.copy()

            # 1. 画 top-3 候选 (浅红色虚线框)
            for i, cand in enumerate(best["candidates"]):
                x, y = cand["match_x"], cand["match_y"]
                w, h = cand["tpl_w"], cand["tpl_h"]
                color = (0, 0, 255) if i == 0 else (100, 100, 200)
                cv2.rectangle(disp, (x, y), (x + w, y + h), color, 1)
                cv2.putText(disp, f"#{i+1} {cand['confidence']:.2f}@{cand['scale']:.2f}",
                            (x, max(0, y - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)

            # 2. 画最佳匹配锚点 (粗红色框)
            if best["confidence"] > 0:
                ax, ay = best["match_x"], best["match_y"]
                aw, ah = best["tpl_w"], best["tpl_h"]
                cv2.rectangle(disp, (ax, ay), (ax + aw, ay + ah), (0, 0, 255), 2)
                cv2.putText(disp, "ANCHOR",
                            (ax, max(0, ay - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)

            # 3. 画 roi 区域 (绿色框)
            if success:
                anchor_x, anchor_y = best["match_x"], best["match_y"]
                roi_x1 = anchor_x + offset["dx1"]
                roi_y1 = anchor_y + offset["dy1"]
                roi_x2 = anchor_x + offset["dx2"]
                roi_y2 = anchor_y + offset["dy2"]
                # 裁剪到窗口
                h, w = disp.shape[0], disp.shape[1]
                rx1 = max(0, min(roi_x1, w - 2))
                ry1 = max(0, min(roi_y1, h - 2))
                rx2 = max(rx1 + 1, min(roi_x2, w))
                ry2 = max(ry1 + 1, min(roi_y2, h))
                cv2.rectangle(disp, (rx1, ry1), (rx2, ry2), (0, 255, 0), 2)
                cv2.putText(disp, "ROI (Inventory detect region)",
                            (rx1, max(0, ry1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            # 4. 写状态文字
            status = "OK" if success else "FAILED"
            color = (0, 255, 0) if success else (0, 0, 255)
            cv2.putText(disp, f"{status} conf={best['confidence']:.3f} scale={best['scale']:.2f}",
                        (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1)
            cv2.putText(disp,
                        f"window: {self.locator.window['width']}x{self.locator.window['height']}",
                        (6, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

            cv2.imwrite(out_path, disp)
            return out_path
        except Exception as e:
            return f"<debug_shot_error: {e}>"

    def _save_stash_debug_shot(self, window_img, template, best, offset, success):
        """专门用于 Stash 的调试截图：扩展截图区域以显示窗口外的 Stash ROI"""
        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            out_path = os.path.join(DEBUG_DIR, f"stash_{ts}.png")

            # 计算 Stash ROI（相对窗口坐标）
            anchor_x, anchor_y = best["match_x"], best["match_y"]
            roi_x1 = anchor_x + offset["dx1"]
            roi_y1 = anchor_y + offset["dy1"]
            roi_x2 = anchor_x + offset["dx2"]
            roi_y2 = anchor_y + offset["dy2"]

            # 扩展截图区域：覆盖窗口 + Stash ROI
            win_w = self.locator.window["width"]
            win_h = self.locator.window["height"]
            ext_x1 = min(0, int(roi_x1))
            ext_y1 = min(0, int(roi_y1))
            ext_x2 = max(win_w, int(roi_x2))
            ext_y2 = max(win_h, int(roi_y2))
            ext_w = ext_x2 - ext_x1
            ext_h = ext_y2 - ext_y1

            # 用 mss 截图扩展区域（转换为屏幕绝对坐标）
            win_left = self.locator.window["left"]
            win_top = self.locator.window["top"]
            try:
                import mss
                sct = mss.mss()
                monitor = {
                    "left": win_left + ext_x1,
                    "top": win_top + ext_y1,
                    "width": ext_w,
                    "height": ext_h,
                }
                sct_img = sct.grab(monitor)
                import numpy as _np
                # mss 返回 BGRA 格式，需要转换为 OpenCV BGR 格式
                raw = _np.array(sct_img, dtype=_np.uint8)  # shape: (H, W, 4) BGRA
                # 提取 BGR 通道（丢弃 A 通道），并确保内存连续
                bgr = raw[:, :, :3].copy()  # 现在就是 BGR 格式
                disp = bgr
            except Exception:
                # 回退：只用窗口截图
                disp = window_img.copy()
                ext_x1, ext_y1 = 0, 0

            # 相对偏移：扩展图坐标系原点在 (ext_x1, ext_y1)
            dx_off = -ext_x1
            dy_off = -ext_y1

            # 1. 画 top-3 候选 (浅蓝色框)
            for i, cand in enumerate(best["candidates"]):
                x, y = cand["match_x"] + dx_off, cand["match_y"] + dy_off
                w, h = cand["tpl_w"], cand["tpl_h"]
                color = (255, 200, 0) if i == 0 else (180, 180, 100)
                cv2.rectangle(disp, (x, y), (x + w, y + h), color, 1)
                cv2.putText(disp, f"#{i+1} {cand['confidence']:.2f}",
                            (x, max(0, y - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)

            # 2. 画最佳匹配锚点 (蓝色粗框)
            if best["confidence"] > 0:
                ax, ay = best["match_x"] + dx_off, best["match_y"] + dy_off
                aw, ah = best["tpl_w"], best["tpl_h"]
                cv2.rectangle(disp, (ax, ay), (ax + aw, ay + ah), (255, 0, 0), 2)
                cv2.putText(disp, "STASH ANCHOR",
                            (ax, max(0, ay - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1)

            # 3. 画游戏窗口边界 (白色虚线)
            wx1 = dx_off
            wy1 = dy_off
            wx2 = wx1 + win_w
            wy2 = wy1 + win_h
            cv2.rectangle(disp, (wx1, wy1), (wx2, wy2), (200, 200, 200), 1, cv2.LINE_4)
            cv2.putText(disp, "GAME WINDOW",
                        (wx1, max(0, wy1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

            # 4. 画 Stash ROI (橙色框)
            rx1 = int(roi_x1) + dx_off
            ry1 = int(roi_y1) + dy_off
            rx2 = int(roi_x2) + dx_off
            ry2 = int(roi_y2) + dy_off
            rx1_c = max(0, rx1)
            ry1_c = max(0, ry1)
            rx2_c = min(disp.shape[1] - 1, rx2)
            ry2_c = min(disp.shape[0] - 1, ry2)
            cv2.rectangle(disp, (rx1_c, ry1_c), (rx2_c, ry2_c), (0, 165, 255), 2)
            cv2.putText(disp, "STASH ROI",
                        (rx1_c, max(0, ry1_c - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)

            # 5. 写状态文字
            status = "OK" if success else "FAILED"
            color = (0, 255, 0) if success else (0, 0, 255)
            cv2.putText(disp, f"STASH {status} conf={best['confidence']:.3f}",
                        (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1)
            cv2.putText(disp,
                        f"roi_rel=({int(roi_x1)},{int(roi_y1)})-({int(roi_x2)},{int(roi_y2)})",
                        (6, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

            cv2.imwrite(out_path, disp)
            return out_path
        except Exception as e:
            return f"<debug_shot_error: {e}>"

    def _save_cells_debug_shot(self, roi_rel, cells_map, tag="stash"):
        """画格子边框 + 编号的调试截图。支持大区域截图"""
        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            out_path = os.path.join(DEBUG_DIR, f"{tag}_cells_{ts}.png")

            x1, y1, x2, y2 = roi_rel
            win_left = self.locator.window["left"]
            win_top = self.locator.window["top"]
            win_w = self.locator.window["width"]
            win_h = self.locator.window["height"]

            # 计算扩展截图范围
            ext_x1 = min(0, int(x1))
            ext_y1 = min(0, int(y1))
            ext_x2 = max(win_w, int(x2))
            ext_y2 = max(win_h, int(y2))
            ext_w = ext_x2 - ext_x1
            ext_h = ext_y2 - ext_y1

            # 用 mss 截图扩展区域
            try:
                import mss
                sct = mss.mss()
                monitor = {
                    "left": win_left + ext_x1,
                    "top": win_top + ext_y1,
                    "width": ext_w,
                    "height": ext_h,
                }
                sct_img = sct.grab(monitor)
                import numpy as _np
                raw = _np.array(sct_img, dtype=_np.uint8)  # BGRA
                # BGRA -> BGR (OpenCV 格式)
                disp = raw[:, :, :3].copy()  # 直接提取 BGR 三通道
            except Exception:
                # 回退：只用窗口截图
                disp = self.locator.grab_window()
                ext_x1, ext_y1 = 0, 0

            dx_off = -ext_x1
            dy_off = -ext_y1

            # 1. 画游戏窗口边界 (白色虚线)
            wx1 = dx_off
            wy1 = dy_off
            wx2 = wx1 + win_w
            wy2 = wy1 + win_h
            cv2.rectangle(disp, (wx1, wy1), (wx2, wy2), (200, 200, 200), 1)

            # 2. 画 ROI (绿色粗框)
            rx1 = int(x1) + dx_off
            ry1 = int(y1) + dy_off
            rx2 = int(x2) + dx_off
            ry2 = int(y2) + dy_off
            rx1_c = max(0, min(rx1, disp.shape[1] - 2))
            ry1_c = max(0, min(ry1, disp.shape[0] - 2))
            rx2_c = max(rx1_c + 1, min(rx2, disp.shape[1] - 1))
            ry2_c = max(ry1_c + 1, min(ry2, disp.shape[0] - 1))
            cv2.rectangle(disp, (rx1_c, ry1_c), (rx2_c, ry2_c), (0, 255, 0), 2)
            cv2.putText(disp, "STASH ROI",
                        (rx1_c, max(0, ry1_c - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            # 3. 画所有格子 (蓝色细框)
            for idx, cell in enumerate(cells_map):
                cx1 = cell[0][0] + dx_off
                cy1 = cell[0][1] + dy_off
                cx2 = cell[1][0] + dx_off
                cy2 = cell[1][1] + dy_off
                cx1_c = max(0, min(cx1, disp.shape[1] - 2))
                cy1_c = max(0, min(cy1, disp.shape[0] - 2))
                cx2_c = max(cx1_c + 1, min(cx2, disp.shape[1] - 1))
                cy2_c = max(cy1_c + 1, min(cy2, disp.shape[0] - 1))
                cv2.rectangle(disp, (cx1_c, cy1_c), (cx2_c, cy2_c), (255, 0, 0), 1)

                # 格子编号 (在格子中心)
                cw = cx2_c - cx1_c
                ch = cy2_c - cy1_c
                if cw > 20 and ch > 12:
                    text = str(idx + 1)
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    scale = 0.35
                    thick = 1
                    (tw, th), _ = cv2.getTextSize(text, font, scale, thick)
                    tx = cx1_c + (cw - tw) // 2
                    ty = cy1_c + (ch + th) // 2
                    cv2.putText(disp, text, (tx, ty), font, scale, (255, 255, 0), thick)

            # 4. 写状态文字
            cv2.putText(disp, f"{tag.upper()} CELLS: {len(cells_map)} cells",
                        (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1)
            cv2.putText(disp,
                        f"roi_rel=({int(x1)},{int(y1)})-({int(x2)},{int(y2)})",
                        (6, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

            cv2.imwrite(out_path, disp)
            return out_path
        except Exception as e:
            return f"<debug_shot_error: {e}>"

    # ------------------------------------------------------------------
    # 便捷方法: 直接把 roi 写入业务配置文件 (不调用业务逻辑，仅改配置)
    # ------------------------------------------------------------------

    def write_roi_to_business_config(self, business_config_path="auto_buy_config.json",
                                     threshold=None):
        """尝试定位 Inventory，成功则把 roi 写入 auto_buy_config.json（保留其他字段不变）。

        Returns: (success: bool, message: str)
        """
        result = self.locate_inventory(threshold=threshold)
        if not result["success"]:
            return False, result["message"]

        # 读取原配置
        if os.path.exists(business_config_path):
            try:
                with open(business_config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                cfg = {}
        else:
            cfg = {}

        # 只更新 roi 字段，保持其他字段不变
        cfg["roi"] = result["roi_dict"]
        # 标记坐标系统为 relative（如之前未标记）
        if "coord_system" not in cfg:
            cfg["coord_system"] = "relative"

        with open(business_config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

        return True, f"已写入 {business_config_path} | roi = {result['roi_dict']}"


# ---------------------------------------------------------------------------
# 命令行独立测试
#   python template_locator.py --server global --threshold 0.65
# ---------------------------------------------------------------------------

def _cli_entry():
    import argparse
    parser = argparse.ArgumentParser(description="TemplateLocator - Inventory/Stash 锚点定位测试")
    parser.add_argument("--server", default="global", choices=["global", "china"],
                        help="游戏服务器 (影响窗口标题搜索)")
    parser.add_argument("--config", default="template_locator_config.json",
                        help="锚点配置文件路径")
    parser.add_argument("--threshold", type=float, default=None,
                        help="覆盖配置中的 matchTemplate 阈值")
    parser.add_argument("--stash", action="store_true",
                        help="定位 Stash 而不是 Inventory")
    parser.add_argument("--cells", action="store_true",
                        help="生成格子坐标并输出调试截图")
    parser.add_argument("--write-config", action="store_true",
                        help="如定位成功，把 roi 写入 auto_buy_config.json")
    parser.add_argument("--business-config", default="auto_buy_config.json",
                        help="业务配置文件路径 (配合 --write-config 使用)")
    args = parser.parse_args()

    from window_locator import locator as _locator
    if not _locator.detect(args.server):
        print("[ERROR] 未检测到游戏窗口")
        return 1

    tloc = TemplateLocator(_locator, config_path=args.config, debug=True)
    print(f"[INFO] 游戏窗口: {_locator.window['width']}x{_locator.window['height']} "
          f"位于屏幕 ({_locator.window['left']}, {_locator.window['top']})")

    # 选择定位目标
    target = "stash" if args.stash else "inventory"
    print(f"\n[INFO] 定位目标: {target.upper()}")

    if args.cells:
        # 生成格子坐标
        if args.stash:
            cells_result = tloc.generate_stash_cells()
        else:
            cells_result = tloc.generate_inventory_cells()
        print(f"[RESULT] success={cells_result['success']}")
        print(f"  message: {cells_result['message']}")
        if cells_result['roi_rel']:
            print(f"  roi_rel: {cells_result['roi_rel']}")
        if cells_result['cell_size']:
            print(f"  cell_size: {cells_result['cell_size'][0]:.1f}x{cells_result['cell_size'][1]:.1f}")
        if cells_result['cells_map']:
            print(f"  cells (相对窗口坐标, 前3个): {cells_result['cells_map'][:3]}")
        if cells_result['cells_screen_map']:
            print(f"  cells (屏幕绝对坐标, 前3个): {cells_result['cells_screen_map'][:3]}")
        if cells_result['debug_image']:
            print(f"  debug_image: {cells_result['debug_image']}")
    elif args.write_config and not args.stash:
        ok, msg = tloc.write_roi_to_business_config(
            business_config_path=args.business_config,
            threshold=args.threshold,
        )
        print(f"[RESULT] {'OK' if ok else 'FAIL'}: {msg}")
    else:
        # 普通定位
        if args.stash:
            result = tloc.locate_stash(threshold=args.threshold)
        else:
            result = tloc.locate_inventory(threshold=args.threshold)
        print(f"[RESULT] success={result['success']}")
        print(f"  message: {result['message']}")
        if result['anchor_rel']:
            print(f"  anchor_rel: {result['anchor_rel']} (size {result['anchor_size']})")
        print(f"  confidence: {result['confidence']:.3f}")
        if result['scale'] is not None:
            print(f"  best_scale: {result['scale']:.2f}x")
        if result['roi_rel']:
            print(f"  roi_rel: {result['roi_rel']}")
            print(f"  roi_dict: {result['roi_dict']}")
        if result['debug_image']:
            print(f"  debug_image: {result['debug_image']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(_cli_entry())
