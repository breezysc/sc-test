from window_locator import locator
from template_locator import TemplateLocator

detected = locator.detect("global")
print("游戏窗口:", "已检测" if detected else "未检测 (游戏可能未运行)")

tloc = TemplateLocator(locator, debug=True)
tpl = tloc._load_template("templates/inventory/anchor.png")
if tpl is not None:
    w, h = tpl.shape[1], tpl.shape[0]
    print("锚点模板: {}x{} (宽x高) - OK".format(w, h))
    print("  宽高比: {:.2f}".format(w/h))
    print("  多尺度: 0.7x -> {}x{} 到 1.5x -> {}x{}".format(
        int(w*0.7), int(h*0.7), int(w*1.5), int(h*1.5)))
else:
    print("锚点模板加载失败")

if detected:
    result = tloc.locate_inventory()
    print("定位结果: success={}".format(result["success"]))
    print("  置信度: {:.3f}".format(result["confidence"]))
    print("  信息: {}".format(result["message"]))
    if result["debug_image"]:
        print("  调试图: {}".format(result["debug_image"]))
    if result["roi_rel"]:
        print("  roi (给 auto_buy_config.json): {}".format(result["roi_dict"]))
