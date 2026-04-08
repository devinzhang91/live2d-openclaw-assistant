import test from 'node:test';
import assert from 'node:assert/strict';

import controllerModule from './realtime-voice-controller.js';

const { RealtimeVoiceController } = controllerModule;

test('entering voice mode in realtime starts listening immediately', () => {
    const controller = new RealtimeVoiceController();

    const result = controller.enterVoiceMode({
        audioAvailable: true,
        realtimeEnabled: true
    });

    assert.equal(result.startListening, true);
    assert.equal(controller.listening, true);
});

test('speech boundaries open and close one realtime turn', () => {
    const controller = new RealtimeVoiceController();
    controller.enterVoiceMode({ audioAvailable: true, realtimeEnabled: true });

    const started = controller.handleSpeechStart();
    const chunk = controller.handleAudioChunk('chunk-1');
    const ended = controller.handleSpeechEnd();

    assert.equal(started.startSession, true);
    assert.equal(chunk.sendAudio, true);
    assert.equal(chunk.payload, 'chunk-1');
    assert.equal(ended.endSession, true);
    assert.equal(controller.sessionActive, false);
});

test('leaving voice mode aborts the active realtime session and stops listening', () => {
    const controller = new RealtimeVoiceController();
    controller.enterVoiceMode({ audioAvailable: true, realtimeEnabled: true });
    controller.handleSpeechStart();

    const result = controller.leaveVoiceMode();

    assert.equal(result.stopListening, true);
    assert.equal(result.abortSession, true);
    assert.equal(controller.listening, false);
    assert.equal(controller.sessionActive, false);
});

test('session finished event should not clear an active recording turn', () => {
    const controller = new RealtimeVoiceController();
    controller.enterVoiceMode({ audioAvailable: true, realtimeEnabled: true });
    controller.handleSpeechStart();

    const result = controller.handleSessionFinished();

    assert.equal(result.ignored, true);
    assert.equal(controller.sessionActive, true);
});
