// Live2D 控制器 - 处理模型交互、表情/动作播放

class Live2DController {
    constructor() {
        this.ready = false;
        this.model = null;
        this.canvas = null;
        this.appDelegate = null;
        this.cubism2model = null;
        
        // 当前表情/动作状态
        this._currentExpression = '';
        this._expressionTimer = null;
        
        // 鼠标跟随状态
        this._mouseFollowEnabled = true;
        // 音频 / 嘴型同步状态
        this.audioContext = null;
        this._nextScheduledTime = 0;
        this._activeAudioChains = [];
        this._mouthLoopRunning = false;
        this.isSpeaking = false;
    }

    async init() {
        await this.waitForLive2D();
        this.ready = true;
        console.log('[Live2D Controller] 初始化完成，模型类型:', this._isQianqianModel() ? 'Qianqian(表情)' : 'Hiyori(动作)');
        
        // 检查是否开启鼠标跟随
        const mouseFollowEnabled = localStorage.getItem('live2d_mouse_follow') === 'true';
        this._mouseFollowEnabled = mouseFollowEnabled;
        
        if (mouseFollowEnabled) {
            console.log('[Live2D Controller] 鼠标跟随已开启');
            // 启用SDK的鼠标跟随
            if (window.cubism5model) {
                const delegate = window.cubism5model;
                if (delegate && typeof delegate.initializeEventListener === 'function') {
                    delegate._initializedEventListeners = false;
                    delegate.initializeEventListener();
                }
            }
        } else {
            console.log('[Live2D Controller] 鼠标跟随已关闭');
            this._disableMouseFollow();
            this._scheduleNeutralPoseReset();
        }
    }

    async waitForLive2D() {
        const maxAttempts = 100;
        let attempts = 0;

        while (attempts < maxAttempts) {
            if (window.cubism5model) {
                this.appDelegate = window.cubism5model;
                console.log('[Live2D Controller] 找到 Cubism 5 模型');

                if (window.cubism5model.subdelegates && window.cubism5model.subdelegates.length > 0) {
                    for (let delegate of window.cubism5model.subdelegates) {
                        if (delegate.model) {
                            this.model = delegate.model;
                            console.log('[Live2D Controller] 找到 Live2D 模型实例');
                            break;
                        }
                    }
                }
                break;
            } else if (window.cubism2model) {
                this.cubism2model = window.cubism2model;
                console.log('[Live2D Controller] 找到 Cubism 2 模型');
                break;
            }

            attempts++;
            await new Promise(resolve => setTimeout(resolve, 100));
        }

        this.canvas = document.getElementById('live2d');
    }

    /**
     * 列出所有可用的表情（用于调试）
     */
    listExpressions() {
        console.log('%c========== Qianqian 可用表情列表 ==========', 'color: #4CAF50; font-size: 14px; font-weight: bold');
        console.log('%c基础使用:', 'color: #2196F3; font-weight: bold');
        console.log('  live2dController.playExpression("happy")');
        console.log('  live2dController.playExpressionByGroup("Happy")');
        console.log('');
        
        const categories = {
            '基础状态': ['idle', 'listening', 'starry', 'focused'],
            '正面情绪': ['happy', 'joy', 'love', 'loving', 'excited', 'playful'],
            '害羞/尴尬': ['shy', 'blush', 'embarrassed', 'awkward'],
            '负面情绪': ['sad', 'cry', 'angry', 'mad', 'annoyed', 'speechless', 'dark', 'blank'],
            '疑惑/思考': ['thinking', 'thinking2', 'confused', 'question'],
            '卖萌/可爱': ['pout', 'cute', 'puffed', 'heart'],
            '特殊眼部': ['starry', 'eyeball', 'money', 'love', 'reincarnation', 'blank'],
            '道具互动': ['mirror', 'fox', 'notebook', 'notebook2', 'gaming', 'hug', 'fan', 'mic', 'microphone', 'heart'],
            '发型切换': ['longhair', 'twintail', 'droopears'],
        };
        
        Object.entries(categories).forEach(([category, names]) => {
            console.log(`%c--- ${category} ---`, 'color: #FF9800; font-weight: bold');
            names.forEach(name => {
                const desc = this.QIANQIAN_EXPRESSION_DESC[name];
                if (desc) {
                    console.log(`  ${name.padEnd(15)} → ${desc}`);
                }
            });
        });
        
        console.log('');
        console.log('%c--- 可用分组 ---', 'color: #9C27B0; font-weight: bold');
        console.log('  基础: Idle, Listening, Thinking');
        console.log('  情绪: Happy, Sad, Angry, Worried, Confused, Shy');
        console.log('  特殊: EyeEffects, Hairstyles, WithItems, Cute');
        console.log('%c===========================================', 'color: #4CAF50; font-size: 14px; font-weight: bold');
        
        return Object.keys(this.QIANQIAN_EXPRESSION_DESC);
    }

    /**
     * 获取 Cubism5 LAppModel 实例
     */
    getAppModel() {
        try {
            const delegate = this.appDelegate || window.cubism5model;
            if (!delegate) return null;
            const sub = delegate.subdelegates?.at?.(0) || delegate.subdelegates?.[0];
            if (!sub) return null;
            const manager = sub.getLive2DManager?.();
            return manager?._models?.at?.(0) || null;
        } catch (e) {
            return null;
        }
    }

    /**
     * 获取 Live2D 管理器
     */
    getLive2DManager() {
        try {
            const delegate = this.appDelegate || window.cubism5model;
            if (!delegate) return null;
            const sub = delegate.subdelegates?.at?.(0) || delegate.subdelegates?.[0];
            if (!sub) return null;
            return sub.getLive2DManager?.() || null;
        } catch (e) {
            return null;
        }
    }

    /**
     * 获取 Cubism5 Live2DManager 实例
     */
    getLive2DManager() {
        try {
            const delegate = this.appDelegate || window.cubism5model;
            if (!delegate) return null;
            const sub = delegate.subdelegates?.at?.(0) || delegate.subdelegates?.[0];
            if (!sub) return null;
            return sub.getLive2DManager?.() || sub._live2dManager || null;
        } catch (e) {
            return null;
        }
    }

    /**
     * 当鼠标跟随关闭时，强制把模型朝向重置到正前方。
     * 解决页面刷新瞬间收到一次 mousemove 后模型停留在侧向的问题。
     */
    _resetNeutralPose() {
        const manager = this.getLive2DManager();
        const appModel = this.getAppModel();
        const coreModel = appModel?._model || manager?._models?.at?.(0) || manager?._models?.[0] || null;

        try {
            manager?.onDrag?.(0, 0);
            if (manager && '_dragX' in manager) manager._dragX = 0;
            if (manager && '_dragY' in manager) manager._dragY = 0;
            if (manager?._dragManager) {
                if (typeof manager._dragManager.set === 'function') {
                    manager._dragManager.set(0, 0);
                }
                if ('_x' in manager._dragManager) manager._dragManager._x = 0;
                if ('_y' in manager._dragManager) manager._dragManager._y = 0;
                if ('_targetX' in manager._dragManager) manager._dragManager._targetX = 0;
                if ('_targetY' in manager._dragManager) manager._dragManager._targetY = 0;
            }
        } catch (e) {
            console.warn('[Live2D] 重置拖拽状态失败:', e);
        }

        if (!coreModel || typeof coreModel.setParameterValueById !== 'function') {
            return;
        }

        try {
            [
                'ParamAngleX',
                'ParamAngleY',
                'ParamAngleZ',
                'ParamBodyAngleX',
                'ParamEyeBallX',
                'ParamEyeBallY'
            ].forEach(id => coreModel.setParameterValueById(id, 0));

            if (typeof coreModel.update === 'function') {
                coreModel.update();
            }
        } catch (e) {
            console.warn('[Live2D] 重置朝向参数失败:', e);
        }
    }

    /**
     * 连续多帧重置到中立朝向，避免初始化阶段的瞬时 mousemove 把模型卡在侧向。
     */
    _scheduleNeutralPoseReset(frames = 12) {
        let remaining = frames;

        const tick = () => {
            if (this._mouseFollowEnabled) {
                return;
            }

            this._resetNeutralPose();
            remaining -= 1;

            if (remaining > 0) {
                requestAnimationFrame(tick);
            }
        };

        requestAnimationFrame(tick);
        setTimeout(() => {
            if (!this._mouseFollowEnabled) {
                this._resetNeutralPose();
            }
        }, 250);
    }

    /**
     * 判断当前是否为 Qianqian 模型
     */
    _isQianqianModel() {
        const appModel = this.getAppModel();
        if (!appModel) return false;
        // 检查是否有表情管理器（Qianqian使用表情，Hiyori使用动作）
        try {
            // Qianqian模型有31个表情
            if (appModel._expressions && appModel._expressions.getSize) {
                return appModel._expressions.getSize() > 20;
            }
            // 或者检查模型路径
            if (appModel._modelSetting && appModel._modelSetting._json) {
                const json = appModel._modelSetting._json;
                if (json.FileReferences && json.FileReferences.Moc) {
                    return json.FileReferences.Moc.includes('qianqian');
                }
            }
        } catch (e) {}
        return false;
    }

    // ==================== Qianqian 表情映射 ====================
    // 详细配置见 qianqian-expressions.js
    
    // 语义名称到 expression 名称的映射（直观易读版本）
    // 格式: '语义名': 'expressionID'  // 中文名 - 描述
    QIANQIAN_EXPRESSIONS = {
        // === 基础状态 ===
        'idle': 'expression1',          // 星星眼 - 默认状态
        'default': 'expression1',       // 星星眼
        
        // === 正面情绪 ===
        'happy': 'expression5',         // 眼泪 - 开心的眼泪
        'joy': 'expression5',           // 眼泪
        'love': 'expression12',         // 爱心眼
        'loving': 'expression12',       // 爱心眼
        'excited': 'expression18',      // 星星 - 身边有星星
        'playful': 'expression15',      // 吐舌 - 调皮
        
        // === 害羞/尴尬 ===
        'shy': 'expression2',           // 脸红
        'blush': 'expression2',         // 脸红
        'embarrassed': 'expression9',   // 流汗 - 尴尬
        'awkward': 'expression9',       // 流汗
        
        // === 负面情绪 ===
        'sad': 'expression5',           // 眼泪
        'cry': 'expression5',           // 眼泪
        'angry': 'expression19',        // 生气
        'mad': 'expression19',          // 生气
        'annoyed': 'expression10',      // 无语
        'speechless': 'expression10',   // 无语
        'dark': 'expression4',          // 黑脸
        
        // === 疑惑/思考 ===
        'thinking': 'expression7',      // 问号
        'confused': 'expression7',      // 问号
        'question': 'expression7',      // 问号
        
        // === 卖萌/可爱 ===
        'pout': 'expression16',         // 嘟嘴
        'cute': 'expression16',         // 嘟嘴
        'puffed': 'expression17',       // 鼓嘴
        
        // === 特殊眼部 ===
        'starry': 'expression1',        // 星星眼
        'money': 'expression11',        // 钱眼
        'reincarnation': 'expression13', // 轮回眼
        'blank': 'expression14',        // 空白眼
        
        // === 监听/专注 ===
        'listening': 'expression1',     // 星星眼
        'focused': 'expression1',       // 星星眼
        
        // === 道具相关 ===
        'mirror': 'expression23',       // 镜子
        'fox': 'expression24',          // 狐狸
        'notebook': 'expression25',     // 笔记本
        'gaming': 'expression27',       // 打游戏
        'hug': 'expression28',          // 抱狐狸
        'fan': 'expression29',          // 扇子
        'mic': 'expression30',          // 话筒
        'microphone': 'expression30',   // 话筒
        'heart': 'expression31',        // 比心
        
        // === 发型 ===
        'longhair': 'expression20',     // 长发
        'twintail': 'expression21',     // 双马尾
        'droopears': 'expression22',    // 垂耳
    };
    
    // 反向映射: expressionID -> 主要语义名（用于日志显示）
    QIANQIAN_EXPRESSION_REVERSE = {
        'expression1': 'starry',        // 星星眼 (idle, default 也用它)
        'expression2': 'shy',           // 脸红
        'expression3': 'shy2',          // 脸红2
        'expression4': 'dark',          // 黑脸
        'expression5': 'happy',         // 眼泪 (开心)
        'expression6': 'eyeball',       // 眼珠
        'expression7': 'thinking',      // 问号
        'expression8': 'thinking2',     // 问号2
        'expression9': 'embarrassed',   // 流汗
        'expression10': 'speechless',   // 无语
        'expression11': 'money',        // 钱眼
        'expression12': 'love',         // 爱心眼
        'expression13': 'reincarnation', // 轮回眼
        'expression14': 'blank',        // 空白眼
        'expression15': 'playful',      // 吐舌
        'expression16': 'pout',         // 嘟嘴
        'expression17': 'puffed',       // 鼓嘴
        'expression18': 'excited',      // 星星
        'expression19': 'angry',        // 生气
        'expression20': 'longhair',     // 长发
        'expression21': 'twintail',     // 双马尾
        'expression22': 'droopears',    // 垂耳
        'expression23': 'mirror',       // 镜子
        'expression24': 'fox',          // 狐狸
        'expression25': 'notebook',     // 笔记本R
        'expression26': 'notebook2',    // 笔记本L
        'expression27': 'gaming',       // 打游戏
        'expression28': 'hug',          // 抱狐狸
        'expression29': 'fan',          // 扇子
        'expression30': 'mic',          // 话筒
        'expression31': 'heart',        // 比心
    };
    
    // 表情中文描述（用于日志）
    QIANQIAN_EXPRESSION_DESC = {
        'starry': '星星眼 ✨',
        'shy': '脸红 😳',
        'shy2': '脸红2 🥰',
        'dark': '黑脸 🌚',
        'happy': '开心的眼泪 😂',
        'eyeball': '眼珠 👁️',
        'thinking': '问号 ❓',
        'thinking2': '问号2 ❔',
        'embarrassed': '流汗 😅',
        'speechless': '无语 😑',
        'money': '钱眼 💰',
        'love': '爱心眼 ❤️',
        'reincarnation': '轮回眼 🔮',
        'blank': '空白眼 👀',
        'playful': '吐舌 😛',
        'pout': '嘟嘴 😗',
        'puffed': '鼓嘴 😤',
        'excited': '星星环绕 🌟',
        'angry': '生气 😠',
        'longhair': '长发 💇',
        'twintail': '双马尾 🎀',
        'droopears': '垂耳 🐰',
        'mirror': '镜子 🪞',
        'fox': '狐狸 🦊',
        'notebook': '笔记本 📓',
        'notebook2': '笔记本L 📔',
        'gaming': '打游戏 🎮',
        'hug': '抱狐狸 🤗',
        'fan': '扇子 🪭',
        'mic': '话筒 🎤',
        'heart': '比心 🫰',
    };

    // 表情分组（用于随机选择）- 使用语义名，更易读
    QIANQIAN_GROUPS = {
        // 基础状态
        'Idle': ['starry', 'thinking', 'thinking2', 'love', 'reincarnation', 'excited'],
        'Listening': ['starry', 'thinking', 'love', 'excited'],
        'Thinking': ['shy', 'shy2', 'dark', 'thinking', 'thinking2', 'speechless', 'money'],
        
        // 情绪分组
        'Happy': ['happy', 'eyeball', 'love', 'playful', 'pout', 'excited', 'heart'],
        'Sad': ['happy', 'blank'],
        'Angry': ['dark', 'puffed', 'angry'],
        'Worried': ['embarrassed', 'speechless', 'blank'],
        'Confused': ['thinking', 'thinking2', 'speechless'],
        'Shy': ['shy', 'shy2', 'embarrassed'],
        
        // 特殊分组
        'EyeEffects': ['starry', 'eyeball', 'money', 'love', 'reincarnation', 'blank'],
        'Hairstyles': ['longhair', 'twintail', 'droopears'],
        'WithItems': ['mirror', 'fox', 'notebook', 'notebook2', 'gaming', 'hug', 'fan', 'mic', 'heart'],
        'Cute': ['love', 'playful', 'pout', 'excited', 'heart'],
    };

    /**
     * 播放指定分组的表情（从分组中随机选择一个）
     * @param {string} group - 表情分组名，如 'Happy', 'Sad', 'Cute', 'EyeEffects' 等
     *                       使用 live2dController.listExpressions() 查看所有可用分组
     */
    playExpressionByGroup(group) {
        if (this._isQianqianModel()) {
            // Qianqian: 播放表情
            this._playQianqianRandomExpression(group);
        } else {
            // Hiyori: 播放动作
            this.playRandom(group, 1);
        }
    }

    /**
     * 禁用SDK的鼠标跟随（移除事件监听器）
     */
    _disableMouseFollowSDK() {
        console.log('[Live2D] 禁用SDK鼠标跟随...');
        
        if (window.cubism5model) {
            const delegate = window.cubism5model;
            if (delegate) {
                // 标记为已初始化，防止再次初始化
                delegate._initializedEventListeners = true;
                
                if (typeof delegate.releaseEventListener === 'function') {
                    try {
                        delegate.releaseEventListener();
                        console.log('[Live2D] 已调用 releaseEventListener');
                    } catch (e) {
                        console.warn('[Live2D] releaseEventListener 失败:', e);
                    }
                }
                
                // 移除已经添加的监听器
                if (delegate.mouseMoveEventListener) {
                    document.removeEventListener('mousemove', delegate.mouseMoveEventListener);
                    delegate.mouseMoveEventListener = null;
                    console.log('[Live2D] 已移除 mousemove 监听器');
                }
                if (delegate.mouseEndedEventListener) {
                    document.removeEventListener('mouseout', delegate.mouseEndedEventListener);
                    delegate.mouseEndedEventListener = null;
                }
                if (delegate.tapEventListener) {
                    document.removeEventListener('pointerdown', delegate.tapEventListener);
                    delegate.tapEventListener = null;
                }
            }
        }
        
        console.log('[Live2D] SDK鼠标跟随禁用完成');
    }
    
    /**
     * 禁用鼠标跟随。
     */
    _disableMouseFollow() {
        this._disableMouseFollowSDK();
        this._resetNeutralPose();
    }

    /**
     * 启用鼠标跟随
     */
    enableMouseFollow() {
        console.log('[Live2D] 启用鼠标跟随...');
        this._mouseFollowEnabled = true;
        localStorage.setItem('live2d_mouse_follow', 'true');
        
        // 重新初始化SDK的鼠标事件监听
        if (window.cubism5model) {
            const delegate = window.cubism5model;
            if (delegate && typeof delegate.initializeEventListener === 'function') {
                try {
                    delegate._initializedEventListeners = false;
                    delegate.initializeEventListener();
                    console.log('[Live2D] 鼠标事件监听器已初始化');
                } catch (e) {
                    console.warn('[Live2D] 初始化鼠标事件失败:', e);
                }
            }
        }
        
        this.updateStatus('鼠标跟随已开启');
    }

    /**
     * 禁用鼠标跟随（切换到自动动画）
     */
    disableMouseFollow() {
        console.log('[Live2D] 禁用鼠标跟随...');
        this._mouseFollowEnabled = false;
        localStorage.setItem('live2d_mouse_follow', 'false');
        
        // 禁用SDK的鼠标事件
        this._disableMouseFollowSDK();
        this._scheduleNeutralPoseReset();

        this.updateStatus('鼠标跟随已关闭');
    }
    
    /**
     * 更新状态显示
     */
    updateStatus(message) {
        // 如果有状态显示元素，更新它
        const statusEl = document.querySelector('.status-text');
        if (statusEl) {
            statusEl.textContent = message;
            setTimeout(() => {
                statusEl.textContent = '就绪';
            }, 2000);
        }
    }

    // ==================== 动作/表情播放接口 ====================

    /**
     * 播放指定名称的表情（自动适配模型类型）
     * @param {string} name - 表情语义名，如 'happy', 'love', 'shy' 等
     *                       使用 live2dController.listExpressions() 查看所有可用表情
     */
    playExpression(name) {
        if (this._isQianqianModel()) {
            this._setQianqianExpression(name);
        } else {
            this._playHiyoriMotion(name);
        }
    }

    /**
     * 清除当前表情
     */
    clearExpression() {
        if (this._expressionTimer) {
            clearTimeout(this._expressionTimer);
            this._expressionTimer = null;
        }
        
        const appModel = this.getAppModel();
        if (!appModel) return;
        
        try {
            appModel.setExpression('');
            const prevExpr = this._currentExpression;
            this._currentExpression = '';
            if (prevExpr) {
                const desc = this.QIANQIAN_EXPRESSION_DESC[prevExpr] || prevExpr;
                console.log(`[expression] 清除表情 (${desc})`);
            }
        } catch (e) {
            console.warn('[expression] 清除表情失败:', e);
        }
    }

    /**
     * 设置 Qianqian 表情
     * @param {string} name - 表情名称（语义名，如 'happy', 'love'）
     */
    _setQianqianExpression(name) {
        const appModel = this.getAppModel();
        if (!appModel) {
            console.warn('[expression] appModel 未就绪');
            return;
        }

        // 转换语义名到 expression ID
        const exprId = this.QIANQIAN_EXPRESSIONS[name];
        if (!exprId) {
            console.warn(`[expression] 未知表情: ${name}`);
            return;
        }
        
        try {
            appModel.setExpression(exprId);
            this._currentExpression = name;  // 存储语义名
            const desc = this.QIANQIAN_EXPRESSION_DESC[name] || name;
            console.log(`[expression] ${name} (${desc})`);
        } catch (e) {
            console.warn(`[expression] 设置表情失败: ${name}`, e);
        }
    }

    /**
     * 从分组中随机播放表情（Qianqian）
     * @param {string} group - 表情分组名
     */
    _playQianqianRandomExpression(group) {
        const expressions = this.QIANQIAN_GROUPS[group];
        if (!expressions || expressions.length === 0) {
            console.warn(`[expression] 未知表情组: ${group}`);
            return;
        }
        const semanticName = expressions[Math.floor(Math.random() * expressions.length)];
        this._setQianqianExpression(semanticName);
    }

    /**
     * 播放 Hiyori 动作
     * @param {string} name - 动作名称
     */
    _playHiyoriMotion(name) {
        const map = {
            'happy': () => this.playRandom('Happy'),
            'sad': () => this.playRandom('Worried'),
            'thinking': () => this.playRandom('Thinking'),
            'listening': () => this.playRandom('Listening'),
            'idle': () => this.playRandom('Idle'),
        };
        
        if (map[name]) {
            map[name]();
        } else {
            this.playRandom(name, 1);
        }
    }

    /**
     * 从指定组随机播放动作（Hiyori 兼容）
     * @param {string} group - 动作组名
     * @param {number} priority - 优先级
     */
    playRandom(group, priority = 1) {
        const appModel = this.getAppModel();
        if (!appModel) {
            console.warn('[motion] appModel 未就绪');
            return;
        }

        try {
            // Cubism5 的 motion 接口
            if (typeof appModel.startMotion === 'function') {
                // 构建 motion 文件名（例如 Idle -> m01）
                const motionMap = {
                    'Idle': 'm01',
                    'Listening': 'm02',
                    'Thinking': 'm03',
                    'Worried': 'm04',
                    'Happy': 'm05',
                };
                const motionName = motionMap[group] || 'm01';
                appModel.startMotion(motionName, priority);
                console.log('[motion] startMotion(' + motionName + ', ' + priority + ')');
            }
        } catch (e) {
            console.warn('[motion] 播放动作失败:', e);
        }
    }

    /**
     * 播放指定动作（预览用）
     * @param {string} motionName - 动作名称（如 m01, m02）
     */
    playMotion(motionName) {
        const appModel = this.getAppModel();
        if (!appModel) {
            console.warn('[motion] appModel 未就绪');
            return;
        }

        try {
            if (typeof appModel.startMotion === 'function') {
                appModel.startMotion(motionName, 3);  // 高优先级
                console.log('[motion] 播放动作:', motionName);
            }
        } catch (e) {
            console.warn('[motion] 播放动作失败:', e);
        }
    }

    /**
     * 播放问候动画
     */
    playGreeting() {
        this.playExpressionByGroup('Happy');
    }

    /**
     * 播放思考动画
     */
    playThinking() {
        this.playExpressionByGroup('Thinking');
    }

    /**
     * 播放聆听动画
     */
    playListening() {
        this.playExpressionByGroup('Listening');
    }

    /**
     * 播放随机 Idle 动画
     */
    playRandomIdle() {
        this.playExpressionByGroup('Idle');
    }

    /**
     * 播放说话状态动画
     */
    playTalking() {
        // 保持当前动作，由嘴型同步驱动口型
    }

    /**
     * 兼容动作面板接口
     * @param {string} motionName - 动作名称（如 m01, m02）
     */
    playMotionByName(motionName) {
        this.playMotion(motionName);
    }

    /**
     * 解锁音频上下文（浏览器自动播放策略要求）
     */
    unlockAudioContext() {
        if (!this.audioContext) {
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (this.audioContext.state === 'suspended') {
            this.audioContext.resume().catch(() => {});
        }
    }

    /**
     * 启动嘴型分析循环。
     */
    _ensureMouthLoop() {
        if (this._mouthLoopRunning) return;
        this._mouthLoopRunning = true;

        const tick = () => {
            const ctx = this.audioContext;
            if (!ctx) {
                this._mouthLoopRunning = false;
                this.setMouthOpen(0);
                return;
            }

            const now = ctx.currentTime;

            // 清理已经播放结束的链路
            this._activeAudioChains = this._activeAudioChains.filter(chain => {
                return !chain.ended || now < chain.endTime + 0.1;
            });

            const activeChain = this._activeAudioChains.find(chain => {
                return now >= chain.startTime && now <= chain.endTime + 0.03;
            });

            const hasFutureAudio = this._activeAudioChains.some(chain => chain.endTime > now);

            if (activeChain) {
                const { analyser, dataArray } = activeChain;
                analyser.getByteTimeDomainData(dataArray);

                let sumSquares = 0;
                for (let i = 0; i < dataArray.length; i++) {
                    const sample = (dataArray[i] - 128) / 128;
                    sumSquares += sample * sample;
                }

                const rms = Math.sqrt(sumSquares / dataArray.length);
                const mouthValue = Math.max(0, Math.min(1, (rms - 0.015) * 10));
                this.isSpeaking = true;
                this.setMouthOpen(mouthValue);
                requestAnimationFrame(tick);
                return;
            }

            if (hasFutureAudio) {
                this.isSpeaking = true;
                this.setMouthOpen(0);
                requestAnimationFrame(tick);
                return;
            }

            this.isSpeaking = false;
            this._mouthLoopRunning = false;
            this.setMouthOpen(0);
        };

        requestAnimationFrame(tick);
    }

    /**
     * 调度音频缓冲区（WebAudio 路径，带嘴型同步）
     * @param {AudioBuffer} audioBuffer - 解码后的音频缓冲
     */
    scheduleAudioBuffer(audioBuffer) {
        if (!audioBuffer) return;

        this.unlockAudioContext();
        const ctx = this.audioContext;
        if (!ctx) return;

        const source = ctx.createBufferSource();
        source.buffer = audioBuffer;

        const analyser = ctx.createAnalyser();
        analyser.fftSize = 1024;
        analyser.smoothingTimeConstant = 0.6;
        const dataArray = new Uint8Array(analyser.fftSize);

        source.connect(analyser);
        analyser.connect(ctx.destination);

        const startTime = Math.max(ctx.currentTime, this._nextScheduledTime || 0);
        const endTime = startTime + audioBuffer.duration;
        const chain = {
            source,
            analyser,
            dataArray,
            startTime,
            endTime,
            ended: false,
        };

        this._activeAudioChains.push(chain);
        this._activeAudioChains.sort((a, b) => a.startTime - b.startTime);
        this._nextScheduledTime = endTime;
        this.isSpeaking = true;

        source.onended = () => {
            chain.ended = true;
            const now = this.audioContext?.currentTime ?? 0;
            this._activeAudioChains = this._activeAudioChains.filter(item => {
                return item !== chain && (!item.ended || now < item.endTime + 0.1);
            });
            if (this._activeAudioChains.length === 0 && now >= this._nextScheduledTime - 0.05) {
                this.stopLipSync();
            }
        };

        source.start(startTime);
        this._ensureMouthLoop();
    }

    /**
     * 使用嘴型同步播放音频
     * @param {string} base64Audio - base64 编码的音频
     * @param {Function} onEnded - 播放结束回调
     * @param {Object} payload - 音频元信息
     */
    playAudioWithLipSync(base64Audio, onEnded, payload = {}) {
        try {
            this.unlockAudioContext();

            const binary = window.atob(base64Audio);
            const arrayBuffer = new ArrayBuffer(binary.length);
            const view = new Uint8Array(arrayBuffer);
            for (let i = 0; i < binary.length; i++) {
                view[i] = binary.charCodeAt(i);
            }

            const format = payload.format || 'mp3';

            if (format === 'pcm_s16le') {
                const audioBuffer = this._pcm16ToAudioBuffer(
                    arrayBuffer,
                    payload.sample_rate || 24000,
                    payload.channels || 1,
                );
                if (!audioBuffer) {
                    if (onEnded) onEnded();
                    return;
                }
                this.scheduleAudioBuffer(audioBuffer);
                if (onEnded) {
                    setTimeout(() => onEnded(), Math.max(0, audioBuffer.duration * 1000));
                }
                return;
            }

            this.audioContext.decodeAudioData(arrayBuffer.slice(0))
                .then((buffer) => {
                    this.scheduleAudioBuffer(buffer);
                    if (onEnded) {
                        setTimeout(() => onEnded(), Math.max(0, buffer.duration * 1000));
                    }
                })
                .catch((e) => {
                    console.warn('[Live2D] 音频解码失败:', e);
                    if (onEnded) onEnded();
                });
        } catch (e) {
            console.warn('[Live2D] 播放音频失败:', e);
            if (onEnded) onEnded();
        }
    }

    _pcm16ToAudioBuffer(arrayBuffer, sampleRate = 24000, channels = 1) {
        const ctx = this.audioContext;
        if (!ctx) return null;

        const bytesPerSample = 2;
        const frameCount = Math.floor(arrayBuffer.byteLength / (bytesPerSample * channels));
        if (frameCount <= 0) return null;

        const audioBuffer = ctx.createBuffer(channels, frameCount, sampleRate);
        const view = new DataView(arrayBuffer);

        for (let channel = 0; channel < channels; channel++) {
            const channelData = audioBuffer.getChannelData(channel);
            for (let i = 0; i < frameCount; i++) {
                const offset = (i * channels + channel) * bytesPerSample;
                channelData[i] = view.getInt16(offset, true) / 32768;
            }
        }

        return audioBuffer;
    }

    /**
     * 停止当前音频
     */
    stopCurrentAudio() {
        for (const chain of this._activeAudioChains) {
            try {
                chain.source.onended = null;
                chain.source.stop();
            } catch (_) {}
        }
        this._activeAudioChains = [];
        this._nextScheduledTime = this.audioContext?.currentTime || 0;
        this.stopLipSync();
    }

    /**
     * 停止嘴型同步
     */
    stopLipSync() {
        this.isSpeaking = false;
        this._mouthLoopRunning = false;
        this.setMouthOpen(0);
    }

    // ==================== 嘴型同步接口 ====================
    
    /**
     * 设置嘴型张开程度（由 lip-sync-patch.js 调用）
     * @param {number} value - 0~1 之间的值
     */
    setMouthOpen(value) {
        // 直接更新全局变量，让补丁读取
        if (typeof window._live2dSetMouthValue === 'function') {
            window._live2dSetMouthValue(value);
        }
    }

    /**
     * 销毁控制器
     */
    destroy() {
        this.stopCurrentAudio();
        if (this.audioContext) {
            this.audioContext.close().catch(() => {});
            this.audioContext = null;
        }
    }

    // ==================== 动作别名（与 app.js 兼容）====================

    playWave() { this.playMotion('m05'); }
    playHeadShake() { this.playMotion('m04'); }
    playNod() { this.playMotion('m03'); }
    playWaveLeft() { this.playMotion('m06'); }
    playShrug() { this.playMotion('m10'); }
    playLegSwing() { this.playMotion('m01'); }
    playJump() { this.playMotion('m07'); }
    playSway() { this.playMotion('m08'); }
}

// 创建全局实例
const live2dController = new Live2DController();
window.live2dController = live2dController;
