/*!
 * Live2D Widget - 自定义版本
 * https://github.com/stevenjoezhang/live2d-widget
 */

// 路径配置
const live2d_path = '/static/';

// 目标容器
const containerId = 'live2d-container';

// 加载外部资源
function loadExternalResource(url, type) {
  return new Promise((resolve, reject) => {
    let tag;
    if (type === 'css') {
      tag = document.createElement('link');
      tag.rel = 'stylesheet';
      tag.href = url;
    }
    else if (type === 'js') {
      tag = document.createElement('script');
      tag.type = 'module';
      tag.src = url;
    }
    if (tag) {
      tag.onload = () => resolve(url);
      tag.onerror = () => reject(url);
      document.head.appendChild(tag);
    }
  });
}

// 初始化 Live2D
(async () => {
  try {
    // 模型名称 → 索引映射（供外部调用）
    window.live2dModelIdMap = { 'Hiyori': 0, 'Qianqian': 1, 'Miku': 2 };

    // 存储当前模型名称（供外部使用）
    window.live2dCurrentModel = localStorage.getItem('live2d_model') || 'Hiyori';

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

    // 检查容器是否存在
    const container = document.getElementById(containerId);
    if (!container) {
      console.error('Live2D 容器不存在:', containerId);
      return;
    }

    // 避免图片资源跨域问题
    const OriginalImage = window.Image;
    window.Image = function(...args) {
      const img = new OriginalImage(...args);
      img.crossOrigin = "anonymous";
      return img;
    };
    window.Image.prototype = OriginalImage.prototype;

    // 加载 waifu.css 和 waifu-tips.js
    await Promise.all([
      loadExternalResource(live2d_path + 'waifu.css', 'css'),
      loadExternalResource(live2d_path + 'waifu-tips.js', 'js')
    ]);

    // 捕获 WaifuQuore widget 实例，供外部调用 loadModel()
    const _origInitWidget = window.initWidget;
    window.initWidget = function(cfg) {
      const p = _origInitWidget.call(window.initWidget, cfg);
      if (p && typeof p.then === 'function') {
        p.then(instance => {
          window._waifuWidget = instance;
          console.log('[Live2D] widget 实例已捕获');
        }).catch(() => {});
      }
      return p;
    };

    // 从 localStorage 获取用户选择的模型（默认 Hiyori）
    const savedModel = localStorage.getItem('live2d_model') || 'Hiyori';
    const modelIdMap = { 'Hiyori': 0, 'Qianqian': 1, 'Miku': 2 };
    const modelId = modelIdMap[savedModel] ?? 0;
    console.log('[Live2D] 加载模型:', savedModel, '索引:', modelId);

    // 禁用鼠标跟随：在初始化前就开始阻止
    console.log('[Live2D] 禁用鼠标跟随，使用自动动画系统');

    // 初始化配置
    initWidget({
      waifuPath: live2d_path + 'waifu-tips.json?v=3',
      cubism2Path: live2d_path + 'live2d.min.js',
      cubism5Path: 'https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js',
      tools: ['switch-model', 'photo'],
      logLevel: 'warn',
      drag: false,
      modelId: modelId,
    });

    // 模型加载后移除所有鼠标监听
    setTimeout(() => {
      // 尝试禁用 Cubism5 的鼠标跟随
      if (window.cubism5model) {
        const delegate = window.cubism5model;
        if (delegate) {
          // 标记为已初始化，防止再次初始化事件监听
          delegate._initializedEventListeners = true;
          
          // 如果已经有监听器，移除它们
          if (delegate.mouseMoveEventListener) {
            document.removeEventListener('mousemove', delegate.mouseMoveEventListener);
            delegate.mouseMoveEventListener = null;
            console.log('[Live2D] 已移除 mousemove 监听器');
          }
          if (delegate.releaseEventListener) {
            try {
              delegate.releaseEventListener();
            } catch(e) {}
          }
        }
      }
    }, 2000);

    // 等待 waifu 元素创建后，将其移动到我们的容器
    const moveWaifuToContainer = () => {
      const waifu = document.getElementById('waifu');
      const waifuToggle = document.getElementById('waifu-toggle');
      const waifuTool = document.getElementById('waifu-tool');

      if (waifu && !container.contains(waifu)) {
        // 设置宽度和高度以填满容器
        waifu.style.width = '100%';
        waifu.style.height = '100%';
        waifu.style.position = 'absolute';
        waifu.style.top = '0';
        waifu.style.left = '0';
        waifu.style.bottom = 'auto';
        waifu.style.transform = 'none';

        // 移动到容器
        container.appendChild(waifu);

        // 调整 waifu-canvas 容器大小
        const waifuCanvas = waifu.querySelector('#waifu-canvas');
        if (waifuCanvas) {
          waifuCanvas.style.width = '100%';
          waifuCanvas.style.height = '100%';
          waifuCanvas.style.position = 'relative';
        }

        // 调整 live2d 元素大小（覆盖 waifu.css 的默认 300px）
        const live2dEl = waifu.querySelector('#live2d');
        if (live2dEl) {
          live2dEl.style.width = '100%';
          live2dEl.style.height = '100%';
          live2dEl.style.display = 'block';
        }

        // 调整 canvas 大小
        const canvas = waifu.querySelector('canvas');
        if (canvas) {
          canvas.style.maxWidth = '100%';
          canvas.style.maxHeight = '100%';
          canvas.style.width = '100%';
          canvas.style.height = '100%';
        }

        console.log('waifu 元素已移动到容器');
      }

      // 隐藏切换按钮和工具栏
      if (waifuToggle) {
        waifuToggle.style.display = 'none';
      }
      if (waifuTool) {
        waifuTool.style.display = 'none';
      }
    };

    // 轮询等待 waifu 元素创建
    const checkInterval = setInterval(() => {
      const waifu = document.getElementById('waifu');
      if (waifu) {
        clearInterval(checkInterval);
        moveWaifuToContainer();
      }
    }, 100);

    // 修复错误：等待模型加载完成后再初始化事件监听器
    const waitForModelAndFix = () => {
      if (!window.cubism5model) {
        return false;
      }

      const appDelegate = window.cubism5model;

      // �已经初始化完成，不需要再补丁
      if (appDelegate._initializedEventListeners) {
        return true;
      }

      // 检查是否有 subdelegates
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

      // 检查模型是否已加载
      const model = live2dManager._models?.at(0);
      if (!model) {
        return false;
      }

      // 标记为已初始化
      appDelegate._initializedEventListeners = true;

      // 注：禁用鼠标跟随，使用自动动画系统替代
      // 如果需要恢复鼠标跟随，取消下面的注释
      // if (!appDelegate.mouseMoveEventListener) {
      //   console.log('初始化 Live2D 事件监听器...');
      //   appDelegate.initializeEventListener();
      // }
      console.log('[Live2D] 鼠标跟随已禁用，使用自动动画系统');

      console.log('Live2D 模型加载完成，事件监听器已初始化');

      // 触发自定义事件，通知其他脚本 Live2D 已准备就绪
      window.dispatchEvent(new CustomEvent('live2d:ready'));

      return true;
    };

    // 等待模型加载
    const modelCheckInterval = setInterval(() => {
      if (waitForModelAndFix()) {
        clearInterval(modelCheckInterval);
      }
    }, 100);

  } catch (error) {
    console.error('Live2D 加载失败:', error);
  }
})();

console.log(`\n%cLive2D%cWidget%c\n`, 'padding: 8px; background: #cd3e45; font-weight: bold; font-size: large; color: white;', 'padding: 8px; background: #ff5450; font-size: large; color: #eee;', '');
