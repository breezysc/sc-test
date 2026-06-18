# POE2 AutoBuy - 自动购买与存仓工具

Path of Exile 2 自动购买与智能存仓工具，基于 HSV 颜色检测和模板匹配技术。

## 功能特性

- **自动购买**: 检测屏幕上紫色高亮物品，Ctrl+Click 自动购买
- **智能存仓**: 背包满后自动 F5 回城，打开仓库并智能存仓
- **HSV 物品检测**: 基于 HSV 颜色空间检测高亮物品（紫色）
- **模板匹配**: 使用模板匹配定位仓库位置
- **置信度检测**: 智能判断格子是否为空，避免无效点击
- **优先级控制**: 购买动作优先于存仓动作
- **双服支持**: 支持国际服 (Path of Exile 2) 和国服 (流放之路)

## 目录结构

```
f:\scgit\
├── auto_buy_new.py          # 主程序 - 自动购买与存仓
├── hsv_detector.py          # HSV 检测器模块
├── auto_buy_debug_tool.py   # 统一调试工具 (GUI)
├── stash_debugger.py        # 仓库调试工具 (独立)
├── hsv_debug_tool.py        # HSV 调试工具 (独立)
├── config.json              # 主配置文件
├── auto_buy_config.json     # 自动化配置 (含仓库格子、ROI等)
├── inventory_config.json    # 背包格子配置
├── good.json                # HSV 颜色配置
└── cc.png                   # 空格子模板图片
```

## 依赖安装

```bash
pip install opencv-python numpy pyautogui mss psutil Pillow
```

**依赖说明:**
- `opencv-python`: 图像处理和模板匹配
- `numpy`: 数值计算
- `pyautogui`: 鼠标键盘自动化
- `mss`: 高性能屏幕截图
- `psutil`: CPU 监控
- `Pillow`: 图像处理

## 快速开始

### 1. 配置游戏窗口

首次运行前需要配置检测区域：

```bash
python auto_buy_debug_tool.py
```

在调试工具中：
1. **HSV 调试** 标签页：点击"选择检测区域"框选游戏中的物品检测区域
2. **仓库配置** 标签页：
   - 点击"识别窗口"识别游戏窗口
   - 点击"选择仓库位置"选择仓库 NPC 位置
   - 设置行列数并框选背包区域
3. 保存配置

### 2. 运行主程序

**正常运行:**
```bash
python auto_buy_new.py
```

**测试存仓功能:**
```bash
python auto_buy_new.py --test-stash
```

## 配置说明

### auto_buy_config.json

主配置文件，包含以下关键配置：

| 配置项 | 说明 |
|--------|------|
| `hsv` | HSV 颜色检测参数 (h_min/h_max, s_min/s_max, v_min/v_max) |
| `roi` | 检测区域坐标 (LEFT, TOP, RIGHT, BOTTOM) |
| `stash_open_pos` | 仓库 NPC 点击位置 |
| `cells_map` | 仓库格子坐标列表 |
| `stash_template` | 仓库模板图片数据 |
| `stash_confidence_region` | 仓库打开状态检测区域 |
| `inventory_confidence_region` | 背包置信度检测区域 |

### good.json

HSV 颜色参数配置：

```json
{
  "h_min": 120,
  "h_max": 180,
  "s_min": 102,
  "s_max": 255,
  "v_min": 106,
  "v_max": 255
}
```

### inventory_config.json

背包格子配置：

```json
{
  "monitor_region": [942, 725, 1711, 1055],
  "target_cells": [
    {"name": "格子1", "x1": 942, "y1": 725, "x2": 1009, "y2": 791},
    ...
  ],
  "similarity_threshold": 0.85
}
```

## 使用流程

### 正常购买流程

1. 启动游戏并进入市场/商店界面
2. 运行 `python auto_buy_new.py`
3. 工具自动检测紫色高亮物品
4. 发现物品后 Ctrl+Click 购买
5. 购买后移动鼠标到安全位置
6. 按 F5 回城
7. 自动打开仓库并执行存仓
8. 返回市场继续检测

### 调试工具使用

**auto_buy_debug_tool.py** 是统一的调试界面，包含：

#### HSV 调试标签页
- 选择检测区域 - 框选游戏中物品出现区域
- 开始/停止 - 实时预览 HSV 检测效果
- 自动点击 - 测试自动购买功能
- HSV 滑块 - 调整颜色检测参数

#### 仓库配置标签页
- 识别窗口 - 识别游戏窗口位置
- 选择仓库位置 - 选择仓库 NPC 位置
- 选择仓库检测区域 - 框选仓库 UI 区域
- 选择背包区域 - 框选背包格子区域
- 测试存仓 - 测试存仓功能

## HSV 参数说明

工具通过 HSV 颜色空间检测紫色高亮物品：

- **H (Hue)**: 色调，0-180 范围，紫色范围约 105-180
- **S (Saturation)**: 饱和度，0-255 范围，检测高亮度物品设置为 70-255
- **V (Value)**: 明度，0-255 范围，检测高亮度物品设置为 70-255

### 调试建议

1. 启动 `auto_buy_debug_tool.py` 或 `hsv_debug_tool.py`
2. 在 HSV 调试页面实时观察检测效果
3. 调整滑块直到只有目标物品被高亮
4. 避免包含背景中的干扰颜色

## 命令行参数

```bash
python auto_buy_new.py [选项]

选项:
  -t, --test-stash    测试存仓流程（不等待超时）
```

## 状态机与优先级

工具使用优先级状态机管理动作：

| 状态 | 优先级 | 说明 |
|------|--------|------|
| PURCHASE_ACTIVE | 0 (最高) | 购买动作进行中 |
| PURCHASE_PENDING | 1 | 购买动作待执行 |
| STORAGE_ACTIVE | 2 | 存仓动作进行中 |
| STORAGE_PENDING | 3 | 存仓动作待执行 |
| IDLE | 4 (最低) | 空闲状态 |

**优先级规则**: 购买动作可随时中断存仓动作，确保不会错过购买机会。

## 存仓置信度

工具使用模板匹配判断格子是否为空：

- 阈值: 0.85 (EMPTY_CELL_THRESHOLD)
- 高于阈值: 判定为空格子，跳过
- 低于阈值: 判定为有物品，执行存仓

格子截图保存在 `stash_debug/` 目录供调试分析。

## 注意事项

1. **游戏窗口**: 工具需要游戏窗口在前景运行
2. **屏幕分辨率**: 配置基于当前屏幕分辨率，更换分辨率后需要重新配置
3. **安全区域**: 购买后将鼠标移到安全位置避免误操作
4. **F5 快捷键**: 工具使用 F5 作为回城键，确保游戏内该键位未被修改

## 故障排除

### 无法识别游戏窗口
- 确认游戏窗口标题包含 "Path of Exile" 或 "流放之路"
- 尝试以管理员权限运行

### 仓库位置偏移
- 重新运行调试工具选择仓库位置
- 检查是否更换了游戏窗口位置

### 物品检测不准确
- 调整 HSV 参数
- 确保检测区域 (ROI) 正确框选

### 存仓操作失败
- 检查仓库格子配置是否正确
- 确认 `cc.png` 空格子模板存在
- 查看 `stash_debug/` 目录下的截图分析

## 文件说明

| 文件 | 说明 |
|------|------|
| `auto_buy_new.py` | 主程序入口 |
| `hsv_detector.py` | HSV 物品检测核心模块 |
| `auto_buy_debug_tool.py` | 统一调试工具 (Tkinter GUI) |
| `stash_debugger.py` | 仓库配置独立工具 |
| `hsv_debug_tool.py` | HSV 调试独立工具 |
| `config.json` | 工具配置 |
| `auto_buy_config.json` | 自动化主配置 |
| `inventory_config.json` | 背包格子配置 |
| `good.json` | HSV 参数配置 |
| `cc.png` | 空格子模板图片 |
| `stash_debug/` | 存仓调试截图目录 |
| `detect_debug/` | 物品检测调试目录 |

## License

MIT License
