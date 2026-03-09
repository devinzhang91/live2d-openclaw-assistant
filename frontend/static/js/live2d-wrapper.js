/**
 * Live2D 包装器 - 使用 pixi-live2d-display + 本地 Shizuku 模型
 */
class Live2DWrapper {
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        this.options = {
            // 使用本地 Shizuku 模型
            modelUrl: '/static/shizuku.model3.json',
            ...options
        };
        this.loaded = false;
        this.app = null;
        this.viewer = null;
    }

    async init() {
        try {
            // 清空容器
            this.container.innerHTML = '';

            // 等待依赖库加载
            await this.waitForDependencies();

            // 创建 PIXI 应用
            this.app = new PIXI.Application({
                view: this.createCanvas(),
                width: this.container.clientWidth || 400,
                height: this.container.clientHeight || 500,
                backgroundAlpha: 0,
                resizeTo: this.container
            });

            this.container.appendChild(this.app.view);

            // 创建 Live2D 查看器
            this.viewer = new PIXI.live2d.Live2DViewer();

            // 加载模型
            const model = await PIXI.live2d.Live2DModel.from(this.options.modelUrl);
            this.viewer.addModel(model);

            // 将查看器添加到舞台
            this.app.stage.addChild(this.viewer);

            // 调整模型大小和位置
            model.scale.set(0.4);
            model.y = this.app.view.height - 300;

            this.loaded = true;
            console.log('Live2D 初始化成功');

        } catch (error) {
            console.warn('Live2D 初始化失败，使用占位符:', error);
            this.createSimplePlaceholder();
            this.loaded = true;
        }
    }

    createCanvas() {
        const canvas = document.createElement('canvas');
        canvas.style.width = '100%';
        canvas.style.height = '100%';
        return canvas;
;
    }

    async waitForDependencies() {
        // 等待 PIXI 和 PIXI.live2d 加载完成
        const waitFor = (condition, timeout = 10000) => {
            return new Promise((resolve, reject) => {
                const start = Date.now();
                const check = () => {
                    if (condition()) {
                        resolve();
                    } else if (Date.now() - start > timeout) {
                        reject(new Error('依赖库加载超时'));
                    } else {
                        setTimeout(check, 100);
                    }
                };
                check();
            });
        };

        await waitFor(() => window.PIXI !== undefined, 10000);
        await waitFor(() => window.PIXI && window.PIXI.live2d, 10000);
        console.log('Live2D 依赖库加载完成');
    }

    createSimplePlaceholder() {
        this.container.innerHTML = '';
        const placeholder = document.createElement('div');
        placeholder.style.cssText = `
            width: 100%;
            height: 100%;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            text-align: center;
        `;

        const avatar = document.createElement('div');
        avatar.innerHTML = '👾';
        avatar.style.cssText = 'font-size: 100px; margin-bottom: 20px;';

        const title = document.createElement('div');
        title.textContent = 'AI 助手';
        title.style.cssText = 'font-size: 28px; font-weight: bold;';

        placeholder.appendChild(avatar);
        placeholder.appendChild(title);
        this.container.appendChild(placeholder);
    }

    // 表情控制
    setExpression(expression) {
        console.log('设置表情:', expression);
        if (this.viewer && this.viewer.models.length > 0) {
            const model = this.viewer.models[0];
            try {
                // 根据表达式播放不同的动画
                // 这需要模型有对应的表情定义
                console.log('模型可用表情:', model.internalModel.motionManager.getMotionCount());
            } catch (e) {
                console.warn('设置表情失败:', e);
            }
        }
    }

    // 动画控制
    playAnimation(animationName) {
        console.log('播放动画:', animationName);
    }

    // 销毁
    destroy() {
        if (this.app) {
            this.app.destroy(true, { children: true });
            this.app = null;
        }
        this.viewer = null;
        this.loaded = false;
    }
}
