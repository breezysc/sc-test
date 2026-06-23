# AI_CONTINUATION_PROMPT.md

> 让任何新的 AI 聊天窗口读取后，能够立刻接手 Path of Exile 2 自动购物脚本项目。

---

## 项目背景

Path of Exile 2 自动购物脚本项目。项目正在进行**坐标系统重构**：
- 从「硬编码的屏幕绝对坐标」改为「游戏窗口相对坐标 + 锚点自动定位」
- 消除 Debug Tool 手动框选流程
- 游戏窗口固定为 **800×600**，不需要支持任意分辨率和缩放

**项目路径**: `F:\scgit\`

---

## 当前进度

**完成度约 40%**：WindowLocator + Inventory 锚点定位已验证成功。

### 已完成模块

| 模块 | 文件 | 状态 |
|------|------|------|
| WindowLocator（窗口检测 + 坐标转换） | [window_locator.py](file:///F:/scgit/window_locator.py) | ✅ 完成 |
| TemplateLocator（Inventory 锚点定位） | [template_locator.py](file:///F:/scgit/template_locator.py) | ✅ 完成 |
| Inventory offset 计算脚本 | [_calc_offset.py](file:///F:/scgit/_calc_offset.py) | ✅ 完成 |
| Inventory 锚点图 | [templates/inventory/anchor.png](file:///F:/scgit/templates/inventory/anchor.png) | ✅ 完成 |
| 锚点配置文件 | [template_locator_config.json](file:///F:/scgit/template_locator_config.json) | ✅ 完成 |
| Inventory ROI 自动写入配置 | `write_roi_to_business_config()` 方法 | ✅ 完成 |

### 未完成模块

| 模块 | 需要做什么 | 优先级 |
|------|-----------|---------|
| **Stash Locator** | 用相同 Anchor + Fixed Offset 方案实现仓库定位 | 🔴 高 |
| **Stash 锚点图** | 需用户截取 Stash 标题栏 → 保存为 `templates/stash/anchor.png` | 🔴 高 |
| **Inventory 格子坐标自动生成** | 基于 Inventory ROI 动态生成 12×5=60 格坐标，替代配置文件中的 cells_map | 🔴 高 |
| **Stash 格子坐标自动生成** | 基于 Stash ROI 动态生成仓库格子坐标 | 🔴 高 |
| **cells_map 坐标迁移** | cells_map 当前存储的是屏幕绝对坐标，需改为相对坐标 | 🟡 中 |
| **stash_open_pos 坐标迁移** | `[1110, 472]` 是屏幕绝对坐标，需改为相对坐标 | 🟡 中 |
| **Currency Exchange Locator** | 用户明确说**不要开始** | ⚪ 待定 |

---

## 技术约束

### 硬性约束
1. **固定 800×600 窗口**：游戏窗口必须设置为 800×600
2. **不支持窗口缩放**：不需要 DPI 缩放、分辨率变化适配
3. **不修改业务逻辑**：`auto_buy_new.py` 中的购买/存仓核心逻辑不动
4. **Anchor + Fixed Offset 方案**：所有 UI 区域定位必须使用此方案
5. **所有坐标基于游戏窗口相对坐标**：以窗口左上角 (0,0) 为原点
6. **offset 是固定像素值**：不会随窗口位置变化（锚点位置是相对窗口定位的）

### 技术栈
- **语言**: Python 3.x（Windows）
- **图像处理**: OpenCV (`cv2`) + NumPy
- **屏幕截图**: `mss` 库
- **自动化**: `pyautogui`
- **窗口检测**: Windows API (`ctypes.windll.user32`)
- **匹配算法**: `cv2.matchTemplate()` + `cv2.TM_CCOEFF_NORMED`
- **多尺度匹配**: 模板在 `[0.7, 1.5]` 倍之间缩放，步长 0.05

---

## 代码架构

### 核心模块依赖关系

```
auto_buy_new.py (业务逻辑，不修改)
   │
   ├── 读取: auto_buy_config.json
   │       (roi, cells_map, stash_open_pos, detection, delays...)
   │
   └── 未来调用: TemplateLocator
                 │
                 └── 依赖: WindowLocator
                         │
                         ├── detect() → 检测游戏窗口
                         ├── grab_window() → 截取窗口截图
                         ├── to_screen(rel_x, rel_y) → 坐标转换
                         ├── to_relative(screen_x, screen_y)
                         ├── click(rel_x, rel_y) → 相对坐标点击
                         └── .window → {left, top, width, height...}
```

### 核心 API

**WindowLocator**（单例，`from window_locator import locator`）:
```python
locator.detect("global")              # 或 "china"
locator.window                         # → {"left","top","width","height"...}
locator.detected                       # → bool
locator.to_screen(100, 200)            # → (screen_x, screen_y)
locator.to_relative(screen_x, screen_y) # → (rel_x, rel_y)
locator.grab_window()                  # → np.ndarray BGR image
locator.click(rel_x, rel_y)            # 在相对坐标点击
```

**TemplateLocator**:
```python
tloc = TemplateLocator(locator, debug=True)
result = tloc.locate_inventory()
# result = {"success", "anchor_rel", "roi_rel", "roi_dict", "confidence"...}
tloc.write_roi_to_business_config()    # 写入 auto_buy_config.json 的 roi 字段
```

### 锚点方案原理（必须理解）

```
┌─────────────────────────────────────────┐
│ 游戏窗口 (0,0)─────────► (800,0)       │
│     │                                  │
│     │  [ANCHOR] ← matchTemplate 找到   │
│     │      │                            │
│     │      │ offset (dx1, dy1)           │
│     │      └───────────► [ROI]           │
│     │                    背包格子区域    │
│     ▼                                   │
│  (0,600)─────────────► (800,600)        │
└─────────────────────────────────────────┘

roi_left   = anchor_x + dx1   (相对窗口)
roi_top    = anchor_y + dy1
roi_right  = anchor_x + dx2
roi_bottom = anchor_y + dy2
```

### 配置文件格式

**template_locator_config.json**（锚点配置）:
```json
{
  "inventory": {
    "template_path": "templates/inventory/anchor.png",
    "threshold": 0.7,
    "scale_min": 0.7,
    "scale_max": 1.5,
    "scale_step": 0.05,
    "offset": {"dx1": -165, "dy1": 295, "dx2": 189, "dy2": 443}
  }
}
```
- `offset` 的值由 `_calc_offset.py` 脚本根据用户提供的屏幕坐标计算得出

**auto_buy_config.json**（业务配置）:
- `roi`: Inventory ROI 区域（相对窗口坐标），由 TemplateLocator 写入
- `cells_map`: 格子坐标数组 `[[[x1,y1],[x2,y2]], ...]`，**当前是屏幕绝对坐标，需迁移**
- `stash_open_pos`: `[1110, 472]`，**屏幕绝对坐标，需迁移**
- `hsv`: HSV 颜色检测参数
- `detection`, `delays`: 检测和延迟参数

---

## 当前待办事项

### 🔴 高优先级（必须完成）

#### 1. Stash Locator 实现
**文件**: 修改 `template_locator.py`，新增 `locate_stash()` 方法

**前置依赖**:
- 用户需提供: Stash 锚点截图（保存为 `templates/stash/anchor.png`）
- 用户需提供: Stash ROI 屏幕坐标 `(x1, y1) - (x2, y2)`

**步骤**:
1. 参考 `_calc_offset.py`，写一个 `_calc_stash_offset.py`：
   - 检测游戏窗口
   - 将用户给的 Stash ROI 屏幕坐标转换为相对坐标
   - matchTemplate 找到 Stash 锚点位置
   - 计算 offset: `dx1 = rel_x1 - anchor_x`, `dy1 = rel_y1 - anchor_y`, `dx2 = rel_x2 - anchor_x`, `dy2 = rel_y2 - anchor_y`
   - 输出 offset 配置
2. 向 `template_locator_config.json` 写入 `"stash"` 配置节
3. 在 `template_locator.py` 中新增 `locate_stash(threshold=None)` 方法，结构与 `locate_inventory()` 一致
4. 调试截图命名: `stash_YYYYMMDD_HHMMSS.png`，包含: 锚点框 + stash_roi 框 + top-3 候选
5. 验证: `python template_locator.py --stash-only`（需新增命令行选项，或单独写测试脚本）

#### 2. Inventory 格子坐标自动生成
**目标**: 基于 Inventory ROI 动态生成 12×5=60 格坐标，替代 `auto_buy_config.json` 中的 cells_map

**Inventory ROI（相对窗口，示例）**: `(447, 359) - (801, 507)`

**格子计算**:
```
cell_width = (801 - 447) / 12 = 29.5 像素
cell_height = (507 - 359) / 5 = 29.6 像素

for row in 0..4:
    for col in 0..11:
        x1 = 447 + col * 29.5
        y1 = 359 + row * 29.6
        x2 = x1 + 29.5
        y2 = y1 + 29.6
        cells_map.append([[x1, y1], [x2, y2]])
```

**注意事项**:
- 生成的是**相对窗口坐标**，但 `auto_buy_new.py` 中 cells_map 当前是**屏幕绝对坐标**
- 用户说「不修改业务逻辑」，所以有两个选择：
  - **选项 A**（推荐）: 生成时直接转成屏幕绝对坐标（简单，最小侵入）
  - **选项 B**: 小幅修改业务逻辑的坐标转换部分（使用 `locator.to_screen()`）
- 建议先**输出调试截图**验证格子坐标的正确性，再决定是否替换 cells_map

**输出要求**: 调试截图包含 `stash_roi` 框 + 所有格子边框 + 格子编号

#### 3. Stash 格子坐标自动生成
**前提**: Stash Locator 完成并验证通过

**步骤**:
1. 确认 Stash 的行列数（查看游戏界面，应该也是 12 列 × 5 行 = 60 格）
2. 基于 Stash ROI 用同样的均分公式生成格子坐标
3. 输出调试截图（stash_roi 框 + 格子边框 + 编号）

### 🟡 中优先级

#### 4. cells_map 坐标系统迁移
- 目标: `auto_buy_config.json` 中 cells_map 从屏幕绝对坐标改为相对坐标，或完全删除改为动态生成
- 若改为动态生成，需确认 `auto_buy_new.py` 中 `load_stash_cells()` 的调用位置，改为调用 TemplateLocator

#### 5. stash_open_pos 坐标迁移
- `stash_open_pos: [1110, 472]` 是屏幕绝对坐标
- 改为相对坐标: `[rel_x, rel_y]`，运行时用 `locator.to_screen(rel_x, rel_y)` 转换
- 或改为通过 Stash 锚点位置计算（仓库打开按钮的位置相对于 Stash 锚点的固定偏移）

### ⚪ 待定

- **Currency Exchange Locator**: 用户明确说「不要开始」，待 Inventory 和 Stash 稳定后再考虑

---

## 关键文件清单

| 文件 | 作用 | 是否需要修改 |
|------|------|-------------|
| `window_locator.py` | 窗口定位和坐标转换 | 不需要（已完成） |
| `template_locator.py` | 锚点定位主模块 | ✅ 需要（新增 Stash 方法） |
| `template_locator_config.json` | 锚点配置 | ✅ 需要（新增 stash 配置节） |
| `_calc_offset.py` | Inventory offset 计算脚本 | 不需要 |
| `_test_tloc.py` | TemplateLocator 测试脚本 | 可能需要（新增 Stash 测试） |
| `templates/inventory/anchor.png` | Inventory 锚点图 | 不需要 |
| `templates/stash/anchor.png` | Stash 锚点图 | ❌ 待截取 |
| `auto_buy_config.json` | 业务配置 | 只读写入（TemplateLocator 写 roi 字段） |
| `auto_buy_new.py` | 业务主程序 | ❌ 不修改（或仅最小坐标转换适配） |

---

## 调试与验证流程

1. **WindowLocator 验证**:
   ```bash
   # 确保游戏已运行，检测窗口
   python -c "from window_locator import locator; locator.detect('global'); print(locator.window)"
   ```

2. **Inventory Locator 验证**:
   ```bash
   python template_locator.py --server global
   # 查看 template_debug/ 目录下的调试截图
   ```

3. **Stash Locator 验证**（待实现后）:
   ```bash
   # 需新增 --stash 选项或单独测试脚本
   python -c "from window_locator import locator; from template_locator import TemplateLocator; locator.detect('global'); t = TemplateLocator(locator); print(t.locate_stash())"
   ```

4. **格子坐标验证**:
   - 检查调试截图中格子是否与游戏界面中的格子对齐
   - 注意格子边框应与游戏格子的视觉边界重合

---

## 已知问题速查

1. **cells_map 仍存储屏幕绝对坐标** — 需改为相对坐标或动态生成
2. **stash_open_pos 是硬编码屏幕坐标** — 需改为相对坐标
3. **Stash Locator 未实现** — 高优先级待做
4. **多尺度匹配对固定窗口是过度设计** — 可接受，保留为容错

---

**请先阅读项目代码再开始修改，不要直接编码。**

建议阅读顺序:
1. `window_locator.py` — 理解坐标系统和窗口检测
2. `template_locator.py` — 理解 Anchor + Fixed Offset 方案
3. `_calc_offset.py` — 理解如何从用户提供的屏幕坐标计算 offset
4. `template_locator_config.json` — 理解配置格式
5. `auto_buy_config.json` — 理解业务配置的结构
6. `auto_buy_new.py` — 快速浏览，理解业务逻辑如何使用坐标
