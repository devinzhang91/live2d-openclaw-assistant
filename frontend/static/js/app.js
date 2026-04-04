/**
 * 主应用
 */
class App {
    constructor() {
        this.audioRecorder = null;
        this.chatManager = null;
        this.isRecording = false;
        this.currentResponseElement = null;
        this.recordingMessage = null;  // 录音消息元素
        this.audioAvailable = false;  // 音频是否可用
        this.inputMode = 'text';  // 当前输入模式: 'text' 或 'voice'
        this.vadMode = 'hold';  // VAD 模式: 'hold' (按住说话) 或 'auto' (自动检测)
        this.vadListening = false;  // VAD 是否正在监听
        this.realtimeFullDuplex = false;  // 是否为全双工实时语音模式
        this.realtimeRecording = false;  // 全双工模式下是否正在录音
        this.realtimeTimer = null;        // 全双工模式 200ms 发包定时器
        this.live2dController = null;  // Live2D 控制器
        this.ttsAudioBuffer = [];  // TTS 音频缓冲区（备用）
        this.ttsPlaying = false;  // TTS 是否正在播放
        this._currentHtmlAudio = null; // 当前非 Live2D 路径播放的 HTML Audio 元素
        this.audioQueue = [];       // 流式 TTS 音频 FIFO 播放队列（降级串行路径）
        this._audioPlaying = false; // 当前是否正在播放音频
        this._decodedQueue = [];    // 并行 decode、顺序调度队列（WebAudio 无缝路径）
        this._schedulerRunning = false; // _runDecodeScheduler 是否正在运行
        this._sessionId = 0;        // 每次新请求递增，用于丢弃旧请求的残留音频
        this._settingsData = null;  // 设置数据缓存
        this._vadPausedForTts = false; // TTS 播放期间是否临时关闭了 VAD
        this.openclawThinkingElement = null;  // OpenClaw 查询中气泡元素
        this.live2dThinkingElement = null;     // Live2D 思考中气泡元素
        this._pwAiText = '';                   // 纯白模式 AI 气泡当前内容
        this._pwUserText = '';                 // 纯白模式用户气泡当前内容
    }

    async init() {
        try {
            // Live2D 由 autoload.js 自动加载，无需手动初始化
            console.log('Live2D 由 autoload.js 自动加载');

            // 初始化 Live2D 控制器
            await this.initLive2DController();

            // 初始化音频录制器
            await this.initAudioRecorder();

            // 初始化聊天管理器
            await this.initChatManager();

            // 初始化设置
            await this.initSettings();

            // 绑定事件
            this.bindEvents();

            // 初始化输入模式
            this.initInputMode();

            console.log('应用初始化完成');
        } catch (error) {
            console.error('应用初始化失败:', error);
            this.showError('应用初始化失败，请刷新页面重试');
        }
    }

    async initLive2DController() {
        try {
            if (typeof live2dController !== 'undefined') {
                this.live2dController = live2dController;
                await this.live2dController.init();
                console.log('Live2D 控制器初始化成功');
                // 初始化完成后延迟打招呼（等 motion-patch 也就绪）
                setTimeout(() => {
                    if (this.live2dController && this.live2dController.ready) {
                        this.live2dController.playGreeting();
                    }
                }, 3000);
            }
        } catch (error) {
            console.warn('Live2D 控制器初始化失败:', error);
        }
    }

    async initAudioRecorder() {
        try {
            this.audioRecorder = new (AudioRecorder || AudioRecorder)({
                sampleRate: 16000,
                channelCount: 1,
                vadSilenceMs: 2500,    // 静音 2.5s 后才切段，支持长句中的自然停顿
                vadMaxSpeechMs: 60000  // 单段最长 60s
            });

            // 设置音频块回调（仅用于按住说话模式，流式发送）
            this.audioRecorder.onDataChunk = async (audioChunk) => {
                if (this.chatManager && this.isRecording) {
                    const base64 = this.arrayBufferToBase64(audioChunk);
                    this.chatManager.sendAudioChunk(base64);
                }
            };

            // 设置停止回调
            this.audioRecorder.onStop = async (audioBlob) => {
                console.log('录音完成');
                this.isRecording = false;

                // 更新录音消息
                if (this.recordingMessage) {
                    this.recordingMessage.element.querySelector('.message-content').textContent = '🎤 录音消息';
                }
            };

            await this.audioRecorder.init();
            this.audioAvailable = true;
            console.log('音频录制器初始化成功');
        } catch (error) {
            console.warn('音频录制器初始化失败:', error);
            this.audioAvailable = false;
            // 不阻止应用运行，只禁用语音模式
        }
    }

    async initChatManager() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';

        // 根据 voice_mode 选择 WebSocket 端点
        let wsPath = '/api/ws/chat';
        if (this._settingsData && this._settingsData.voice_mode === 'realtime_volc') {
            wsPath = '/api/ws/realtime_volc';
            this.realtimeFullDuplex = true;
        }

        const wsUrl = `${protocol}//${window.location.host}${wsPath}`;
        console.log(`[WebSocket] voice_mode=${this._settingsData?.voice_mode || 'unknown'}, connecting to: ${wsUrl}`);

        this.chatManager = new ChatManager(wsUrl);

        this.chatManager.onStatus = (message) => {
            this.updateStatus(message);
        };

        this.chatManager.onError = (message) => {
            this.showError(message);
        };

        this.chatManager.onMessage = (data) => {
            this.handleChatMessage(data);
        };

        this.chatManager.connect();
    }

    initInputMode() {
        // 初始化模式切换按钮
        const textModeBtn = document.getElementById('textModeBtn');
        const voiceModeBtn = document.getElementById('voiceModeBtn');

        // 如果音频不可用，禁用语音模式按钮
        if (!this.audioAvailable) {
            voiceModeBtn.classList.add('disabled');
            voiceModeBtn.title = '音频功能不可用';
            // 显示提示
            this.showError('音频功能不可用，请使用文字输入（或使用 HTTPS 访问以启用语音）');
        }

        // 文字模式按钮
        textModeBtn.addEventListener('click', () => {
            this.switchInputMode('text');
        });

        // 语音模式按钮
        voiceModeBtn.addEventListener('click', () => {
            if (this.audioAvailable) {
                this.switchInputMode('voice');
            }
        });
    }

    switchInputMode(mode) {
        this.inputMode = mode;

        const textModeBtn = document.getElementById('textModeBtn');
        const voiceModeBtn = document.getElementById('voiceModeBtn');
        const textInputArea = document.getElementById('textInputArea');
        const voiceInputArea = document.getElementById('voiceInputArea');

        if (mode === 'text') {
            textModeBtn.classList.add('active');
            voiceModeBtn.classList.remove('active');
            textInputArea.style.display = 'flex';
            voiceInputArea.style.display = 'none';
            // 停止 VAD 监听
            this.stopVadListening();
        } else {
            voiceModeBtn.classList.add('active');
            textModeBtn.classList.remove('active');
            voiceInputArea.style.display = 'flex';
            textInputArea.style.display = 'none';
            // 全双工模式下不需要前端 VAD，等待用户点击按钮
        }
    }

    switchVadMode(mode) {
        this.vadMode = mode;

        const holdToSpeakBtn = document.getElementById('holdToSpeakBtn');
        const vadAutoBtn = document.getElementById('vadAutoBtn');
        const voicePrompt = document.getElementById('voicePrompt');
        const recordBtn = document.getElementById('recordBtn');

        if (mode === 'hold') {
            holdToSpeakBtn.classList.add('active');
            vadAutoBtn.classList.remove('listening');
            voicePrompt.textContent = '按住录音按钮开始说话';
            voicePrompt.style.background = '#f1f5f9';
            voicePrompt.style.color = '#64748b';
            recordBtn.style.display = 'block';
            // 停止 VAD 监听
            this.stopVadListening();
        } else {
            vadAutoBtn.classList.add('listening');
            holdToSpeakBtn.classList.remove('active');
            voicePrompt.textContent = 'VAD 正在... 请直接说话';
            voicePrompt.style.background = '#dcfce7';
            voicePrompt.style.color = '#16a34a';
            recordBtn.style.display = 'none';
            // 开始 VAD 监听
            this.startVadListening();
        }
    }

    _setVoicePrompt(text, background, color) {
        const voicePrompt = document.getElementById('voicePrompt');
        if (!voicePrompt) return;
        voicePrompt.textContent = text;
        voicePrompt.style.background = background;
        voicePrompt.style.color = color;
    }

    _isVadInterruptEnabled() {
        return !!(this._settingsData && this._settingsData.vad_interrupt_tts);
    }

    _shouldAutoResumeVad() {
        return this.audioAvailable && this.inputMode === 'voice' && this.vadMode === 'auto' && !this.isRecording;
    }

    _hasActiveTtsPlayback() {
        return !!(
            this.ttsPlaying ||
            this._audioPlaying ||
            this._currentHtmlAudio ||
            this.audioQueue.length > 0 ||
            this._decodedQueue.length > 0
        );
    }

    _onTtsPlaybackStart() {
        this.ttsPlaying = true;

        if (!this._shouldAutoResumeVad() || this._isVadInterruptEnabled()) {
            return;
        }

        if (this.vadListening) {
            this._vadPausedForTts = true;
            this.stopVadListening();
        }

        this._setVoicePrompt('🔈 AI 回复中，已暂停监听', '#e0e7ff', '#4338ca');
        this.updateStatus('AI 回复中...');
    }

    _resumeVadAfterTts() {
        if (!this._vadPausedForTts) {
            return;
        }

        this._vadPausedForTts = false;

        if (this._shouldAutoResumeVad() && !this.vadListening) {
            this.startVadListening();
        }
    }

    _finalizeTtsPlayback(sessionId = this._sessionId) {
        if (sessionId !== this._sessionId) {
            return;
        }

        this.ttsPlaying = false;
        this._audioPlaying = false;
        this.updateStatus(this.openclawThinkingElement ? 'OpenClaw 处理中...' : '就绪');
        this._live2dReact('tts_end');
        this._resumeVadAfterTts();
    }

    bindEvents() {
        // 发送按钮
        const sendBtn = document.getElementById('sendBtn');
        sendBtn.addEventListener('click', () => {
            this.handleSendText();
        });

        // 文本输入框回车发送
        const textInput = document.getElementById('textInput');
        textInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.handleSendText();
            }
        });

        // VAD 模式切换按钮
        const holdToSpeakBtn = document.getElementById('holdToSpeakBtn');
        const vadAutoBtn = document.getElementById('vadAutoBtn');

        holdToSpeakBtn.addEventListener('click', () => {
            this.switchVadMode('hold');
        });

        vadAutoBtn.addEventListener('click', () => {
            this.switchVadMode('auto');
        });

        // 录音按钮（仅按住说话模式使用）
        const recordBtn = document.getElementById('recordBtn');

        // 全双工模式：点击开始/停止
        // 非全双工模式：按住说话
        if (this.realtimeFullDuplex) {
            recordBtn.addEventListener('click', () => {
                if (this.realtimeRecording) {
                    this.stopRealtimeRecording();
                } else {
                    this.startRealtimeRecording();
                }
            });
        } else {
            // 按住说话（原有逻辑）
            recordBtn.addEventListener('mousedown', () => { this.startRecording(); });
            recordBtn.addEventListener('mouseup', () => { this.stopRecording(); });
            recordBtn.addEventListener('mouseleave', () => {
                if (this.isRecording) this.stopRecording();
            });
            recordBtn.addEventListener('touchstart', (e) => { e.preventDefault(); this.startRecording(); });
            recordBtn.addEventListener('touchend', (e) => { e.preventDefault(); this.stopRecording(); });
        }

        // 纯白模式按钮
        document.getElementById('pureWhiteModeBtn').addEventListener('click', () => {
            this.togglePureWhiteMode();
        });
        document.getElementById('pureWhiteExitBtn').addEventListener('click', () => {
            this.togglePureWhiteMode(false);
        });

        // 设置按钮
        document.getElementById('settingsBtn').addEventListener('click', () => {
            this.openSettings();
        });

        document.getElementById('settingsClose').addEventListener('click', () => {
            this.closeSettings();
        });

        document.getElementById('settingsCancel').addEventListener('click', () => {
            this.closeSettings();
        });

        document.getElementById('settingsSave').addEventListener('click', () => {
            this.saveSettings();
        });

        // 点击遮罩层关闭
        document.getElementById('settingsModal').addEventListener('click', (e) => {
            if (e.target === e.currentTarget) {
                this.closeSettings();
            }
        });

        // 语速滑块实时更新标签
        document.getElementById('speedSlider').addEventListener('input', (e) => {
            document.getElementById('speedBadge').textContent = `${parseFloat(e.target.value).toFixed(1)}x`;
        });

        // VAD 灵敏度滑块实时更新标签
        document.getElementById('vadThreshSlider').addEventListener('input', (e) => {
            const v = parseFloat(e.target.value);
            document.getElementById('vadThreshBadge').textContent = v.toFixed(3);
        });

        // 性格下拉框更新提示
        document.getElementById('personalitySelect').addEventListener('change', (e) => {
            this._updatePersonalityHint(e.target.value);
        });

        // ===== 动作预览面板 =====
        const motionPanelToggle = document.getElementById('motionPanelToggle');
        const motionPanel = document.getElementById('motionPanel');
        const motionPanelClose = document.getElementById('motionPanelClose');

        if (motionPanelToggle && motionPanel) {
            motionPanelToggle.addEventListener('click', () => {
                motionPanel.classList.toggle('open');
            });
        }
        if (motionPanelClose && motionPanel) {
            motionPanelClose.addEventListener('click', () => {
                motionPanel.classList.remove('open');
            });
        }

        // 动作按钮：点击播放对应动作
        document.querySelectorAll('.motion-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const motionName = btn.dataset.motion;
                if (this.live2dController && motionName) {
                    this.live2dController.playMotionByName(motionName);
                    // 短暂高亮按钮
                    btn.classList.add('playing');
                    setTimeout(() => btn.classList.remove('playing'), 600);
                }
            });
        });
    }

    togglePureWhiteMode(force) {
        const active = (force !== undefined) ? !!force : !document.body.classList.contains('pure-white-mode');
        document.body.classList.toggle('pure-white-mode', active);
        const btn = document.getElementById('pureWhiteModeBtn');
        if (active) {
            btn.textContent = '🔵';
            btn.title = '退出纯白模式';
            btn.classList.add('active');
            // 进入纯白模式时刷新气泡内容
            this._updatePwBubble('ai', this._pwAiText, false);
            this._updatePwBubble('user', this._pwUserText, false);
        } else {
            btn.textContent = '⚪';
            btn.title = '纯白模式';
            btn.classList.remove('active');
        }
    }

    /**
     * 更新纯白模式浮动气泡
     * @param {'ai'|'user'} role
     * @param {string} text
     * @param {boolean} streaming - 是否显示流式光标
     */
    _updatePwBubble(role, text, streaming = false) {
        const el = document.getElementById(role === 'ai' ? 'pwBubbleAI' : 'pwBubbleUser');
        if (!el) return;
        if (role === 'ai') this._pwAiText = text;
        else this._pwUserText = text;
        const textEl = el.querySelector('.pw-bubble-text');
        if (textEl) textEl.textContent = text;
        el.classList.toggle('streaming', streaming);
        el.classList.toggle('visible', !!text);
    }

    async handleSendText() {
        const textInput = document.getElementById('textInput');
        const text = textInput.value.trim();

        if (!text) {
            return;
        }

        // 用户手势帧内立即解锁 AudioContext（浏览器自动播放策略要求）
        if (this.live2dController) {
            this.live2dController.unlockAudioContext();
        }

        // 清空输入框
        textInput.value = '';

        // 显示用户消息
        this.addMessage('user', text);

        // Live2D: 用户发送 → 点头确认
        this._live2dReact('user_send');

        // 发送到服务器
        this.chatManager.sendText(text);

        // 新消息开始：递增 sessionId 使旧音频自动失效，重置队列和 WebAudio 调度时钟
        this._sessionId++;
        this.audioQueue = [];
        this._decodedQueue = [];
        this._audioPlaying = false;
        if (this.live2dController) {
            this.live2dController._nextScheduledTime = 0;
        }
    }

    startVadListening() {
        if (this.vadListening || !this.audioAvailable) {
            return;
        }

        try {
            // VAD 说话开始 → 通知后端开始接收音频流
            this.audioRecorder.onVadSpeechStart = () => {
                console.log('[VAD] 检测到说话开始 → audio_start');
                if (this._isVadInterruptEnabled() && this._hasActiveTtsPlayback()) {
                    this._interruptTts();
                }
                if (this.live2dController) this.live2dController.unlockAudioContext();
                this._live2dReact('listening');  // 聆听状态动作
                if (this.chatManager) this.chatManager.startAudioStream();
                this._setVoicePrompt('🎤 正在说话...', '#dcfce7', '#16a34a');
                this.updateStatus('正在录音...');
            };

            // VAD 流式音频块 → 持续推送给后端累积
            this.audioRecorder.onAudioChunk = (wavArrayBuffer) => {
                if (!this.chatManager) return;
                const base64 = this.arrayBufferToBase64(wavArrayBuffer);
                this.chatManager.sendAudioChunk(base64);
            };

            // VAD 说话结束 → 通知后端停止接收，触发 ASR 识别
            this.audioRecorder.onVadSpeechEnd = () => {
                console.log('[VAD] 检测到说话结束 → audio_end，触发 ASR');
                if (this.chatManager) this.chatManager.endAudioStream();
                this._setVoicePrompt('⏳ 正在识别...', '#fef9c3', '#a16207');
                this.updateStatus('正在识别...');
            };

            // 启动前端 VAD
            this.audioRecorder.startVAD();
            this.vadListening = true;

            this._setVoicePrompt('🎤 VAD 监听中... 请说话', '#dcfce7', '#16a34a');

            this.updateStatus('VAD 监听中...');
            console.log('VAD 自动监听已启动');
        } catch (error) {
            console.error('启动 VAD 监听失败:', error);
            this.showError('无法启动 VAD 监听');
        }
    }

    stopVadListening() {
        if (!this.vadListening) {
            return;
        }

        try {
            this.audioRecorder.stopVAD();
            this.vadListening = false;

            this._setVoicePrompt('VAD 模式', '#f1f5f9', '#64748b');

            this.updateStatus('就绪');
            console.log('VAD 自动监听已停止');
        } catch (error) {
            console.error('停止 VAD 监听失败:', error);
            this.vadListening = false;
        }
    }

    startRecording() {
        if (this.isRecording || !this.audioAvailable) {
            return;
        }

        try {
            // 用户手势帧内立即解锁 AudioContext
            if (this.live2dController) {
                this.live2dController.unlockAudioContext();
            }
            this._live2dReact('listening');  // 聆听状态动作

            this.audioRecorder.start();
            this.isRecording = true;

            const recordBtn = document.getElementById('recordBtn');
            recordBtn.classList.add('recording');

            const voicePrompt = document.getElementById('voicePrompt');
            if (voicePrompt) {
                voicePrompt.textContent = '正在录音...';
                voicePrompt.style.background = '#fee2e2';
                voicePrompt.style.color = '#ef4444';
            }

            this.updateStatus('正在录音...');

            // 开始音频流
            this.chatManager.startAudioStream();

            // 添加录音消息（带动画）
            this.recordingMessage = this.addMessage('user', '🎤 正在录音...');
            this._animateRecordingMessage();

        } catch (error) {
            console.error('开始录音失败:', error);
            this.showError('无法开始录音');
        }
    }

    stopRecording() {
        if (!this.isRecording) {
            return;
        }

        try {
            this.audioRecorder.stop();

            const recordBtn = document.getElementById('recordBtn');
            recordBtn.classList.remove('recording');

            const voicePrompt = document.getElementById('voicePrompt');
            if (voicePrompt) {
                voicePrompt.textContent = '按住录音按钮开始说话';
                voicePrompt.style.background = '#f1f5f9';
                voicePrompt.style.color = '#64748b';
            }

            this.updateStatus('正在处理...');

            // 结束音频流
            if (this.chatManager) {
                this.chatManager.endAudioStream();
            }

            // 停止录音消息
            if (this.recordingMessage) {
                this.recordingMessage.element.querySelector('.message-content').textContent = '🎤 正在处理...';
                this.recordingMessage = null;
            }

        } catch (error) {
            console.error('停止录音失败:', error);
            this.isRecording = false;
        }
    }

    startRealtimeRecording() {
        if (this.realtimeRecording || !this.audioAvailable) {
            return;
        }

        try {
            if (this.live2dController) {
                this.live2dController.unlockAudioContext();
            }
            this._live2dReact('listening');

            this.audioRecorder.start();
            this.realtimeRecording = true;

            const recordBtn = document.getElementById('recordBtn');
            recordBtn.classList.add('recording');

            const voicePrompt = document.getElementById('voicePrompt');
            if (voicePrompt) {
                voicePrompt.textContent = '实时录音中...';
                voicePrompt.style.background = '#fee2e2';
                voicePrompt.style.color = '#ef4444';
            }

            this.updateStatus('实时录音中...');

            // 开始音频流
            this.chatManager.startAudioStream();

            // 添加录音消息
            this.recordingMessage = this.addMessage('user', '🎤 实时录音中...');
            this._animateRecordingMessage();

            // 启动 200ms 发包定时器
            this.realtimeTimer = setInterval(() => {
                if (this.realtimeRecording && this.audioRecorder && this.audioRecorder.audioData) {
                    const chunk = this.audioRecorder.getAudioData();
                    if (chunk && chunk.length > 0) {
                        const base64 = this.arrayBufferToBase64(chunk);
                        this.chatManager.sendAudioChunk(base64);
                    }
                }
            }, 200);

        } catch (error) {
            console.error('开始实时录音失败:', error);
            this.showError('无法开始实时录音');
        }
    }

    stopRealtimeRecording() {
        if (!this.realtimeRecording) {
            return;
        }

        try {
            // 停止定时器
            if (this.realtimeTimer) {
                clearInterval(this.realtimeTimer);
                this.realtimeTimer = null;
            }

            this.audioRecorder.stop();

            const recordBtn = document.getElementById('recordBtn');
            recordBtn.classList.remove('recording');

            const voicePrompt = document.getElementById('voicePrompt');
            if (voicePrompt) {
                voicePrompt.textContent = '按住录音按钮开始说话';
                voicePrompt.style.background = '#f1f5f9';
                voicePrompt.style.color = '#64748b';
            }

            this.updateStatus('正在处理...');

            // 结束音频流
            if (this.chatManager) {
                this.chatManager.endAudioStream();
            }

            // 停止录音消息
            if (this.recordingMessage) {
                this.recordingMessage.element.querySelector('.message-content').textContent = '🎤 正在处理...';
            }

        } catch (error) {
            console.error('停止实时录音失败:', error);
        } finally {
            this.recordingMessage = null;
            this.realtimeRecording = false;
        }
    }

    _animateRecordingMessage() {
        // 录音消息动画
        const dots = '...';
        let dotCount = 0;

        this.recordingInterval = setInterval(() => {
            if (this.recordingMessage) {
                dotCount = (dotCount + 1) % 4;
                const text = '🎤 正在录音' + dots.substring(0, dotCount);
                this.recordingMessage.element.querySelector('.message-content').textContent = text;
            }
        }, 500);
    }

    arrayBufferToBase64(buffer) {
        let binary = '';
        const bytes = new Uint8Array(buffer);
        const len = bytes.byteLength;
        for (let i = 0; i < len; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return window.btoa(binary);
    }

    handleChatMessage(data) {
        switch (data.type) {
            case 'asr_chunk':
                // ASR 增量片段（追加）
                if (this.currentResponseElement && this.currentResponseElement.type === 'asr') {
                    this.currentResponseElement.element.querySelector('.message-content').textContent += data.content;
                    this.scrollToBottom();
                } else {
                    this.currentResponseElement = this.addMessage('user', data.content);
                    this.currentResponseElement.type = 'asr';
                }
                this._updatePwBubble('user',
                    this.currentResponseElement.element.querySelector('.message-content').textContent, true);
                break;

            case 'asr_partial':
                // ASR 中间结果快照（替换，每次都是完整识别内容）
                if (this.currentResponseElement && this.currentResponseElement.type === 'asr') {
                    this.currentResponseElement.element.querySelector('.message-content').textContent = data.content;
                    this.scrollToBottom();
                } else {
                    this.currentResponseElement = this.addMessage('user', data.content);
                    this.currentResponseElement.type = 'asr';
                }
                this._updatePwBubble('user', data.content, true);
                break;

            case 'asr_complete':
                // ASR 有结果：确认是真实语音，此时才打断 TTS 并开始新对话
                if (data.content) {
                    this._interruptTts();  // 停止当前 TTS 播放并清空队列
                }
                if (this.recordingMessage) {
                    this.recordingMessage.element.remove();
                    this.recordingMessage = null;
                }
                if (data.content) {
                    // 如果有 asr_partial 创建的消息框，用最终结果更新它；否则新增消息
                    if (this.currentResponseElement && this.currentResponseElement.type === 'asr') {
                        this.currentResponseElement.element.querySelector('.message-content').textContent = data.content;
                        this.currentResponseElement.type = 'user';  // 标记为最终 user 消息
                    } else {
                        this.addMessage('user', data.content);
                    }
                    this._updatePwBubble('user', data.content, false);
                }
                this.currentResponseElement = null;
                break;

            case 'llm_thinking': {
                this._updatePwBubble('ai', '思考中...', true);
                this._live2dReact('thinking');  // 清表情 + 思考动作
                // Live2D 思考中 —— 显示动画气泡
                if (!this.live2dThinkingElement) {
                    const mc = document.getElementById('chatMessages');
                    const td = document.createElement('div');
                    td.className = 'message assistant';
                    td.innerHTML = `
                        <div class="message-avatar">👒</div>
                        <div class="openclaw-thinking">
                            <span>Live2D 思考中</span>
                            <span class="dot-flashing">
                                <span></span><span></span><span></span>
                            </span>
                        </div>`;
                    mc.appendChild(td);
                    this.live2dThinkingElement = td;
                    this.scrollToBottom();
                }
                break;
            }

            case 'llm_chunk':
                // LLM 流式片段 —— 先移除思考气泡
                if (this.live2dThinkingElement) {
                    this.live2dThinkingElement.remove();
                    this.live2dThinkingElement = null;
                }
                if (this.currentResponseElement && this.currentResponseElement.type === 'assistant') {
                    this.currentResponseElement.element.querySelector('.message-content').textContent += data.content;
                    this.scrollToBottom();
                } else {
                    this.currentResponseElement = this.addMessage('assistant', data.content);
                    // LLM 开始输出，播放思考动作
                    if (this.live2dController) {
                        this.live2dController.playThinking();
                    }
                }
                this._updatePwBubble('ai',
                    this.currentResponseElement
                        ? this.currentResponseElement.element.querySelector('.message-content').textContent
                        : data.content, true);
                break;

            case 'llm_complete':
                // LLM 完成（此时音频队列可能已在播放）
                console.log('AI 回复完成:', data.content);
                if (data.content) this._updatePwBubble('ai', data.content, false);
                else this._updatePwBubble('ai', this._pwAiText, false);  // 停止流式光标
                // Live2D: 根据回复内容触发表情
                this._live2dReact('llm_complete', data.content || this._pwAiText);
                this.currentResponseElement = null;
                break;

            case 'tts_audio':
                // TTS 音频数据（流式流水线）—立即入队播放
                this.enqueueAudio(data);
                break;

            case 'openclaw_thinking': {
                // OpenClaw 正在处理中 —— 显示动画气泡
                const messagesContainer = document.getElementById('chatMessages');
                const thinkDiv = document.createElement('div');
                thinkDiv.className = 'message openclaw';
                thinkDiv.innerHTML = `
                    <div class="message-avatar">👾</div>
                    <div class="openclaw-thinking">
                        <span>OpenClaw 处理中</span>
                        <span class="dot-flashing">
                            <span></span><span></span><span></span>
                        </span>
                    </div>`;
                messagesContainer.appendChild(thinkDiv);
                this.openclawThinkingElement = thinkDiv;
                this.scrollToBottom();
                break;
            }

            case 'openclaw_message': {
                // OpenClaw 返回结果 —— 替换或新增消息
                if (this.openclawThinkingElement) {
                    this.openclawThinkingElement.remove();
                    this.openclawThinkingElement = null;
                }
                this.addMessage('openclaw', data.content);
                break;
            }

            case 'tts_complete':
                // 服务端全部 TTS 完成 —— 等调度队列播完后再更新状态
                this._waitForScheduledAudioEnd();
                break;

            case 'chat_response':
                // 端到端实时语音的模型回复流（实时文本）
                if (this.live2dThinkingElement) {
                    this.live2dThinkingElement.remove();
                    this.live2dThinkingElement = null;
                }
                const content = data.data && data.data.content !== undefined ? data.data.content : (data.content || '');
                if (this.currentResponseElement && this.currentResponseElement.type === 'assistant') {
                    this.currentResponseElement.element.querySelector('.message-content').textContent += content;
                    this.scrollToBottom();
                } else {
                    this.currentResponseElement = this.addMessage('assistant', content);
                    this.currentResponseElement.type = 'assistant';
                }
                break;

            case 'chat_complete':
                // 端到端实时语音对话完成
                this._live2dReact('llm_complete', this._pwAiText);
                this.currentResponseElement = null;
                break;

            case 'realtime_session_started':
                console.log('[WebSocket] 实时语音会话已启动, dialog_id:', data.dialog_id);
                break;

            case 'realtime_session_finished':
                console.log('[WebSocket] 实时语音会话已结束');
                // 停止实时录音
                if (this.realtimeRecording) {
                    // 停止定时器
                    if (this.realtimeTimer) {
                        clearInterval(this.realtimeTimer);
                        this.realtimeTimer = null;
                    }
                    this.realtimeRecording = false;

                    const recordBtn = document.getElementById('recordBtn');
                    if (recordBtn) recordBtn.classList.remove('recording');

                    const voicePrompt = document.getElementById('voicePrompt');
                    if (voicePrompt) {
                        voicePrompt.textContent = '按住录音按钮开始说话';
                        voicePrompt.style.background = '#f1f5f9';
                        voicePrompt.style.color = '#64748b';
                    }
                }
                break;

            case 'tts_sentence_start':
                // TTS 句子开始（端到端模式）
                break;

            case 'tts_sentence_end':
                // TTS 句子结束（端到端模式）
                break;
        }
    }

    addMessage(type, content) {
        const messagesContainer = document.getElementById('chatMessages');
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${type}`;

        let avatar = '';
        if (type === 'assistant') {
            avatar = '👒';  // Live2D AI 助手
        } else if (type === 'user') {
            avatar = '🕶️';  // 用户
        } else if (type === 'openclaw') {
            avatar = '👾';  // OpenClaw
        }

        messageDiv.innerHTML = `
            <div class="message-avatar">${avatar}</div>
            <div class="message-content">${this.escapeHtml(content)}</div>
        `;

        messagesContainer.appendChild(messageDiv);
        this.scrollToBottom();

        // 同步纯白模式气泡（文字输入发送时走此路径）
        if (type === 'user') this._updatePwBubble('user', content, false);
        else if (type === 'assistant') this._updatePwBubble('ai', content, false);

        return {
            element: messageDiv,
            type: type
        };
    }

    updateStatus(message) {
        const statusText = document.querySelector('.status-text');
        if (statusText) {
            statusText.textContent = message;
        }
    }

    showError(message) {
        const messagesContainer = document.getElementById('chatMessages');
        const errorDiv = document.createElement('div');
        errorDiv.className = 'message system';
        errorDiv.innerHTML = `
            <div class="message-content" style="color: #ef4444;">
                ⚠️ ${this.escapeHtml(message)}
            </div>
        `;
        messagesContainer.appendChild(errorDiv);
        this.scrollToBottom();
    }

    scrollToBottom() {
        const messagesContainer = document.getElementById('chatMessages');
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    playAudio(base64Audio) {
        try {
            const audioData = this.base64ToArrayBuffer(base64Audio);
            const audioBlob = new Blob([audioData], { type: 'audio/wav' });
            const audioUrl = URL.createObjectURL(audioBlob);
            const audio = new Audio(audioUrl);
            audio.play();
        } catch (error) {
            console.error('播放音频失败:', error);
        }
    }

    /**
     * 将音频加入播放队列。
     * Live2D 可用时走 WebAudio 无缝调度路径（帧到即 decode + schedule，零间隙）；
     * 否则退回 FIFO sequential 路径（onended 链）。
     * @param {string|Object} audioPayload - base64 编码的音频数据，或带格式信息的对象
     */
    enqueueAudio(audioPayload) {
        if (!this.ttsPlaying) {
            this._onTtsPlaybackStart();
        }

        const payload = typeof audioPayload === 'string'
            ? { content: audioPayload, format: 'mp3' }
            : (audioPayload || {});
        const base64Audio = payload.content;
        const audioFormat = payload.format || 'mp3';

        if (!base64Audio) {
            return;
        }

        if (this.live2dController && this.live2dController.ready) {
            // 无缝调度路径：并发 decode，保序调度
            const sessionId = this._sessionId;

            // 确保 AudioContext 存在（将停用的 context 恒等候以后处理）
            if (!this.live2dController.audioContext) {
                this.live2dController.audioContext =
                    new (window.AudioContext || window.webkitAudioContext)();
            }
            const ctx = this.live2dController.audioContext;
            if (ctx.state === 'suspended') ctx.resume().catch(() => {});

            // 立即开始 decode/转换（多块并发进行）
            const arrayBuffer = this.base64ToArrayBuffer(base64Audio);
            const decodePromise = this._decodeAudioPayload(arrayBuffer, audioFormat, payload, ctx)
                .catch(e => { console.warn('[TTS] decode 失败', e); return null; });

            this._decodedQueue.push({ sessionId, decodePromise });

            // 启动调度器（如未运行）
            if (!this._schedulerRunning) {
                this._runDecodeScheduler();
            }
        } else {
            // 降级串行路径
            this.audioQueue.push({ payload, sessionId: this._sessionId });
            if (!this._audioPlaying) {
                this._playNextInQueue();
            }
        }
    }

    async _decodeAudioPayload(arrayBuffer, format, payload, audioContext) {
        if (format === 'pcm_s16le') {
            const sampleRate = payload.sample_rate || 24000;
            const channels = payload.channels || 1;
            return this._pcm16ToAudioBuffer(arrayBuffer, sampleRate, channels, audioContext);
        }
        return audioContext.decodeAudioData(arrayBuffer.slice(0));
    }

    _pcm16ToAudioBuffer(arrayBuffer, sampleRate, channels = 1, audioContext = null) {
        const bytesPerSample = 2;
        const frameCount = Math.floor(arrayBuffer.byteLength / (bytesPerSample * channels));
        const ctx = audioContext || this.live2dController?.audioContext;
        if (!ctx || frameCount <= 0) {
            return null;
        }

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
     * 按入队顺序依次 await 解码结果并将其调度到 WebAudio 时间轴。
     * decode 是并发进行的（在 enqueueAudio 中就已开始），此处仅保证调度顺序。
     */
    async _runDecodeScheduler() {
        this._schedulerRunning = true;
        while (this._decodedQueue.length > 0) {
            const { sessionId, decodePromise } = this._decodedQueue.shift();
            const audioBuffer = await decodePromise;  // 等 decode 完成（多块并行，但顺序消费）

            // 丢弃旧请求音频或 decode 失败的块
            if (!audioBuffer || this._sessionId !== sessionId) continue;

            const isFirst = !this._audioPlaying;
            this._audioPlaying = true;
            this.live2dController.scheduleAudioBuffer(audioBuffer);
            if (isFirst) this.live2dController.playTalking();
        }
        this._schedulerRunning = false;
    }

    /**
     * 等待 WebAudio 调度队列中的所有音频播放完毕，然后停止 LipSync 并更新状态。
     * 适用于 tts_complete 到来时（此时调度队列可能还未播完）。
     */
    _waitForScheduledAudioEnd() {
        const lc = this.live2dController;
        const sessionId = this._sessionId;

        if (!this._hasActiveTtsPlayback()) {
            this._finalizeTtsPlayback(sessionId);
            return;
        }

        if (!lc || !lc.audioContext) {
            const checkFallback = () => {
                if (sessionId !== this._sessionId) return;
                if (this._hasActiveTtsPlayback()) {
                    setTimeout(checkFallback, 50);
                    return;
                }
                this._finalizeTtsPlayback(sessionId);
            };
            checkFallback();
            return;
        }

        const ctx = lc.audioContext;

        const check = () => {
            if (this._sessionId !== sessionId) return; // 被打断，不再处理
            const remaining = lc._nextScheduledTime - ctx.currentTime;
            if (remaining <= 0.05) {
                // 所有调度音频已播完
                lc.stopLipSync();
                lc.isSpeaking = false;
                this._finalizeTtsPlayback(sessionId);
            } else {
                // 每 50ms 检查一次，或剩余时间更短时更精确地唤醒
                setTimeout(check, Math.min(50, Math.max(16, (remaining - 0.04) * 1000)));
            }
        };
        check();
    }

    /**
     * 取队首音频播放，播放结束后自动递归调用自身，直到队列为空。
     * sessionId 不匹配时跳过（丢弃来自旧请求的残留音频）。
     */
    _playNextInQueue() {
        // 跳过已失效（旧 session）的音频
        while (this.audioQueue.length > 0 && this.audioQueue[0].sessionId !== this._sessionId) {
            this.audioQueue.shift();
        }
        if (this.audioQueue.length === 0) {
            this._audioPlaying = false;
            return;
        }

        const isFirst = !this._audioPlaying;
        this._audioPlaying = true;
        const { payload } = this.audioQueue.shift();
        const currentSession = this._sessionId;

        // 首条音频时触发说话动作
        if (isFirst && this.live2dController) {
            this.live2dController.playTalking();
        }

        const onEnded = () => {
            // 仅当 session 未切换时继续，否则直接清理
            if (this._sessionId !== currentSession) {
                this._audioPlaying = false;
                return;
            }
            this._playNextInQueue();
        };

        if (this.live2dController && this.live2dController.ready) {
            this.live2dController.playAudioWithLipSync(payload.content, onEnded, payload);
        } else {
            this._playAudioWithCallback(payload, onEnded);
        }
    }

    /**
     * 立即中断当前 TTS 播放并清空队列。
     * 由 VAD 说话开始时触发，让用户可随时打断 AI 说话。
     * 无缝调度路径：递增 sessionId 使后续 _scheduleAudioDirect 的 decode 结果全部丢弃，
     * 并调用 stopCurrentAudio() 停止当前正在播放的 source + 重置 _nextScheduledTime。
     */
    _interruptTts() {
        if (!this._hasActiveTtsPlayback()) return;
        console.log('[TTS] 被用户语音打断');
        this._live2dReact('interrupted');  // 摇头 + 清除表情

        // 递增 sessionId 使所有已入队或正在 decode 的旧音频自动失效
        this._sessionId++;
        this.audioQueue = [];
        this._decodedQueue = [];
        this._audioPlaying = false;
        this.ttsPlaying = false;

        // 停止 Live2D AudioContext 中正在播放的 source，并重置调度时钟
        if (this.live2dController) {
            this.live2dController.stopCurrentAudio(); // 内部已 reset _nextScheduledTime
        }
        // 停止非 Live2D 路径播放的 HTML Audio
        if (this._currentHtmlAudio) {
            try { this._currentHtmlAudio.pause(); this._currentHtmlAudio.src = ''; } catch (_) {}
            this._currentHtmlAudio = null;
        }
    }

    /**
     * 播放音频并在结束时触发回调（不依赖 Live2D）。
     */
    _playAudioWithCallback(audioPayload, callback) {
        try {
            const payload = typeof audioPayload === 'string'
                ? { content: audioPayload, format: 'mp3' }
                : (audioPayload || {});
            const base64Audio = payload.content;
            const format = payload.format || 'mp3';
            const audioData = this.base64ToArrayBuffer(base64Audio);
            const audioBlob = format === 'pcm_s16le'
                ? this._createWavBlobFromPcm16(audioData, payload.sample_rate || 24000, payload.channels || 1)
                : new Blob([audioData], { type: 'audio/mpeg' });
            const audioUrl = URL.createObjectURL(audioBlob);
            const audio = new Audio(audioUrl);
            this._currentHtmlAudio = audio;
            const done = () => {
                this._currentHtmlAudio = null;
                URL.revokeObjectURL(audioUrl);
                callback();
            };
            audio.addEventListener('ended', done, { once: true });
            audio.addEventListener('error', done, { once: true });
            audio.play().catch(() => done());
        } catch (error) {
            console.error('播放音频失败:', error);
            callback();
        }
    }

    _createWavBlobFromPcm16(arrayBuffer, sampleRate, channels = 1) {
        const bytesPerSample = 2;
        const blockAlign = channels * bytesPerSample;
        const byteRate = sampleRate * blockAlign;
        const pcmBytes = arrayBuffer.byteLength;
        const wavBuffer = new ArrayBuffer(44 + pcmBytes);
        const view = new DataView(wavBuffer);

        const writeString = (offset, value) => {
            for (let i = 0; i < value.length; i++) {
                view.setUint8(offset + i, value.charCodeAt(i));
            }
        };

        writeString(0, 'RIFF');
        view.setUint32(4, 36 + pcmBytes, true);
        writeString(8, 'WAVE');
        writeString(12, 'fmt ');
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true);
        view.setUint16(22, channels, true);
        view.setUint32(24, sampleRate, true);
        view.setUint32(28, byteRate, true);
        view.setUint16(32, blockAlign, true);
        view.setUint16(34, 16, true);
        writeString(36, 'data');
        view.setUint32(40, pcmBytes, true);
        new Uint8Array(wavBuffer, 44).set(new Uint8Array(arrayBuffer));

        return new Blob([wavBuffer], { type: 'audio/wav' });
    }

    playTtsAudio() {
        // 合并所有音频块
        const combinedBase64 = this.ttsAudioBuffer.join('');

        // 使用 Live2D 控制器播放（带嘴形同步）
        if (this.live2dController && this.live2dController.ready) {
            this.live2dController.playAudioWithLipSync(combinedBase64);
        } else {
            // 回退到普通播放
            this.playAudio(combinedBase64);
        }

        // 清空缓冲区
        this.ttsAudioBuffer = [];
    }

    base64ToArrayBuffer(base64) {
        const binaryString = window.atob(base64);
        const bytes = new Uint8Array(binaryString.length);
        for (let i = 0; i < binaryString.length; i++) {
            bytes[i] = binaryString.charCodeAt(i);
        }
        return bytes.buffer;
    }

    // ========== 设置管理 ==========

    /**
     * 初始化设置：从后端加载当前设置并填充下拉框和滑块
     */
    async initSettings() {
        try {
            const resp = await fetch('/api/settings');
            if (!resp.ok) throw new Error('加载设置失败');
            const data = await resp.json();
            this._settingsData = data;
            this._populateSettingsUI(data);
        } catch (e) {
            console.warn('[Settings] 加载设置失败:', e);
        }
    }

    /**
     * 用后端数据填充设置界面
     */
    _populateSettingsUI(data) {
        const select = document.getElementById('personalitySelect');
        select.innerHTML = '';
        (data.personalities || []).forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = `${p.name}`;
            opt.dataset.description = p.description || '';
            if (p.id === data.current_personality) opt.selected = true;
            select.appendChild(opt);
        });

        const speed = data.speed_ratio ?? 1.0;
        document.getElementById('speedSlider').value = speed;
        document.getElementById('speedBadge').textContent = `${speed.toFixed(1)}x`;

        const vadThresh = data.vad_speech_threshold ?? 0.030;
        document.getElementById('vadThreshSlider').value = vadThresh;
        document.getElementById('vadThreshBadge').textContent = vadThresh.toFixed(3);
        // 立即应用到当前录音器
        if (this.audioRecorder) {
            this.audioRecorder.options.vadSpeechThreshold = vadThresh;
            this.audioRecorder.options.vadSilenceThreshold = parseFloat((vadThresh * 0.7).toFixed(4));
        }

        this._updatePersonalityHint(data.current_personality);

        // 填充 Live2D 模型选择
        const live2dModelSelect = document.getElementById('live2dModelSelect');
        if (live2dModelSelect) {
            const savedModel = localStorage.getItem('live2d_model') || 'Hiyori';
            live2dModelSelect.value = savedModel;
        }

        // 填充 Live2D 鼠标跟随开关
        const mouseFollowEl = document.getElementById('live2dMouseFollow');
        if (mouseFollowEl) {
            const mouseFollow = localStorage.getItem('live2d_mouse_follow') === 'true';
            mouseFollowEl.checked = mouseFollow;
        }

        // 填充 OpenClaw 设置
        const oc = data.openclaw || {};
        const ocEnabledEl = document.getElementById('openclawEnabled');
        const ocUrlEl = document.getElementById('openclawUrl');
        const ocTokenEl = document.getElementById('openclawToken');
        const ocNameEl = document.getElementById('openclawAgentName');
        const ocTimeoutEl = document.getElementById('openclawTimeout');
        const vadInterruptTtsEl = document.getElementById('vadInterruptTts');
        if (ocEnabledEl) ocEnabledEl.checked = !!oc.enabled;
        if (ocUrlEl) ocUrlEl.value = oc.base_url || 'http://127.0.0.1:18789';
        if (ocTokenEl) ocTokenEl.value = oc.token || '';
        if (ocNameEl) ocNameEl.value = oc.agent_name || 'Live2D';
        if (ocTimeoutEl) ocTimeoutEl.value = oc.timeout_seconds || 60;
        if (vadInterruptTtsEl) vadInterruptTtsEl.checked = !!data.vad_interrupt_tts;
    }

    _updatePersonalityHint(personalityId) {
        const select = document.getElementById('personalitySelect');
        const opt = select.querySelector(`option[value="${personalityId}"]`);
        const hint = document.getElementById('personalityHint');
        if (hint) {
            hint.textContent = opt ? (opt.dataset.description || '') : '';
        }
    }

    openSettings() {
        const modal = document.getElementById('settingsModal');
        // 重新填充以反映当前后端状态
        if (this._settingsData) {
            this._populateSettingsUI(this._settingsData);
        }
        modal.classList.add('active');
    }

    closeSettings() {
        document.getElementById('settingsModal').classList.remove('active');
    }

    async saveSettings() {
        const personalityId = document.getElementById('personalitySelect').value;
        const speedRatio = parseFloat(document.getElementById('speedSlider').value);
        const vadSpeechThreshold = parseFloat(document.getElementById('vadThreshSlider').value);
        const vadInterruptTts = document.getElementById('vadInterruptTts')?.checked ?? false;

        // 获取 Live2D 模型选择
        const live2dModelSelect = document.getElementById('live2dModelSelect');
        const selectedModel = live2dModelSelect ? live2dModelSelect.value : 'Hiyori';
        const currentModel = localStorage.getItem('live2d_model') || 'Hiyori';

        const modelChanged = selectedModel !== currentModel;
        if (modelChanged) {
            localStorage.setItem('live2d_model', selectedModel);
        }

        // 处理 Live2D 鼠标跟随开关
        const mouseFollowEl = document.getElementById('live2dMouseFollow');
        const mouseFollow = mouseFollowEl ? mouseFollowEl.checked : false;
        const currentMouseFollow = localStorage.getItem('live2d_mouse_follow') === 'true';
        
        if (mouseFollow !== currentMouseFollow) {
            localStorage.setItem('live2d_mouse_follow', mouseFollow);
            if (window.live2dController) {
                if (mouseFollow) {
                    window.live2dController.enableMouseFollow();
                    this.updateStatus('已开启鼠标跟随');
                } else {
                    window.live2dController.disableMouseFollow();
                    this.updateStatus('已关闭鼠标跟随');
                }
            }
        }

        // 读取 OpenClaw 设置
        const openclaw = {
            enabled: document.getElementById('openclawEnabled')?.checked ?? false,
            base_url: (document.getElementById('openclawUrl')?.value || 'http://127.0.0.1:18789').trim(),
            token: (document.getElementById('openclawToken')?.value || '').trim(),
            agent_name: (document.getElementById('openclawAgentName')?.value || 'Live2D').trim(),
            timeout_seconds: parseInt(document.getElementById('openclawTimeout')?.value || '60', 10),
        };

        try {
            const resp = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    personality_id: personalityId,
                    speed_ratio: speedRatio,
                    vad_speech_threshold: vadSpeechThreshold,
                    vad_interrupt_tts: vadInterruptTts,
                    openclaw: openclaw,
                })
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.detail || '保存失败');
            }
            const result = await resp.json();
            this._settingsData = result.settings;

            // 立即应用 VAD 阈值到当前录音器
            if (this.audioRecorder) {
                this.audioRecorder.options.vadSpeechThreshold = vadSpeechThreshold;
                this.audioRecorder.options.vadSilenceThreshold = parseFloat((vadSpeechThreshold * 0.7).toFixed(4));
            }

            this.closeSettings();

            // 找到选中的性格名称给用户提示
            const p = (result.settings.personalities || []).find(x => x.id === personalityId);
            const name = p ? p.name : personalityId;
            const ocStatus = openclaw.enabled ? ' | OpenClaw ✅' : '';
            const modelName = selectedModel === 'Hiyori' ? 'Hiyori' : '茜茜';
            const refreshReason = modelChanged ? ` | 模型：${modelName}` : '';
            this.updateStatus(`已保存：${name}${ocStatus}${refreshReason}，正在刷新页面...`);
            setTimeout(() => window.location.reload(), 300);
        } catch (e) {
            console.error('[Settings] 保存设置失败:', e);
            this.showError(`保存设置失败：${e.message}`);
        }
    }

    /**
     * 根据事件名触发对应的 Live2D 动作。
     * @param {'listening'|'user_send'|'thinking'|'llm_complete'|'tts_end'|'interrupted'} event
     * @param {string} [text] - LLM 回复文本（llm_complete 时使用）
     */
    _live2dReact(event, text = '') {
        const lc = this.live2dController;
        if (!lc || !lc.ready) return;

        switch (event) {
            case 'listening':
                // 用户正在说话 → 聆听状态（m02疑惑 / m07惊讶 / m09生气 随机）
                lc.playListening();
                break;

            case 'user_send':
                // 文字发送 / 语音识别结束 → 同聆听状态
                lc.playListening();
                break;

            case 'thinking':
                // LLM 思考中 → 思考状态（m03思考 / m04担忧 / m07惊讶 / m10担忧 随机）
                lc.playThinking();
                break;

            case 'llm_complete': {
                // 分析回复情绪 → 播放对应复合组
                const group = this._detectEmotion(text);
                lc.playRandom(group);
                break;
            }

            case 'tts_end':
                // 语音播放结束 → 2s 后恢复随机 Idle
                setTimeout(() => {
                    if (!lc.isSpeaking) lc.playRandomIdle();
                }, 2000);
                break;

            case 'interrupted':
                // TTS 被用户语音打断 → 回到思考状态
                lc.playThinking();
                break;
        }
    }

    /**
     * 分析 LLM 回复文本，返回对应的复合动作组名称。
     * @returns {'Happy'|'Worried'|'surprised'|'angry'|'Thinking'|'Idle'}
     */
    _detectEmotion(text) {
        if (!text) return 'Idle';
        const t = text.toLowerCase();

        const rules = [
            {
                group: 'Happy',
                patterns: ['哈哈','开心','高兴','喜欢','太好了','不错','好厉害','加油','棒','厉害',
                           '没问题','当然','好的','很高兴','很开心','嘿嘿','嘻嘻','搞定','放心',
                           '包在我身上','那还用说','当然了']
            },
            {
                group: 'surprised',
                patterns: ['真的吗','怎么回事','什么！','诶','哇','没想到','居然','原来如此',
                           '！？','?!','哦？','不会吧']
            },
            {
                group: 'Worried',
                patterns: ['难过','悲伤','遗憾','可惜','没办法','失败','很抱歉','对不起','抱歉',
                           '不好意思','担心','害怕','糟糕','出错']
            },
            {
                group: 'angry',
                patterns: ['不行','烦人','讨厌','生气','愤怒','不可以']
            },
            {
                group: 'Thinking',
                patterns: ['嗯','让我想想','这个嘛','不过','但是','虽然','需要考虑']
            },
        ];

        for (const rule of rules) {
            if (rule.patterns.some(p => t.includes(p.toLowerCase()))) {
                return rule.group;
            }
        }
        return 'Idle';
    }

    destroy() {
        // Live2D 由 autoload.js 管理，无需手动销毁

        // 销毁 Live2D 控制器
        if (this.live2dController) {
            this.live2dController.destroy();
        }

        // 停止 VAD 监听
        this.stopVadListening();

        if (this.audioRecorder) {
            this.audioRecorder.destroy();
        }

        if (this.chatManager) {
            this.chatManager.disconnect();
        }

        if (this.recordingInterval) {
            clearInterval(this.recordingInterval);
        }
    }
}

// 初始化应用
const app = new App();
window.addEventListener('DOMContentLoaded', () => {
    app.init();
});

// 页面卸载时清理
window.addEventListener('beforeunload', () => {
    app.destroy();
});
