/**
 * Live2D 错误修复补丁
 * 使用全局错误处理来抑制模型加载前的 hitTest 错误
 */

(() => {
if (window.__live2dErrorFilterPatchLoaded) {
  console.log('Live2D 错误过滤补丁已加载，跳过重复注入');
  return;
}
window.__live2dErrorFilterPatchLoaded = true;

const getFirstSubdelegate = (appDelegate) => {
  const subdelegates = appDelegate?.subdelegates;
  if (!subdelegates) return null;

  if (typeof subdelegates.at === 'function') {
    return subdelegates.at(0) || null;
  }

  if (Array.isArray(subdelegates)) {
    return subdelegates[0] || null;
  }

  return subdelegates[0] || null;
};

// 保存原始的错误处理函数
const originalConsoleError = console.error;
const originalConsoleWarn = console.warn;

// 过滤特定错误
const filterLive2DErrors = (...args) => {
  const message = args[0];

  // 检查是否是 hitTest 相关的错误
  if (typeof message === 'string') {
    if (message.includes('hitTest') ||
        message.includes('Cannot read properties of null') ||
        message.includes('getDrawableIndex')) {
      return; // 抑制这些错误
    }
  } else if (message instanceof Error) {
    if (message.message?.includes('hitTest') ||
        message.message?.includes('Cannot read properties of null') ||
        message.message?.includes('getDrawableIndex')) {
      return; // 抑制这些错误
    }
  }

  // 其他正常输出
  originalConsoleError.apply(console, args);
};

const filterLive2DWarns = (...args) => {
  const message = args[0];

  // 检查是否是 hitTest 相关的警告
  if (typeof message === 'string') {
    if (message.includes('hitTest') ||
        message.includes('Cannot read properties of null') ||
        message.includes('getDrawableIndex')) {
      return; // 抑制这些警告
    }
  }

  // 其他正常输出
  originalConsoleWarn.apply(console, args);
};

// 应用过滤
console.error = filterLive2DErrors;
console.warn = filterLive2DWarns;

// 等待模型加载完成后，恢复正常的错误输出
const restoreConsole = () => {
  if (!window.cubism5model) {
    return false;
  }

  const appDelegate = window.cubism5model;
  const subdelegate = getFirstSubdelegate(appDelegate);
  if (!subdelegate) {
    return false;
  }
  let live2dManager = null;
  try {
    live2dManager = subdelegate.getLive2DManager?.();
  } catch (error) {
    return false;
  }

  if (!live2dManager) {
    return false;
  }

  const model = live2dManager._models?.at(0);
  if (!model || !model.hitTest) {
    return false;
  }

  // 模型已加载，恢复正常的错误输出
  console.error = originalConsoleError;
  console.warn = originalConsoleWarn;

  console.log('Live2D 模型加载完成，已恢复正常错误输出');
  return true;
};

// 轮询检查
let restoreAttempts = 0;
const restoreInterval = setInterval(() => {
  restoreAttempts++;
  if (restoreAttempts > 200) {
    clearInterval(restoreInterval);
    return;
  }

  if (restoreConsole()) {
    clearInterval(restoreInterval);
  }
}, 100);

console.log('Live2D 错误过滤补丁已加载 (patch v20260301-3)');
})();
