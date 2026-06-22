"""验证 Stash 格子坐标生成是否与 auto_buy_config.json 中的 cells_map 匹配"""
import json
from window_locator import locator
from template_locator import TemplateLocator

# 1. 检测窗口
locator.detect('china')
print(f"[窗口] {locator.window['width']}x{locator.window['height']} @ ({locator.window['left']}, {locator.window['top']})")

# 2. 生成格子
tloc = TemplateLocator(locator)
r = tloc.generate_stash_cells()
print(f"\n[生成] ROI (相对窗口): {r['roi_rel']}")
print(f"[生成] 每格尺寸: {r['cell_size']}")
print(f"[生成] 格子数量: {len(r['cells_map'])}")

# 3. 读取配置中的 cells_map
with open('auto_buy_config.json', 'r', encoding='utf-8') as f:
    cfg = json.load(f)
orig = cfg['cells_map']
gen = r['cells_screen_map']

# 4. 对比验证
print("\n=== 对比 auto_buy_config.json 中的 cells_map ===")

checks = [0, 5, 11, 12, 30, 59]
for idx in checks:
    print(f"\n--- 第{idx+1}格 ---")
    print(f"  原配置: {orig[idx]}")
    print(f"  生成:   {gen[idx]}")
    match = (orig[idx] == gen[idx])
    print(f"  匹配: {match}")
    if not match:
        # 显示差异
        dx1 = gen[idx][0][0] - orig[idx][0][0]
        dy1 = gen[idx][0][1] - orig[idx][0][1]
        dx2 = gen[idx][1][0] - orig[idx][1][0]
        dy2 = gen[idx][1][1] - orig[idx][1][1]
        print(f"  差异: dx1={dx1}, dy1={dy1}, dx2={dx2}, dy2={dy2}")

# 统计
matches = 0
for i in range(60):
    if orig[i] == gen[i]:
        matches += 1
print(f"\n=== 总匹配: {matches}/60 格 ===")

# 调试图片
if r['debug_image']:
    print(f"[调试截图] {r['debug_image']}")
    print(f"[锚点调试] template_debug\\stash_cells_*.png")
