class RealtimeVoiceController {
    constructor() {
        this.listening = false;
        this.sessionActive = false;
    }

    enterVoiceMode({ audioAvailable, realtimeEnabled }) {
        const startListening = !!audioAvailable && !!realtimeEnabled && !this.listening;
        if (startListening) {
            this.listening = true;
        }

        return { startListening };
    }

    leaveVoiceMode() {
        const result = {
            stopListening: this.listening,
            abortSession: this.sessionActive
        };

        this.listening = false;
        this.sessionActive = false;

        return result;
    }

    handleSpeechStart() {
        if (!this.listening || this.sessionActive) {
            return { startSession: false };
        }

        this.sessionActive = true;
        return { startSession: true };
    }

    handleAudioChunk(payload) {
        if (!this.listening || !this.sessionActive || !payload) {
            return { sendAudio: false, payload: null };
        }

        return { sendAudio: true, payload };
    }

    handleSpeechEnd() {
        if (!this.sessionActive) {
            return { endSession: false };
        }

        this.sessionActive = false;
        return { endSession: true };
    }

    handleSessionFinished() {
        if (this.sessionActive) {
            return {
                hadActiveSession: true,
                continueListening: this.listening,
                ignored: true
            };
        }

        return {
            hadActiveSession: false,
            continueListening: this.listening,
            ignored: false
        };
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { RealtimeVoiceController };
}

if (typeof window !== 'undefined') {
    window.RealtimeVoiceController = RealtimeVoiceController;
}
