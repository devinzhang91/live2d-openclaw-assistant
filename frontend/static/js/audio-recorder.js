/**
 * 音频录制器 - 支持流式发送 & 前端振幅 VAD
 */
class AudioRecorder {
    constructor(options = {}) {
        this.options = {
            sampleRate: 16000,
            channelCount: 1,
            chunkDuration: 100, // 每个块 100ms
            // VAD 参数
            vadSpeechThreshold: 0.015,   // 说话起始振幅阈值
            vadSilenceThreshold: 0.010,  // 静音判定振幅阈值（略低，迟滞）
            vadSilenceMs: 2500,          // 静音多少毫秒后认为说话结束
            vadPrerollMs: 300,           // 说话开始前保留的预滚帧（ms）
            vadMinSpeechMs: 300,         // 最短有效语音时长（ms），过短丢弃
            vadMaxSpeechMs: 60000,       // 单段最长语音（ms），超过则强制结束
            vadStreamChunkMs: 500,       // 流式推送间隔（ms）：每累积这么多语音就推送一次
            ...options
        };
        this.mediaRecorder = null;
        this.stream = null;
        this.isRecording = false;
        this.onDataChunk = null;
        this.onStop = null;
        this.recordingInterval = null;
        this.audioContext = null;
        this.scriptProcessor = null;
        this.source = null;

        // VAD 相关
        this._vadSource = null;
        this._vadProcessor = null;
        this._vadActive = false;
        this._vadState = 'idle';          // 'idle' | 'speaking'
        this._vadPrerollBuf = [];         // 预滚环形缓冲（Float32Array[])
        this._vadSpeechBuf = [];          // 正在积累的语音帧
        this._vadSilenceSamples = 0;      // 连续静音样本计数
        this._vadSpeechSamples = 0;       // 本次语音累计样本数
        this._vadSilenceThreshSamples = 0;// 样本数阈值（by option）
        this._vadPrerollMaxFrames = 0;    // 预滚最大帧数

        /** VAD 回调 */
        this.onVadSpeechStart = null;     // () => void  — 检测到说话开始
        this.onVadSpeechEnd = null;       // () => void  — 检测到说话结束（正在处理）
        /** 完整语音回调：收到完整语音片段的 WAV ArrayBuffer */
        this.onSpeechSegment = null;      // (wavArrayBuffer) => void  [已废弃，由 onAudioChunk 替代]
        this.onAudioChunk = null;          // 流式推送：(wavArrayBuffer) => void，说话期间每隔 vadStreamChunkMs 触发一次
    }

    async init() {
        try {
            // Check if mediaDevices is available
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                throw new Error(
                    '浏览器不支持麦克风访问。请确保：\n' +
                    '1. 使用 HTTPS 或 localhost 访问\n' +
                    '2. 允许浏览器访问麦克风\n' +
                    '3. 浏览器支持 Web Audio API'
                );
            }

            this.stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: this.options.sampleRate,
                    channelCount: this.options.channelCount,
                    echoCancellation: false,    // 关闭：防止 Chrome 把音频抹零
                    noiseSuppression: false,    // 关闭：Chrome 噪声抑制会把低振幅语音归零
                    autoGainControl: false      // 关闭：由后端 Silero VAD 自行处理
                }
            });

            // 创建 AudioContext 用于实时音频处理
            this.audioContext = new AudioContext({
                sampleRate: this.options.sampleRate
            });

            console.log('音频录制器初始化成功');
        } catch (error) {
            console.error('音频录制器初始化失败:', error);
            throw error;
        }
    }

    start() {
        if (!this.stream) {
            throw new Error('音频录制器未初始化');
        }

        if (this.isRecording) {
            console.warn('已经在录音中');
            return;
        }

        try {
            // 创建音频源
            this.source = this.audioContext.createMediaStreamSource(this.stream);

            // 创建脚本处理器（处理实时音频数据）
            const bufferSize = 4096;
            this.scriptProcessor = this.audioContext.createScriptProcessor(
                bufferSize,
                this.options.channelCount,
                this.options.channelCount
            );

            // 存储音频数据
            this.audioChunks = [];
            this.startTime = Date.now();

            // 处理音频数据
            this.scriptProcessor.onaudioprocess = (e) => {
                const inputData = e.inputBuffer;
                const audioData = this._convertAudioBufferToFloat32Array(inputData);

                // 存储音频数据
                this.audioChunks.push({
                    data: audioData,
                    timestamp: Date.now() - this.startTime
                });

                // 触发回调
                if (this.onDataChunk) {
                    const wavBuffer = this._float32ArrayToWav(audioData, inputData.sampleRate);
                    this.onDataChunk(wavBuffer);
                }
            };

            // 连接节点
            this.source.connect(this.scriptProcessor);
            this.scriptProcessor.connect(this.audioContext.destination);

            this.isRecording = true;
            console.log('开始录音（流式）');

        } catch (error) {
            console.error('开始录音失败:', error);
            throw error;
        }
    }

    stop() {
        if (!this.stream) {
            throw new Error('音频录制器未初始化');
        }

        if (!this.isRecording) {
            console.warn('未在录音中');
            return;
        }

        try {
            // 断开连接
            if (this.source) {
                this.source.disconnect();
            }
            if (this.scriptProcessor) {
                this.scriptProcessor.disconnect();
            }

            this.isRecording = false;
            console.log('停止录音');

            // 触发停止回调
            if (this.onStop) {
                // 合并所有音频数据
                const allAudioData = this._mergeAudioChunks(this.audioChunks);
                const wavBuffer = this._float32ArrayToWav(
                    allAudioData,
                    this.options.sampleRate
                );
                const audioBlob = new Blob([wavBuffer], { type: 'audio/wav' });
                this.onStop(audioBlob);
            }

            this.audioChunks = [];

        } catch (error) {
            console.error('停止录音失败:', error);
            this.isRecording = false;
        }
    }

    /**
     * 获取当前累积的音频数据（用于实时语音模式）
     * 返回 WAV 格式的 ArrayBuffer，会清空已累积的数据
     * @returns {ArrayBuffer|null} WAV 音频数据，没有数据时返回 null
     */
    getAudioData() {
        if (!this.audioChunks || this.audioChunks.length === 0) {
            return null;
        }
        // 合并所有累积的音频块
        const mergedData = this._mergeAudioChunks(this.audioChunks);
        const wavBuffer = this._float32ArrayToWav(mergedData, this.options.sampleRate);
        // 清空已发送的数据
        this.audioChunks = [];
        return wavBuffer;
    }

    _convertAudioBufferToFloat32Array(audioBuffer) {
        const numberOfChannels = audioBuffer.numberOfChannels;
        const length = audioBuffer.length;
        const result = new Float32Array(length);

        for (let i = 0; i < length; i++) {
            let sum = 0;
            for (let channel = 0; channel < numberOfChannels; channel++) {
                sum += audioBuffer.getChannelData(channel)[i];
            }
            result[i] = sum / numberOfChannels;
        }

        return result;
    }

    _mergeAudioChunks(chunks) {
        // 计算总长度
        const totalLength = chunks.reduce((sum, chunk) => sum + chunk.data.length, 0);
        const result = new Float32Array(totalLength);

        // 合并数据
        let offset = 0;
        for (const chunk of chunks) {
            result.set(chunk.data, offset);
            offset += chunk.data.length;
        }

        return result;
    }

    _float32ArrayToWav(audioData, sampleRate) {
        const numChannels = 1;
        const format = 1; // PCM
        const bitDepth = 16;

        const bytesPerSample = bitDepth / 8;
        const blockAlign = numChannels * bytesPerSample;

        const samples = audioData.length;
        const dataSize = samples * blockAlign;
        const bufferSize = 44 + dataSize;

        const arrayBuffer = new ArrayBuffer(bufferSize);
        const view = new DataView(arrayBuffer);

        // WAV 文件头
        const writeString = (offset, string) => {
            for (let i = 0; i < string.length; i++) {
                view.setUint8(offset + i, string.charCodeAt(i));
            }
        };

        writeString(0, 'RIFF');
        view.setUint32(4, bufferSize - 8, true);
        writeString(8, 'WAVE');
        writeString(12, 'fmt ');
        view.setUint32(16, 16, true);
        view.setUint16(20, format, true);
        view.setUint16(22, numChannels, true);
        view.setUint32(24, sampleRate, true);
        view.setUint32(28, sampleRate * blockAlign, true);
        view.setUint16(32, blockAlign, true);
        view.setUint16(34, bitDepth, true);
        writeString(36, 'data');
        view.setUint32(40, dataSize, true);

        // 写入音频数据
        let offset = 44;
        for (let i = 0; i < samples; i++) {
            const sample = Math.max(-1, Math.min(1, audioData[i]));
            const intSample = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
            view.setInt16(offset, intSample, true);
            offset += 2;
        }

        return arrayBuffer;
    }

    async convertToWav(audioBlob) {
        // 将 WebM 转换为 WAV
        const arrayBuffer = await audioBlob.arrayBuffer();
        const audioContext = new AudioContext({
            sampleRate: this.options.sampleRate
        });

        const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
        const wavBuffer = this._float32ArrayToWav(
            audioBuffer.getChannelData(0),
            audioBuffer.sampleRate
        );
        return wavBuffer;
    }

    // ====================== 前端振幅 VAD ======================

    /**
     * 启动 VAD 监听模式（前端振幅检测）。
     * 当检测到完整的语音片段后，调用 this.onSpeechSegment(wavArrayBuffer)。
     * 检测到语音开始调用 this.onVadSpeechStart()，结束调用 this.onVadSpeechEnd()。
     */
    startVAD() {
        if (this._vadActive) return;
        if (!this.stream) throw new Error('音频录制器未初始化，请先调用 init()');

        // 使用 AudioContext 的实际采样率（浏览器不一定遵守请求的 16000 Hz，
        // Chrome/macOS 通常给出 44100 或 48000）。WAV 头必须与实际数据匹配，
        // 后端会按需重采样到 16000 Hz。
        const sr = this.audioContext.sampleRate;
        console.log(`[VAD] AudioContext 实际采样率: ${sr} Hz`);
        const bufferSize = 4096;

        this._vadState = 'idle';
        this._vadPrerollBuf = [];       // 预滚帧（说话前保留）
        this._vadStreamBuf = [];        // 流式块缓冲（积累到 vadStreamChunkMs 后推送）
        this._vadStreamSamples = 0;     // 当前流式块已累积的 samples 数
        this._vadSpeechSamples = 0;     // 本段语音总 samples
        this._vadSilenceSamples = 0;
        this._vadSilenceThreshSamples = Math.floor(sr * this.options.vadSilenceMs / 1000);
        this._vadStreamChunkThresh = Math.floor(sr * this.options.vadStreamChunkMs / 1000);
        this._vadPrerollMaxFrames = Math.ceil(
            (this.options.vadPrerollMs / 1000) * sr / bufferSize
        ) + 1;

        this._vadSource = this.audioContext.createMediaStreamSource(this.stream);
        this._vadProcessor = this.audioContext.createScriptProcessor(
            bufferSize, this.options.channelCount, this.options.channelCount
        );

        this._vadProcessor.onaudioprocess = (e) => {
            if (!this._vadActive) return;

            const inputData = e.inputBuffer;
            const frame = this._convertAudioBufferToFloat32Array(inputData);
            const rms = this._calcRMS(frame);

            // ── 辅助：把 _vadStreamBuf 编码成 WAV 并通过 onAudioChunk 推送 ──
            const flushStreamChunk = () => {
                if (this._vadStreamBuf.length === 0) return;
                const total = this._vadStreamBuf.reduce((s, f) => s + f.length, 0);
                const merged = new Float32Array(total);
                let off = 0;
                for (const f of this._vadStreamBuf) { merged.set(f, off); off += f.length; }
                if (this.onAudioChunk) this.onAudioChunk(this._float32ArrayToWav(merged, sr));
                this._vadStreamBuf = [];
                this._vadStreamSamples = 0;
            };

            if (this._vadState === 'idle') {
                // 维护预滚缓冲（限制长度）
                this._vadPrerollBuf.push(frame);
                if (this._vadPrerollBuf.length > this._vadPrerollMaxFrames) {
                    this._vadPrerollBuf.shift();
                }

                if (rms > this.options.vadSpeechThreshold) {
                    // ── 说话开始 ──
                    this._vadState = 'speaking';
                    this._vadSilenceSamples = 0;
                    this._vadSpeechSamples = 0;
                    // 把预滚帧放入流式块缓冲
                    this._vadStreamBuf = [...this._vadPrerollBuf];
                    this._vadStreamSamples = this._vadPrerollBuf.reduce((s, f) => s + f.length, 0);
                    this._vadPrerollBuf = [];
                    if (this.onVadSpeechStart) this.onVadSpeechStart(); // → audio_start
                }

            } else { // speaking
                this._vadStreamBuf.push(frame);
                this._vadStreamSamples += frame.length;
                this._vadSpeechSamples += frame.length;

                // 每累积到 vadStreamChunkMs 就推送一次给后端
                if (this._vadStreamSamples >= this._vadStreamChunkThresh) {
                    flushStreamChunk(); // → audio chunk
                }

                // 超过最大单段时长 → 强制结束本段，开启新段
                const maxSamples = Math.floor(sr * this.options.vadMaxSpeechMs / 1000);
                if (maxSamples > 0 && this._vadSpeechSamples >= maxSamples) {
                    console.log(`[VAD] 达到最大单段时长 ${this.options.vadMaxSpeechMs}ms，强制结束`);
                    flushStreamChunk();
                    if (this.onVadSpeechEnd) this.onVadSpeechEnd();   // → audio_end
                    this._vadSpeechSamples = 0;
                    this._vadSilenceSamples = 0;
                    // 继续 speaking 状态，立即开启新段
                    if (this.onVadSpeechStart) this.onVadSpeechStart(); // → audio_start
                    return;
                }

                if (rms < this.options.vadSilenceThreshold) {
                    this._vadSilenceSamples += frame.length;
                    if (this._vadSilenceSamples >= this._vadSilenceThreshSamples) {
                        // ── 静音足够久 → 说话结束 ──
                        const minSamples = Math.floor(sr * this.options.vadMinSpeechMs / 1000);
                        if (this._vadSpeechSamples > minSamples) {
                            flushStreamChunk();                            // 推送最后一块 → audio chunk
                            if (this.onVadSpeechEnd) this.onVadSpeechEnd(); // → audio_end
                        }
                        // 无论是否够长，都重置状态
                        this._vadState = 'idle';
                        this._vadPrerollBuf = [];
                        this._vadStreamBuf = [];
                        this._vadStreamSamples = 0;
                        this._vadSpeechSamples = 0;
                        this._vadSilenceSamples = 0;
                    }
                } else {
                    // 有声重置静音计数
                    this._vadSilenceSamples = 0;
                }
            }
        };

        this._vadSource.connect(this._vadProcessor);
        this._vadProcessor.connect(this.audioContext.destination);
        this._vadActive = true;
        console.log('[VAD] 前端振幅 VAD 已启动');
    }

    /** 停止 VAD 监听 */
    stopVAD() {
        if (!this._vadActive) return;
        this._vadActive = false;

        if (this._vadSource) { this._vadSource.disconnect(); this._vadSource = null; }
        if (this._vadProcessor) { this._vadProcessor.disconnect(); this._vadProcessor = null; }

        this._vadState = 'idle';
        this._vadPrerollBuf = [];
        this._vadSpeechBuf = [];
        this._vadSilenceSamples = 0;
        this._vadSpeechSamples = 0;
        console.log('[VAD] 前端振幅 VAD 已停止');
    }

    /** 计算 RMS 振幅 */
    _calcRMS(frame) {
        let sum = 0;
        for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
        return Math.sqrt(sum / frame.length);
    }

    // ====================== 销毁 ======================

    destroy() {
        this.stopVAD();
        this.stop();

        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }

        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
        }

        this.mediaRecorder = null;
        console.log('音频录制器已销毁');
    }

    // 获取音频时长（秒）
    getDuration(audioBlob) {
        return new Promise((resolve) => {
            const audio = new Audio(URL.createObjectURL(audioBlob));
            audio.addEventListener('loadedmetadata', () => {
                resolve(audio.duration);
            });
        });
    }
}
