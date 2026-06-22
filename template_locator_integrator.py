"""
TemplateLocator 整合模块 - 替代配置文件读取

功能：
1. 启动时自动执行 locate_inventory() 和 locate_stash()
2. 动态生成 Inventory 和 Stash 的 cells_map
3. 提供与原配置格式兼容的 API，不修改业务逻辑
"""
import os
import sys
import json

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from window_locator import WindowLocator, locator
from template_locator import TemplateLocator

# 全局实例
_tloc = None
_inventory_roi = None
_inventory_cells = None
_stash_roi = None
_stash_cells = None

# 配置常量
CONFIG_PATH = "auto_buy_config.json"

def init_template_locator(server="china"):
    """初始化 TemplateLocator，自动定位 Inventory 和 Stash
    
    Args:
        server: "global" 或 "china"
        
    Returns:
        dict: {
            "inventory_ok": bool,
            "stash_ok": bool,
            "inventory_roi": (x1, y1, x2, y2) or None,
            "stash_roi": (x1, y1, x2, y2) or None,
        }
    """
    global _tloc, _inventory_roi, _inventory_cells, _stash_roi, _stash_cells
    
    print("[Locator] 初始化 TemplateLocator...")
    
    # 1. 检测游戏窗口（如果尚未检测）
    if not locator.window:
        if not locator.detect(server):
            print("[Locator] ❌ 未检测到游戏窗口")
            return {
                "inventory_ok": False,
                "stash_ok": False,
                "inventory_roi": None,
                "stash_roi": None,
            }
    
    # 2. 创建 TemplateLocator 实例
    _tloc = TemplateLocator(locator, debug=True)
    
    # 3. 定位 Inventory
    print("[Locator] 定位 Inventory...")
    inventory_result = _tloc.locate_inventory()
    if inventory_result["success"]:
        _inventory_roi = inventory_result["roi_rel"]
        print(f"[Locator] ✓ Inventory ROI: {_inventory_roi}")
        
        # 生成格子坐标
        cells_result = _tloc.generate_inventory_cells()
        if cells_result["success"]:
            _inventory_cells = cells_result["cells_map"]
            print(f"[Locator] ✓ Inventory 格子: {len(_inventory_cells)} 个")
        else:
            print(f"[Locator] ❌ Inventory 格子生成失败: {cells_result['message']}")
    else:
        print(f"[Locator] ❌ Inventory 定位失败: {inventory_result['message']}")
    
    # 4. 定位 Stash
    print("[Locator] 定位 Stash...")
    stash_result = _tloc.locate_stash()
    if stash_result["success"]:
        _stash_roi = stash_result["roi_rel"]
        print(f"[Locator] ✓ Stash ROI: {_stash_roi}")
        
        # 生成格子坐标
        cells_result = _tloc.generate_stash_cells()
        if cells_result["success"]:
            _stash_cells = cells_result["cells_map"]
            print(f"[Locator] ✓ Stash 格子: {len(_stash_cells)} 个")
        else:
            print(f"[Locator] ❌ Stash 格子生成失败: {cells_result['message']}")
    else:
        print(f"[Locator] ❌ Stash 定位失败: {stash_result['message']}")
    
    return {
        "inventory_ok": _inventory_roi is not None,
        "stash_ok": _stash_roi is not None,
        "inventory_roi": _inventory_roi,
        "stash_roi": _stash_roi,
    }

def get_inventory_roi():
    """获取 Inventory ROI（相对窗口坐标）
    
    Returns:
        dict: {"LEFT": x1, "TOP": y1, "RIGHT": x2, "BOTTOM": y2}
              或 None（定位失败时）
    """
    if _inventory_roi is None:
        return None
    x1, y1, x2, y2 = _inventory_roi
    return {"LEFT": x1, "TOP": y1, "RIGHT": x2, "BOTTOM": y2}

def get_inventory_cells():
    """获取 Inventory 格子坐标（相对窗口坐标）
    
    Returns:
        list: [{"region": [x1, y1, x2, y2]}, ...]
              或 []（定位失败时）
    """
    if _inventory_cells is None:
        return []
    result = []
    for cell in _inventory_cells:
        p1, p2 = cell
        x1, y1 = p1[0], p1[1]
        x2, y2 = p2[0], p2[1]
        result.append({"region": [x1, y1, x2, y2]})
    return result

def get_stash_roi():
    """获取 Stash ROI（相对窗口坐标）
    
    Returns:
        dict: {"LEFT": x1, "TOP": y1, "RIGHT": x2, "BOTTOM": y2}
              或 None（定位失败时）
    """
    if _stash_roi is None:
        return None
    x1, y1, x2, y2 = _stash_roi
    return {"LEFT": x1, "TOP": y1, "RIGHT": x2, "BOTTOM": y2}

def get_stash_cells():
    """获取 Stash 格子坐标（相对窗口坐标）
    
    Returns:
        list: [{"region": [x1, y1, x2, y2]}, ...]
              或 []（定位失败时）
    """
    if _stash_cells is None:
        return []
    result = []
    for cell in _stash_cells:
        p1, p2 = cell
        x1, y1 = p1[0], p1[1]
        x2, y2 = p2[0], p2[1]
        result.append({"region": [x1, y1, x2, y2]})
    return result

def fallback_to_config():
    """从配置文件读取备用配置（当 TemplateLocator 失败时使用）
    
    Returns:
        dict: 包含 roi, stash_open_pos, hsv_config
    """
    hsv_config = {
        "h_min": 105,
        "h_max": 180,
        "s_min": 70,
        "s_max": 255,
        "v_min": 70,
        "v_max": 255
    }
    roi = {"LEFT": 80, "TOP": 285, "RIGHT": 857, "BOTTOM": 1057}
    stash_open_pos = [900, 380]
    
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
                if "hsv" in config:
                    hsv_config.update(config["hsv"])
                if "roi" in config and config["roi"]:
                    roi = config["roi"]
                if "stash_open_pos" in config and len(config["stash_open_pos"]) == 2:
                    stash_open_pos = config["stash_open_pos"]
        except Exception as e:
            print(f"[Locator] 加载配置文件失败: {e}")
    
    return {
        "roi": roi,
        "stash_open_pos": stash_open_pos,
        "hsv_config": hsv_config,
    }

# 初始化标志
_initialized = False

def ensure_initialized(server="china"):
    """确保 TemplateLocator 已初始化"""
    global _initialized
    if not _initialized:
        init_template_locator(server)
        _initialized = True

# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("TemplateLocator 整合测试")
    print("=" * 60)
    
    # 初始化
    result = init_template_locator("china")
    
    print("\n=== 结果 ===")
    print(f"Inventory 定位: {'✓' if result['inventory_ok'] else '✗'}")
    print(f"Stash 定位: {'✓' if result['stash_ok'] else '✗'}")
    
    if result["inventory_ok"]:
        roi = get_inventory_roi()
        cells = get_inventory_cells()
        print(f"\nInventory ROI: {roi}")
        print(f"Inventory 格子数: {len(cells)}")
        if cells:
            print(f"第一个格子: {cells[0]}")
    
    if result["stash_ok"]:
        roi = get_stash_roi()
        cells = get_stash_cells()
        print(f"\nStash ROI: {roi}")
        print(f"Stash 格子数: {len(cells)}")
        if cells:
            print(f"第一个格子: {cells[0]}")
    
    print("\n" + "=" * 60)
