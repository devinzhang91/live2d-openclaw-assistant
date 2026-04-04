/**
 * 聊天管理
 */
class ChatManager {
    constructor(wsUrl) {
        this.wsUrl = wsUrl;
        this.ws = null;
        this.connected = false;
        this.onMessage = null;
        this.onStatus = null;
        this.onError = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
    }

    connect() {
        try {
            this.ws = new WebSocket(this.wsUrl);

            this.ws.onopen = () => {
                this.connected = true;
                this.reconnectAttempts = 0;
                console.log('WebSocket 已连接');
                this.emitStatus('已连接');
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleMessage(data);
                } catch (error) {
                    console.error('解析消息失败:', error);
                }
            };

            this.ws.onclose = () => {
                this.connected = false;
                console.log('WebSocket 已断开');
                this.emitStatus('已断开');
                this.reconnect();
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket 错误:', error);
                this.emitError('连接错误');
            };

        } catch (error) {
            console.error('创建 WebSocket 失败:', error);
            this.emitError('无法建立连接');
        }
    }

    reconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error('达到最大重连次数');
            this.emitError('无法连接到服务器');
            return;
        }

        this.reconnectAttempts++;
        const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);

        console.log(`${delay/1000}秒后尝试重连...`);
        this.emitStatus(`正在重连 (${this.reconnectAttempts}/${this.maxReconnectAttempts})`);

        setTimeout(() => {
            this.connect();
        }, delay);
    }

    sendMessage(message) {
        if (!this.connected || !this.ws) {
            this.emitError('未连接到服务器');
            return;
        }

        try {
            this.ws.send(JSON.stringify(message));
        } catch (error) {
            console.error('发送消息失败:', error);
            this.emitError('发送消息失败');
        }
    }

    sendText(text) {
        this.sendMessage({
            type: 'text',
            content: text
        });
    }

    startAudioStream() {
        this.sendMessage({
            type: 'audio_start'
        });
    }

    sendAudioChunk(audioData) {
        this.sendMessage({
            type: 'audio',
            content: audioData
        });
    }

    endAudioStream() {
        this.sendMessage({
            type: 'audio_end'
        });
    }

    sendAudioStop() {
        if (!this.connected) return;
        this.ws.send(JSON.stringify({ type: 'audio_stop' }));
    }

    handleMessage(data) {
        // suppress noisy high-frequency events from the console
        if (data.type !== 'llm_chunk' && data.type !== 'tts_audio' && data.type !== 'asr_chunk') {
            console.log('收到消息:', data);
        }

        switch (data.type) {
            case 'status':
                if (this.onStatus) {
                    this.onStatus(data.message);
                }
                break;

            case 'error':
                if (this.onError) {
                    this.onError(data.message);
                }
                break;

            case 'asr_chunk':
            case 'asr_partial':
            case 'asr_complete':
            case 'llm_chunk':
            case 'llm_complete':
            case 'tts_audio':
            case 'tts_complete':
            case 'llm_thinking':
            case 'openclaw_thinking':
            case 'openclaw_message':
                if (this.onMessage) {
                    this.onMessage(data);
                }
                break;

            default:
                console.warn('未知消息类型:', data.type);
        }
    }

    emitStatus(message) {
        if (this.onStatus) {
            this.onStatus(message);
        }
    }

    emitError(message) {
        if (this.onError) {
            this.onError(message);
        }
    }

    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.connected = false;
    }
}
