# PROJECT_HANDOVER.md

> Path of Exile 2 自动购物脚本 - 项目交接文档
> Windows 环境 | Python | OpenCV matchTemplate | 800x600 固定窗口

---

## 1. 项目目标

本项目的核心目标是构建一个 **自动化的 Path of Exile 2 辅助工具**，分为两个主要功能：

1. **自动购物** - 在通货兑换栏中识别高亮物品并自动购买
2. **自动存仓** - 将背包中的物品存入仓库格子

**近期重构目标**：将坐标系统从「硬编码的屏幕绝对坐标」改为「游戏窗口相对坐标 + 锚点自动定位」，消除人工框选流程。

**重构原则**：
- 窗口固定为 **800×600**（无需支持任意分辨率和缩放）
- 所有坐标基于「游戏窗口左上角 (0,0)」计算
- 使用 **Anchor + Fixed Offset** 方案自动识别 UI 区域
- 不修改业务逻辑代码（`auto_buy_new.py` 中的购买和存仓逻辑不动）

---

## 2. 当前已完成功能

| 模块 | 状态 | 文件 | 说明 |
|------|------|------|------|
| WindowLocator | ✅ 已完成 | [window_locator.py](file:///F:/scgit/window_locator.py) | 游戏窗口检测 + 坐标双向转换 + 截图 |
| TemplateLocator (Inventory) | ✅ 已完成 | [template_locator.py](file:///F:/scgit/template_locator.py) | Inventory 锚点定位 + ROI 计算 |
| Offset 计算脚本 (Inventory) | ✅ 已完成 | [_calc_offset.py](file:///F:/scgit/_calc_offset.py) | 根据用户给的屏幕坐标计算 anchor offset |
| Inventory 锚点配置 | ✅ 已完成 | [template_locator_config.json](file:///F:/scgit/template_locator_config.json) | Inventory 模板路径、阈值、offset |
| Inventory 锚点图片 | ✅ 已完成 | [templates/inventory/anchor.png](file:///F:/scgit/templates/inventory/anchor.png) | Inventory 标题栏截图 |
| Inventory ROI 写入配置 | ✅ 已完成 | [template_locator.py](file:///F:/scgit/template_locator.py#L416-L445) | `write_roi_to_business_config()` 方法 |

**尚未完成**：

| 模块 | 状态 | 文件 | 说明 |
|------|------|------|------|
| TemplateLocator (Stash) | ❌ 待实现 | 需在 template_locator.py 中加 `locate_stash()` | Stash 仓库区域锚点定位 |
| Stash 锚点图片 | ❌ 待提供 | `templates/stash/anchor.png` | 需用户截取 Stash 标题栏 |
| Stash 格子坐标自动生成 | ❌ 待实现 | 需在 TemplateLocator 中实现 | 基于 stash_roi 自动生成 60 格 |
| Inventory 格子坐标自动生成 | ❌ 待实现 | 需在 TemplateLocator 中实现 | 基于 inventory_roi 动态生成 cells_map |
| Currency Exchange Locator | ❌ 未开始 | 需新建 | 通货兑换栏锚点定位 |
| 业务逻辑不修改 | — | [auto_buy_new.py](file:///F:/scgit/auto_buy_new.py) | 不修改购买/存仓核心逻辑 |

---

## 3. 当前目录结构

```
F:\scgit\
├── window_locator.py                 # 游戏窗口定位器（核心）
├── template_locator.py               # 锚点定位器（MVP：已实现 Inventory）
├── template_locator_config.json      # 锚点配置（threshold、offset、scale 等）
├── auto_buy_new.py                   # 业务主程序（不修改）
├── auto_buy_config.json              # 业务配置（roi、cells_map、stash_open_pos、detection）
├── inventory_config.json             # 旧格式兼容配置（保留）
├── config.json                       # 商店格子配置（保留）
│
├── _calc_offset.py                   # Inventory offset 计算脚本
├── _test_tloc.py                     # TemplateLocator 测试脚本
├── _debug_windows.py                 # 窗口调试脚本
│
├── auto_buy_debug_tool.py            # 旧版调试工具（保留）
├── hsv_detector.py                   # HSV 颜色检测（保留）
├── hsv_debug_tool.py                 # HSV 调试工具（保留）
├── stash_debugger.py                 # 旧版 Stash 调试（保留）
│
├── templates/
│   └── inventory/
│       └── anchor.png                # Inventory 锚点图（已截取）
│   └── stash/
│       └── anchor.png                # ❌ 待截取
│
├── template_debug/                   # TemplateLocator 调试截图输出目录
│   └── inventory_YYYYMMDD_HHMMSS.png
│
├── stash_debug/                      # Stash 调试输出目录（旧逻辑）
├── .gitignore
└── README.md
```

---

## 4. WindowLocator 设计

### 4.1 文件
[window_locator.py](file:///F:/scgit/window_locator.py)

### 4.2 模块职责
1. 自动检测 Path of Exile 2 游戏窗口（支持国际服/国服）
2. 提供「相对游戏窗口坐标」↔「屏幕绝对坐标」**双向转换**
3. 提供游戏窗口/区域截图能力
4. 提供基于相对坐标的点击封装

### 4.3 使用方式

```python
from window_locator import locator

# 1. 检测窗口
locator.detect("global")   # 国际服: "Path of Exile 2" / "Path of Exile"
locator.detect("china")    # 国服: "流放之路"

# 2. 检查是否已检测
if locator.detected:
    win = locator.window  # {"hwnd","title","left","top","right","bottom","width","height"}
    print(f"窗口位置: ({win['left']}, {win['top']}) 尺寸: {win['width']}x{win['height']}")

# 3. 坐标转换
screen_x, screen_y = locator.to_screen(100, 200)        # 相对坐标 -> 屏幕坐标
rel_x, rel_y = locator.to_relative(screen_x, screen_y)  # 屏幕坐标 -> 相对坐标

# 4. 截图
full_shot = locator.grab_window()                       # 截取整个游戏窗口
roi_shot = locator.grab_region(100, 100, 400, 300)      # 截取窗口内指定区域

# 5. 点击
locator.click(100, 200)                                 # 在相对坐标 (100,200) 点击
```

### 4.4 窗口检测逻辑
- 使用 Windows API `EnumWindows` 枚举所有窗口
- 按标题关键词匹配（国际服: "Path of Exile 2" / "Path of Exile"；国服: "流放之路"）
- 排除浏览器窗口（chrome/firefox/edge/iexplore/safari/opera/brave/浏览器）
- 优先选标题含 "Path of Exile 2" 的窗口，否则按标题长度排序取最短

### 4.5 坐标系统

**屏幕绝对坐标系统**：
- 原点位于物理屏幕左上角
- x 轴向右，y 轴向下
- Window 位置: `(window.left, window.top)` 表示游戏窗口左上角的屏幕坐标

**相对游戏窗口坐标系统**：
- 原点位于游戏窗口左上角 `(0, 0)`
- 最大值: `(window.width-1, window.height-1)`
- 当前项目窗口尺寸固定 **800×600**

**双向转换公式**：
```
屏幕坐标 = 相对坐标 + 窗口位置偏移
  screen_x = rel_x + window.left
  screen_y = rel_y + window.top

相对坐标 = 屏幕坐标 - 窗口位置偏移
  rel_x = screen_x - window.left
  rel_y = screen_y - window.top
```

### 4.6 窗口信息结构（Window dict）
```python
{
    "hwnd": <ctypes.c_void_p>,   # 窗口句柄
    "title": "Path of Exile 2",  # 窗口标题
    "left": 100,                  # 窗口左上角屏幕 X
    "top": 100,                   # 窗口左上角屏幕 Y
    "right": 900,                 # 窗口右下角屏幕 X
    "bottom": 700,                # 窗口右下角屏幕 Y
    "width": 800,                 # 窗口宽度（固定）
    "height": 600                 # 窗口高度（固定）
}
```

---

## 5. TemplateLocator 设计

### 5.1 文件
[template_locator.py](file:///F:/scgit/template_locator.py)

### 5.2 设计原则
- **Anchor + Fixed Offset** 方案
- 所有坐标使用 **相对游戏窗口坐标**
- 不修改业务逻辑，仅提供 ROI/格子坐标给 `auto_buy_new.py` 使用

### 5.3 Anchor + Fixed Offset 方案原理

```
┌───────────────────────────────────────────┐
│ 游戏窗口 800x600                           │
│                                           │
│   [ANCHOR]  ← 锚点（UI 标题栏截图）        │
│       │                                   │
│       │ dx1, dy1  ← 固定像素偏移           │
│       └──────────┐                        │
│                  ▼                        │
│           ┌─────────────────┐             │
│           │    ROI 区域      │  ← 检测区域 │
│           │ (背包格子/仓库)  │             │
│           └─────────────────┘             │
│                                           │
└───────────────────────────────────────────┘

锚点左上角: (anchor_x, anchor_y)  ← 由 matchTemplate 找到
ROI 左上角: (anchor_x + dx1, anchor_y + dy1)
ROI 右下角: (anchor_x + dx2, anchor_y + dy2)
```

### 5.4 核心算法流程（以 Inventory 为例）

1. **截取整个游戏窗口** - `locator.grab_window()` → `np.ndarray (H, W, 3)` BGR
2. **加载锚点模板** - `cv2.imread("templates/inventory/anchor.png")`
3. **多尺度 matchTemplate** - 模板在 `[0.7, 1.5]` 倍之间缩放，步长 0.05
   - 使用 `cv2.TM_CCOEFF_NORMED` 方法
   - 缩放小于 1.0 用 `cv2.INTER_AREA`，大于 1.0 用 `cv2.INTER_CUBIC`
   - 取置信度最高的匹配结果作为锚点
4. **计算 ROI** - 锚点位置 + 固定 offset（像素值）
5. **保存调试截图** - 画出锚点框、ROI 框、top-3 候选框

### 5.5 TemplateLocator 类 API

```python
class TemplateLocator:
    def __init__(self, window_locator, config_path="template_locator_config.json", debug=True):
        """
        Args:
            window_locator: WindowLocator 实例（已调用 detect()）
            config_path: 锚点配置文件路径
            debug: 是否输出调试截图到 template_debug/ 目录
        """

    def locate_inventory(self, threshold=None):
        """定位 Inventory 区域。

        Returns: dict: {
            "success": bool,
            "anchor_rel": (x, y) | None,       # 锚点左上角 (相对窗口)
            "anchor_size": (w, h) | None,      # 锚点在最佳匹配尺度下的大小
            "confidence": float,                # matchTemplate 最高置信度
            "scale": float | None,              # 最佳匹配的缩放系数 (如 1.0)
            "roi_rel": (x1, y1, x2, y2) | None, # 完整 ROI 区域 (相对窗口)
            "roi_dict": {"LEFT", "TOP", "RIGHT", "BOTTOM"} | None,
            "debug_image": str | None,          # 调试截图路径
            "message": str
        }
        """

    def write_roi_to_business_config(self, business_config_path="auto_buy_config.json", threshold=None):
        """定位成功后，将 roi 字段写入 auto_buy_config.json（保留其他字段不变）。
        Returns: (success: bool, message: str)
        """

    # 内部辅助方法:
    def _multi_scale_match(self, window_img, template, scale_min, scale_max, scale_step):
        """多尺度模板匹配。
        Returns: {
            "match_x", "match_y", "confidence", "scale",
            "tpl_w", "tpl_h", "candidates": [...]
        }
        """

    def _load_template(self, path):
        """加载模板图片，带文件缓存。失败返回 None。"""

    def _save_debug_shot(self, window_img, template, best, offset, success):
        """保存调试截图到 template_debug/ 目录。
        截图内容: 锚点框(红色) + ROI 框(绿色) + top-3 候选(浅红色虚线) + 状态文字。
        """
```

### 5.6 命令行入口

```bash
# 测试 Inventory 锚点定位
python template_locator.py --server global

# 定位成功后写入 auto_buy_config.json
python template_locator.py --server global --write-config
```

### 5.7 调试截图输出
- 目录: `template_debug/`
- 文件名: `inventory_YYYYMMDD_HHMMSS.png`
- 内容:
  - **红色粗框**: 锚点匹配区域
  - **绿色框**: 计算出的 ROI 区域
  - **浅红色虚线框**: top-3 候选匹配位置
  - **文字**: 状态(OK/FAILED)、置信度、scale、窗口尺寸

---

## 6. Inventory Locator 实现细节

### 6.1 配置 (template_locator_config.json)

```json
{
  "inventory": {
    "template_path": "templates/inventory/anchor.png",
    "threshold": 0.7,
    "scale_min": 0.7,
    "scale_max": 1.5,
    "scale_step": 0.05,
    "offset": {
      "dx1": -165,      // ROI 左上角 X 偏移
      "dy1": 295,       // ROI 左上角 Y 偏移
      "dx2": 189,       // ROI 右下角 X 偏移
      "dy2": 443        // ROI 右下角 Y 偏移
    }
  }
}
```

### 6.2 锚点图片 (templates/inventory/anchor.png)
- **内容**: Path of Exile 2 游戏中背包标题栏（"Inventory" 文字所在区域）
- **要求**: 截取的图片必须清晰、唯一（在窗口内只有一处可匹配）
- **尺寸**: 根据实际截图尺寸而定（无需固定尺寸，因使用多尺度匹配）

### 6.3 坐标计算流程

用户提供的屏幕坐标（示例）:
```
背包 ROI (屏幕绝对坐标): (457, 375) - (811, 523)
```

步骤（由 `_calc_offset.py` 执行）:
1. 检测游戏窗口，获取 `window.left, window.top`
2. 将屏幕坐标转换为相对坐标:
   ```
   rel_x1 = 457 - window.left
   rel_y1 = 375 - window.top
   rel_x2 = 811 - window.left
   rel_y2 = 523 - window.top
   ```
3. 用 `matchTemplate` 在游戏窗口截图中找到锚点位置 `(anchor_x, anchor_y)`
4. 计算 offset:
   ```
   dx1 = rel_x1 - anchor_x
   dy1 = rel_y1 - anchor_y
   dx2 = rel_x2 - anchor_x
   dy2 = rel_y2 - anchor_y
   ```
5. 将 offset 写入 `template_locator_config.json`

实际生成的配置（800x600 窗口下）:
```json
"offset": {
  "dx1": -165,
  "dy1": 295,
  "dx2": 189,
  "dy2": 443
}
```

### 6.4 运行时定位流程

在 `template_locator.py` 的 `locate_inventory()` 方法中:
1. 截取游戏窗口 (800×600 BGR image)
2. 加载 `templates/inventory/anchor.png`
3. 多尺度匹配: 缩放模板 0.7x → 1.5x，步长 0.05
4. 找到最佳匹配: `(anchor_x, anchor_y)` + 置信度 `conf`
5. 如果 `conf >= 0.7`（阈值）:
   - 计算 ROI: `roi_x1 = anchor_x + dx1`, `roi_y1 = anchor_y + dy1`, `roi_x2 = anchor_x + dx2`, `roi_y2 = anchor_y + dy2`
   - 返回 ROI 和锚点信息
6. 保存调试截图

计算得到的 Inventory ROI（相对窗口坐标，示例）:
```
roi_dict = {"LEFT": 447, "TOP": 359, "RIGHT": 801, "BOTTOM": 507}
```

### 6.5 Inventory 格子系统

**配置文件中当前存储格式**（`auto_buy_config.json` 的 cells_map）:
```json
"cells_map": [
  [[953, 734], [1017, 799]],  // 格子1: [[x1,y1], [x2,y2]] - 屏幕绝对坐标
  [[1017, 734], [1081, 799]], // 格子2
  // ... 共 60 格 (12 列 × 5 行)
]
```

**注意**: 当前 cells_map 中存储的是**屏幕绝对坐标**，尚未改为相对坐标。
这是后续需要完成的任务。

**格子自动生成思路**（待实现）:
- Inventory ROI: `(447, 359) - (801, 507)`（相对窗口坐标）
- 宽度: `801 - 447 = 354` 像素
- 高度: `507 - 359 = 148` 像素
- 列数: 12，行数: 5
- 每格宽度: `354 / 12 = 29.5` 像素
- 每格高度: `148 / 5 = 29.6` 像素
- 格子坐标: 遍历行列，计算 `x1 = roi_left + col * cell_width`，`y1 = roi_top + row * cell_height`，`x2 = x1 + cell_width`，`y2 = y1 + cell_height`

**目标**: 删除配置文件中的 cells_map，由程序在初始化时基于 ROI 动态生成。

---

## 7. 当前使用的锚点方案

### 7.1 方案名称
**Anchor + Fixed Offset（锚点 + 固定像素偏移）**

### 7.2 为什么选这个方案
| 方案 | 优点 | 缺点 | 是否采用 |
|------|------|------|---------|
| **Anchor + Fixed Offset** | 简单、可靠、精确，无需知道窗口位置历史，适配窗口移动 | 需要预先截取锚点图 | ✅ 采用 |
| 直接 ROI 固定坐标 | 最简单 | 窗口移动失效、分辨率变化失效 | ❌ 已放弃 |
| 百分比偏移 | 支持窗口缩放 | 800x600 固定窗口下精度不如像素偏移 | ❌ 不需要 |
| 特征点匹配（SIFT/ORB） | 理论上最鲁棒 | 实现复杂、性能开销大 | ❌ 过度设计 |

### 7.3 方案约束

1. **固定 800×600 窗口**: 游戏窗口必须设置为 800×600 分辨率
2. **不支持窗口缩放**: 不需要考虑 DPI 缩放、分辨率变化
3. **offset 是固定像素值**: 不会随窗口位置改变（只会随 anchor 位置改变，而 anchor 是相对窗口定位的）
4. **多尺度匹配保留为容错**: 锚点模板在 0.7x~1.5x 之间缩放以提高匹配成功率，但实际最佳匹配通常是 1.0x（因为窗口固定 800x600）
5. **锚点必须唯一**: 锚点截图必须在游戏窗口内只有一处可匹配（如标题栏特定文字）

### 7.4 完整定位流程（运行时）

```
用户启动脚本
│
├─► WindowLocator.detect()
│   找到游戏窗口位置 (window.left, window.top)
│   无需任何人工配置
│
├─► TemplateLocator.locate_inventory()
│   │
│   ├─► 截取游戏窗口截图 (800x600, BGR)
│   │
│   ├─► 加载 templates/inventory/anchor.png
│   │
│   ├─► 多尺度 matchTemplate
│   │   │  0.70x: 尝试匹配
│   │   │  0.75x: 尝试匹配
│   │   │  ...
│   │   │  1.00x: ← 通常最高置信度 (≥0.95)
│   │   │  ...
│   │   │  1.50x: 尝试匹配
│   │   └─► 取置信度最高的结果作为锚点
│   │
│   └─► anchor_x, anchor_y + offset → roi_rel
│       roi_left   = anchor_x + dx1
│       roi_top    = anchor_y + dy1
│       roi_right  = anchor_x + dx2
│       roi_bottom = anchor_y + dy2
│
└─► 业务逻辑使用 roi_rel（相对坐标）
    点击时通过 locator.to_screen(rel_x, rel_y) 转换为屏幕坐标
```

---

## 8. 当前配置文件格式

### 8.1 template_locator_config.json（锚点配置）

**位置**: [template_locator_config.json](file:///F:/scgit/template_locator_config.json)

**格式**:
```json
{
  "inventory": {
    "template_path": "templates/inventory/anchor.png",
    "threshold": 0.7,
    "scale_min": 0.7,
    "scale_max": 1.5,
    "scale_step": 0.05,
    "offset": {
      "dx1": -165,
      "dy1": 295,
      "dx2": 189,
      "dy2": 443
    }
  }
}
```

**字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `template_path` | string | 锚点模板图片路径（相对项目根目录） |
| `threshold` | float | matchTemplate 置信度阈值（低于此值视为定位失败），建议 0.7 |
| `scale_min` | float | 最小缩放比例，0.7 |
| `scale_max` | float | 最大缩放比例，1.5 |
| `scale_step` | float | 缩放步长，0.05 |
| `offset.dx1` | int | ROI 左上角相对锚点左上角的 X 偏移（像素，相对窗口） |
| `offset.dy1` | int | ROI 左上角相对锚点左上角的 Y 偏移（像素，相对窗口） |
| `offset.dx2` | int | ROI 右下角相对锚点左上角的 X 偏移（像素，相对窗口） |
| `offset.dy2` | int | ROI 右下角相对锚点左上角的 Y 偏移（像素，相对窗口） |

**未来扩展**（Stash 加入后）:
```json
{
  "inventory": { ... },
  "stash": {
    "template_path": "templates/stash/anchor.png",
    "threshold": 0.7,
    "scale_min": 0.7,
    "scale_max": 1.5,
    "scale_step": 0.05,
    "offset": {
      "dx1": ???,
      "dy1": ???,
      "dx2": ???,
      "dy2": ???
    }
  }
}
```

### 8.2 auto_buy_config.json（业务配置）

**位置**: [auto_buy_config.json](file:///F:/scgit/auto_buy_config.json)

**关键字段**:
```json
{
  "hsv": {                       // HSV 颜色检测配置（识别高亮物品）
    "h_min": 133,
    "h_max": 138,
    "s_min": 131,
    "s_max": 152,
    "v_min": 137,
    "v_max": 246
  },

  "roi": {                       // ← 由 TemplateLocator 写入（相对窗口坐标）
    "LEFT": 447,
    "TOP": 359,
    "RIGHT": 801,
    "BOTTOM": 507
  },

  "cells_map": [                 // ← 待改为动态生成（存放在屏幕坐标）
    [[953, 734], [1017, 799]],   // 格子1
    [[1017, 734], [1081, 799]],  // 格子2
    // ... 共 60 格
  ],

  "detection": {                 // 检测参数
    "threshold": 1,
    "border_thickness": 20
  },

  "delays": {                    // 延迟参数
    "ctrl_hold": 0.1,
    "wait_after_buy": 3.0,
    "scan_interval": 0.5
  },

  "stash_open_pos": [1110, 472], // ← 待改为相对坐标

  "stash_template": [...]        // ← Stash 检测模板（旧格式）
}
```

**注意**: `cells_map` 和 `stash_open_pos` 目前存储的是**屏幕绝对坐标**，这是旧系统遗留的。
重构目标是: 这些坐标都改为**相对窗口坐标**，由 TemplateLocator 在运行时基于锚点 + 网格生成。

### 8.3 config.json（商店格子，保留）

**位置**: [config.json](file:///F:/scgit/config.json)

**用途**: 旧版系统中用于商店格子的坐标配置，保留用于兼容。

---

## 9. 已知问题

### 9.1 cells_map 仍使用屏幕绝对坐标
- **问题**: `auto_buy_config.json` 中 `cells_map` 存储的是屏幕绝对坐标
- **影响**: 游戏窗口移动后，这些坐标失效
- **修复方案**: 基于 Inventory ROI 动态生成格子坐标（相对窗口），或转换存储格式为相对坐标
- **优先级**: 高

### 9.2 stash_open_pos 为硬编码屏幕坐标
- **问题**: `auto_buy_config.json` 中 `stash_open_pos: [1110, 472]` 是屏幕绝对坐标
- **影响**: 窗口移动后点击位置错误
- **修复方案**: 改为相对窗口坐标（如 `[310, 372]` ，以窗口左上角为原点），运行时通过 `locator.to_screen()` 转换
- **优先级**: 高

### 9.3 Stash 锚点尚未实现
- **问题**: Stash Locator 未编码，仓库区域仍依赖旧版 cells_map
- **影响**: 无法自动定位仓库格子
- **修复方案**: 参考 Inventory Locator 实现 `locate_stash()`，用户需提供 Stash 锚点图和 ROI 屏幕坐标
- **优先级**: 高

### 9.4 多尺度匹配对 800x600 固定窗口是过度设计
- **说明**: 因为窗口固定 800x600，锚点的实际尺寸不会变化，理论上只需要 1.0x 匹配即可
- **当前做法**: 保留 0.7x~1.5x 多尺度匹配作为容错，性能开销约 17 次 matchTemplate 调用，可接受
- **优化空间**（可选）: 若确认锚点截图时的窗口尺寸与运行时一致，可简化为单尺度

### 9.5 调试截图可能累积过多文件
- **问题**: `template_debug/` 目录中的调试截图会不断累积
- **建议**: 在 TemplateLocator 中增加简单的文件数限制（如保留最近 10 个），或让用户手动清理

---

## 10. 下一步开发计划

### Phase 1: Inventory 格子坐标自动生成（不修改业务逻辑）
**目标**: 删除 `auto_buy_config.json` 中硬编码的 cells_map，由程序在运行时基于 Inventory ROI 动态生成 60 格坐标。

**步骤**:
1. 从 `template_locator_config.json` 读取 Inventory offset
2. 调用 `locate_inventory()` 获取 roi_rel: `(roi_left, roi_top, roi_right, roi_bottom)`
3. 基于 ROI 自动生成格子坐标:
   ```
   列数: 12，行数: 5
   cell_width = (roi_right - roi_left) / 12
   cell_height = (roi_bottom - roi_top) / 5
   cells_map = []
   for row in range(5):
       for col in range(12):
           x1 = roi_left + col * cell_width
           y1 = roi_top + row * cell_height
           x2 = x1 + cell_width
           y2 = y1 + cell_height
           cells_map.append([[x1, y1], [x2, y2]])  // 相对窗口坐标
   ```
4. 输出调试截图（格子边框 + 编号），验证正确性
5. 修改 `auto_buy_new.py` 中的 `load_stash_cells()`（实际是加载 Inventory cells 的函数），使其调用 TemplateLocator 动态生成，而不是读取配置文件中的 cells_map

**注意**: cells_map 当前存储的是屏幕绝对坐标，生成后需在业务代码中处理：
- 选项 A: 生成的是相对坐标，业务逻辑使用时通过 `locator.to_screen()` 转换
- 选项 B: 生成时直接转为屏幕绝对坐标（简单，但不符合相对坐标原则）
- **推荐选项 A**，但需要修改业务逻辑的坐标转换位置 → 用户说不修改业务逻辑，所以可能需要**在生成时就转成屏幕坐标**，或者**修改业务逻辑的一小部分（仅坐标转换部分）**

### Phase 2: Stash Locator
**目标**: 用与 Inventory Locator 相同的 Anchor + Fixed Offset 方案实现仓库区域定位。

**步骤**:
1. 用户提供:
   - Stash 锚点图 → 保存为 `templates/stash/anchor.png`
   - Stash ROI 屏幕坐标 `(x1, y1)` - `(x2, y2)`
2. 编写 `_calc_stash_offset.py`（参考 `_calc_offset.py`）:
   - 检测游戏窗口
   - 将用户给的屏幕坐标转换为相对坐标
   - matchTemplate 找到 Stash 锚点位置
   - 计算 offset: `dx1 = rel_x1 - anchor_x`, `dy1 = rel_y1 - anchor_y`, `dx2 = rel_x2 - anchor_x`, `dy2 = rel_y2 - anchor_y`
   - 输出配置 JSON
3. 修改 `template_locator_config.json`，添加 `"stash"` 配置节
4. 修改 `template_locator.py`:
   - 添加 `locate_stash(threshold=None)` 方法（参考 `locate_inventory()`）
   - 添加 `_save_debug_shot_stash()` 方法（或改造现有 `_save_debug_shot()` 支持多类型）
   - 调试截图命名: `stash_YYYYMMDD_HHMMSS.png`
5. 验证 Stash ROI
6. 基于 Stash ROI 自动生成仓库格子坐标（12 列 × 5 行 = 60 格，或需根据实际 Stash 布局确认行列数）
7. 输出调试截图（锚点框 + stash_roi 框 + 所有格子边框和编号）
8. 写入 `auto_buy_config.json` 的 `"stash_roi"` 字段（需新增此字段）

### Phase 3: Currency Exchange Locator（不开始）
**用户明确说不要开始**。设计思路与 Inventory/Stash 相同，待前两者稳定后再实施。

### Phase 4: 坐标系统统一迁移
**目标**: 确保 `auto_buy_new.py` 中所有硬编码的屏幕坐标都改为相对坐标 + `locator.to_screen()` 转换。

**检查清单**:
- [ ] `stash_open_pos: [1110, 472]` → 改为相对坐标
- [ ] `cells_map` → 改为动态生成（相对坐标）
- [ ] 业务逻辑中所有 `pyautogui.click(x, y)` 调用 → 确保使用相对坐标 + `locator.to_screen()` 或 `locator.click()`
- [ ] `mss.grab(monitor)` 调用 → 确保使用 `locator.to_screen_monitor()` 转换

---

## 11. 关键坐标系统总结（速查表）

| 概念 | 坐标系统 | 原点 | 转换公式 |
|------|---------|------|---------|
| **屏幕绝对坐标** | 物理屏幕 | 屏幕左上角 (0,0) | 原始值 |
| **相对窗口坐标** | 游戏窗口 | 窗口左上角 (0,0) | `rel = screen - (window.left, window.top)` |
| **锚点位置** | 相对窗口 | 模板在窗口内匹配到的位置 | `(anchor_x, anchor_y)` |
| **ROI 位置** | 相对窗口 | `(anchor_x + dx1, anchor_y + dy1)` - `(anchor_x + dx2, anchor_y + dy2)` |

**WindowLocator API**:
```python
locator.to_screen(rel_x, rel_y)      # → (screen_x, screen_y)
locator.to_relative(screen_x, screen_y)  # → (rel_x, rel_y)
locator.to_screen_monitor(rel_x1, rel_y1, rel_x2, rel_y2)
                                     # → {"top", "left", "width", "height"}
locator.click(rel_x, rel_y)           # 在相对坐标点击
```

**当前项目的坐标约束**:
- 窗口固定尺寸: **800 × 600**
- Inventory ROI（相对窗口，示例）: `(447, 359) - (801, 507)`
- Inventory 格子: **12 列 × 5 行 = 60 格**
- Stash 格子: **待确认（预计也是 12 列 × 5 行 = 60 格）**
