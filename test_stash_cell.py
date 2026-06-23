import cv2
import numpy as np
import mss
import json

# 加载空格子模板
empty_cell_template = cv2.imread("cc.png")
print(f"空格子模板: {'已加载' if empty_cell_template is not None else '未加载'}, 大小: {empty_cell_template.shape if empty_cell_template is not None else 'N/A'}")

# 用户提供的坐标
first_center_x = 521
first_center_y = 763
last_center_x = 844
last_center_y = 879

# 格子布局
cols = 12
rows = 5
cell_width = 62
cell_height = 62

# 计算格子间距
col_spacing = (last_center_x - first_center_x) / (cols - 1)
row_spacing = (last_center_y - first_center_y) / (rows - 1)

print(f"\n格子布局: {cols}列 × {rows}行")
print(f"列间距: {col_spacing:.2f}, 行间距: {row_spacing:.2f}")
print(f"格子大小: {cell_width}×{cell_height}")

# 生成所有格子并输出第一个
cells = []
for row in range(rows):
    for col in range(cols):
        center_x = int(first_center_x + col * col_spacing)
        center_y = int(first_center_y + row * row_spacing)
        x1 = center_x - cell_width // 2
        y1 = center_y - cell_height // 2
        x2 = center_x + cell_width // 2
        y2 = center_y + cell_height // 2
        cells.append({
            "index": len(cells) + 1,
            "region": [x1, y1, x2, y2],
            "center": (center_x, center_y)
        })

print(f"\n第一个格子:")
print(f"  区域: {cells[0]['region']}")
print(f"  中心: {cells[0]['center']}")

print(f"\n最后一个格子:")
print(f"  区域: {cells[-1]['region']}")
print(f"  中心: {cells[-1]['center']}")

# 截图第一个格子区域并计算置信度
if empty_cell_template is not None:
    x1, y1, x2, y2 = cells[0]['region']
    print(f"\n截图第一个格子区域: ({x1}, {y1}) - ({x2}, {y2})")
    
    with mss.mss() as sct:
        monitor = {
            "top": y1,
            "left": x1,
            "width": x2 - x1,
            "height": y2 - y1
        }
        screenshot = sct.grab(monitor)
        cell_img = np.array(screenshot)[:, :, :3]
    
    # 保存截图
    cv2.imwrite("test_first_cell.png", cell_img)
    print(f"截图已保存: test_first_cell.png (大小: {cell_img.shape[1]}×{cell_img.shape[0]})")
    
    # 显示模板和截图对比
    cv2.imwrite("test_template.png", empty_cell_template)
    print(f"模板已保存: test_template.png (大小: {empty_cell_template.shape[1]}×{empty_cell_template.shape[0]})")
    
    # 计算置信度
    def _get_template_confidence(search_img, template):
        if search_img is None or template is None:
            return 0.0
        search_gray = cv2.cvtColor(search_img, cv2.COLOR_BGR2GRAY)
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        result = cv2.matchTemplate(search_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        return float(max_val)
    
    confidence = _get_template_confidence(cell_img, empty_cell_template)
    print(f"\n第一个格子与空格子模板的匹配度: {confidence:.4f}")
    print(f"判断: {'空格子' if confidence > 0.5 else '有物品'}")
    
    # 检查亮度
    gray = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY)
    avg_brightness = np.mean(gray)
    brightness_std = np.std(gray)
    print(f"平均亮度: {avg_brightness:.2f}")
    print(f"亮度方差: {brightness_std:.2f}")

else:
    print("\n无法测试：空格子模板未加载")

# 输出所有格子信息（可选）
print("\n所有格子中心坐标:")
for cell in cells:
    print(f"格子{cell['index']}: {cell['center']}")
