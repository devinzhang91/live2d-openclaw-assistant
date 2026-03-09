/**
 * Live2D 嘴形控制补丁 (v20260306-1)
 *
 * 原理：Cubism5 LAppModel.update() 内部已经内置了 lip sync 机制：
 *   if (this._lipsync) {
 *     let rms = this._wavFileHandler.getRms();
 *     model.addParameterValueById(lipSyncId, rms, 0.8);  // 在渲染前写入参数
 *   }
 *   model.update(); // 渲染
 *
 * _lipsync 默认为 true，_lipSyncIds 从 model3.json Groups["LipSync"] 读取。
 * 我们只需替换 _wavFileHandler.getRms() 返回我们的实时音量值即可，
 * 这样就在渲染循环的正确时机写入参数，完全避免时序竞争。
 */

(() => {
if (window.__live2dLipSyncPatchLoaded) {
  console.log('[lip-sync] 补丁已加载，跳过重复注入');
  return;
}
window.__live2dLipSyncPatchLoaded = true;

// 全局实时音量值（由 live2d-controller.js 写入）
window._lipsyncRmsValue = 0;

// 记录当前已处理的模型实例，用于检测模型切换
window._lipSyncLastModel = null;

const getFirstSubdelegate = (appDelegate) => {
  const subdelegates = appDelegate?.subdelegates;
  if (!subdelegates) return null;
  if (typeof subdelegates.at === 'function') return subdelegates.at(0) || null;
  if (Array.isArray(subdelegates)) return subdelegates[0] || null;
  return subdelegates[0] || null;
};

const setupLipSync = () => {
  if (!window.cubism5model) return false;

  const subdelegate = getFirstSubdelegate(window.cubism5model);
  if (!subdelegate) return false;

  let live2dManager = null;
  try {
    live2dManager = subdelegate.getLive2DManager?.();
  } catch (e) {
    return false;
  }
  if (!live2dManager) return false;

  const appModel = live2dManager._models?.at(0);
  if (!appModel) return false;

  // 等待模型完全初始化（_initialized 标志）
  if (!appModel._initialized) {
    return false;
  }

  // 检测模型是否切换（通过比较模型实例）
  if (window._lipSyncLastModel === appModel && window._lipSyncSetupComplete) {
    return true; // 同一个模型，已设置过
  }

  console.log('[lip-sync] 模型已初始化，接管 wavFileHandler...');
  console.log('[lip-sync] _lipsync =', appModel._lipsync);
  console.log('[lip-sync] _lipSyncIds size =', appModel._lipSyncIds?.getSize?.());
  
  // 打印 LipSync 参数 IDs
  try {
    const lipSyncIds = appModel._lipSyncIds;
    if (lipSyncIds && lipSyncIds.getSize) {
      const size = lipSyncIds.getSize();
      console.log('[lip-sync] LipSync 参数数量:', size);
      for (let i = 0; i < size && i < 5; i++) {
        console.log('[lip-sync] LipSync 参数', i, ':', lipSyncIds.at(i));
      }
    }
  } catch (e) {
    console.log('[lip-sync] 读取 LipSync IDs 失败:', e);
  }

  // 核心：替换 wavFileHandler，让 getRms() 返回我们的实时音量
  // Cubism5 内部在每帧 update() 中调用：
  //   rms = this._wavFileHandler.getRms()
  //   model.addParameterValueById(lipSyncId, rms, 0.8)
  // 这是在渲染前的正确时机，完全不存在时序竞争问题。
  appModel._wavFileHandler = {
    update: function(dt) {
      // no-op：我们不需要 wavFileHandler 做任何事
    },
    getRms: function() {
      return window._lipsyncRmsValue || 0;
    }
  };

  // 确保 _lipsync 为 true（默认已是 true，防御性赋值）
  appModel._lipsync = true;

  // 暴露全局写入接口（供 live2d-controller.js 使用）
  window._live2dSetMouthValue = (value) => {
    window._lipsyncRmsValue = Math.max(0, Math.min(1, value/1.5));
  };

  // 记录当前模型实例
  window._lipSyncLastModel = appModel;
  window._lipSyncSetupComplete = true;
  
  console.log('✓ Live2D 嘴形控制补丁已加载（wavFileHandler 已接管）');
  return true;
};

// 监听 live2d:ready 事件
window.addEventListener('live2d:ready', () => {
  console.log('[lip-sync] 收到 live2d:ready 事件');
  // 重置标志，允许重新设置
  window._lipSyncSetupComplete = false;
  window._lipSyncLastModel = null;
  setTimeout(() => setupLipSync(), 500);
});

// 轮询备用
let attempts = 0;
const interval = setInterval(() => {
  if (++attempts > 600) {
    clearInterval(interval);
    console.warn('[lip-sync] 等待模型超时');
    return;
  }
  if (setupLipSync()) clearInterval(interval);
}, 100);

console.log('[lip-sync] 嘴形补丁加载中... (patch v20260306-1)');
})();
