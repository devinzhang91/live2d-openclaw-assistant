/**
 * Live2D 错误修复补丁
 * 修复 waifu-tips.js 在模型加载前触发鼠标事件导致的错误
 * 通过重写 lapplive2dmanager.onTap 方法来添加模型检查
 */

// 等待 Live2D widget 加载完成
const fixWidgetErrors = () => {
  if (!window.cubism5model) {
    return false;
  }

  const appDelegate = window.cubism5model;

  // 检查是否有 subdelegates
  if (!appDelegate.subdelegates || appDelegate.subdelegates.length === 0) {
    return false;
  }

  const subdelegate = appDelegate.subdelegates[0];
  const live2dManager = subdelegate.getLive2DManager?.();

  if (!live2dManager) {
    return false;
  }

  // 获取模型
  const model = live2dManager._models?.at(0);
  if (!model) {
    return false;
  }

  // 检查模型是否真的加载完成
  if (!model.hitTest) {
    return false;
  }

  // 如果已经修补过，就不重复
  if (appDelegate._fixedErrorPatch) {
    return true;
  }

  // 查找 lapplive2dmanager 对象
  // 它应该在某个地方被存储，我们可以通过 subdelegate 访问
  if (subdelegate._live2dManager) {
    const manager = subdelegate._live2dManager;

    // 保存原始 onTap 和 onDrag 方法
    const originalOnTap = manager.onTap.bind(manager);
    const originalOnDrag = manager.onDrag.bind(manager);

    // 重写 onTap 方法，添加模型检查
    manager.onTap = function(x, y) {
      try {
        const model = this._models?.at(0);
        if (model && model.hitTest) {
          originalOnTap(x, y);
        }
      } catch (e) {
        // 忽略错误
      }
    };

    // 重写 onDrag 方法，添加模型检查
    manager.onDrag = function(x, y) {
      try {
        const model = this._models?.at(0);
        if (model) {
          originalOnDrag(x, y);
        }
      } catch (e) {
        // 忽略错误
      }
    };
  }

  // 标记为已修补
  appDelegate._fixedErrorPatch = true;

  console.log('Live2D 错误修复补丁已加载');
  return true;
};

// 轮询尝试设置
let fixAttempts = 0;
const fixInterval = setInterval(() => {
  fixAttempts++;
  if (fixAttempts > 200) {
    clearInterval(fixInterval);
    console.log('Live2D 错误修复补丁超时（未找到模型）');
    return;
  }

  if (fixWidgetErrors()) {
    clearInterval(fixInterval);
  }
}, 100);

console.log('Live2D 错误修复补丁加载中...');
