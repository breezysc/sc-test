"""
config 坐标迁移脚本 - 把「屏幕绝对坐标」→「相对游戏窗口的坐标」

使用:
    1. 先运行 Path of Exile 2 游戏，确保窗口存在
    2. 运行: python migrate_config_to_relative.py [config.json]

会:
    - 自动检测游戏窗口位置
    - 读取指定的配置文件，将坐标从屏幕绝对坐标转换为相对坐标
    - 备份原配置为 .backup
    - 添加 "coord_system": "relative" 标记

兼容的字段:
    - roi.LEFT, roi.TOP, roi.RIGHT, roi.BOTTOM
    - stash_open_pos [x, y]
    - cells_map [[[x1,y1],[x2,y2]], ...]
    - stash_confidence_region [x1, y1, x2, y2]
"""

import json
import os
import sys
import copy
import ctypes
from ctypes import wintypes
from window_locator import locator


CONFIG_FIELDS_TO_CONVERT = [
    "roi",
    "stash_open_pos",
    "cells_map",
    "stash_confidence_region",
]


def detect_game_window(server="global"):
    """复用 window_locator 的检测逻辑"""
    return locator.detect(server)


def convert_value(val, win_left, win_top):
    """递归转换坐标值"""
    if isinstance(val, dict):
        # 字典: 可能是 roi {"LEFT": x, "TOP": y, "RIGHT": x, "BOTTOM": y}
        if set(val.keys()) & {"LEFT", "TOP", "RIGHT", "BOTTOM"}:
            new = dict(val)
            if "LEFT" in new:
                new["LEFT"] = int(new["LEFT"]) - win_left
            if "TOP" in new:
                new["TOP"] = int(new["TOP"]) - win_top
            if "RIGHT" in new:
                new["RIGHT"] = int(new["RIGHT"]) - win_left
            if "BOTTOM" in new:
                new["BOTTOM"] = int(new["BOTTOM"]) - win_top
            return new
        return val
    elif isinstance(val, list):
        # 列表: 可能是 cells_map 或 stash_open_pos 或 stash_confidence_region
        if len(val) == 2 and all(isinstance(v, (int, float)) for v in val):
            # stash_open_pos [x, y]
            return [int(val[0]) - win_left, int(val[1]) - win_top]
        elif len(val) == 4 and all(isinstance(v, (int, float)) for v in val):
            # stash_confidence_region [x1, y1, x2, y2]
            return [
                int(val[0]) - win_left,
                int(val[1]) - win_top,
                int(val[2]) - win_left,
                int(val[3]) - win_top,
            ]
        elif len(val) >= 1 and isinstance(val[0], list):
            # cells_map [[[x1,y1],[x2,y2]], ...]
            return [convert_value(item, win_left, win_top) for item in val]
        return val
    return val


def convert_config(config, win_left, win_top):
    """转换整个配置 dict"""
    new_config = copy.deepcopy(config)

    # 逐字段转换（仅当字段存在时）
    for field in CONFIG_FIELDS_TO_CONVERT:
        if field in new_config:
            new_config[field] = convert_value(new_config[field], win_left, win_top)

    # 兼容: cells 数组 [{"region": [x1,y1,x2,y2]}, ...]
    if "cells" in new_config and isinstance(new_config["cells"], list):
        new_cells = []
        for cell in new_config["cells"]:
            if isinstance(cell, dict) and "region" in cell:
                new_cell = dict(cell)
                region = cell["region"]
                if isinstance(region, list) and len(region) == 4:
                    new_cell["region"] = [
                        int(region[0]) - win_left,
                        int(region[1]) - win_top,
                        int(region[2]) - win_left,
                        int(region[3]) - win_top,
                    ]
                new_cells.append(new_cell)
            else:
                new_cells.append(cell)
        new_config["cells"] = new_cells

    # 添加标记
    new_config["coord_system"] = "relative"
    return new_config


def main():
    if len(sys.argv) >= 2:
        config_path = sys.argv[1]
    else:
        # 默认为 auto_buy_config.json
        config_path = "auto_buy_config.json"

    if not os.path.exists(config_path):
        print(f"[错误] 配置文件不存在: {config_path}")
        sys.exit(1)

    # 1. 检测游戏窗口
    print("[1/3] 正在检测游戏窗口...")
    server = "global"
    if len(sys.argv) >= 3:
        server = sys.argv[2]
    if not detect_game_window(server):
        print(f"[错误] 未检测到游戏窗口，请先启动游戏")
        # 允许用户手动输入窗口位置
        print("  或者手动输入窗口坐标:")
        win_left = int(input("  win_left="))
        win_top = int(input("  win_top="))
    else:
        win = locator.window
        print(f"  ✓ 检测到: {win['title']}")
        print(f"  位置: ({win['left']}, {win['top']})  尺寸: {win['width']}x{win['height']}")
        win_left = win["left"]
        win_top = win["top"]

    # 2. 读取配置
    print(f"[2/3] 正在读取配置: {config_path}")
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # 检查是否已经是 relative 坐标
    if config.get("coord_system") == "relative":
        print("  ✓ 配置已经是相对坐标系统，无需转换")
        sys.exit(0)

    # 3. 转换并保存
    print("[3/3] 正在转换坐标并保存...")
    new_config = convert_config(config, win_left, win_top)

    # 备份原文件
    backup_path = config_path + ".backup"
    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"  ✓ 已备份原配置到: {backup_path}")

    # 写回
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(new_config, f, ensure_ascii=False, indent=2)
    print(f"  ✓ 已写入新配置到: {config_path}")
    print(f"  ✓ 标记: coord_system = relative")
    print("\n完成！现在 auto_buy_new.py 和 auto_buy_debug_tool.py 都将使用相对坐标。")


if __name__ == "__main__":
    main()
