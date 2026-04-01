<template>
  <div class="sv-page">
    <section v-if="panelVisible" class="sv-card" :class="{ 'subtitle-mode': subtitleEnabled }">

      <main class="sv-main">
        <template v-if="!subtitleEnabled">
          <div class="avatar-wrap">
            <img class="avatar-img" src="/logo.jpg" alt="Assistant avatar">
          </div>
          <div class="dots" aria-hidden="true">
            <span></span>
            <span></span>
            <span></span>
          </div>
          <p class="state-text">{{ displayStateText }}</p>
          <p v-if="inCall && partialText" class="assist-tip">{{ partialText }}</p>
          <p v-else-if="inCall && agentBusy && busyText" class="assist-tip">{{ busyText }}</p>
        </template>

        <template v-else>
          <div class="avatar-wrap small">
            <img class="avatar-img" src="/logo.jpg" alt="Assistant avatar">
          </div>
          <section ref="msgList" class="subtitle-panel" aria-live="polite">
            <template v-if="hasSubtitleContent">
              <div class="msg-list">
                <div v-for="msg in messages" :key="msg.id" :class="['msg-row', msg.role]">
                  <div class="msg-bubble">{{ msg.text }}</div>
                </div>
                <div v-if="partialText" class="msg-row user pending">
                  <div class="msg-bubble">{{ partialText }}</div>
                </div>
                <div v-if="pendingReply" class="msg-row assistant pending">
                  <div class="msg-bubble">{{ pendingReply }}</div>
                </div>
              </div>
            </template>
            <template v-else>
              <div class="subtitle-placeholder">
                <div class="quote-mark">&#10078;</div>
                <p>??????????</p>
              </div>
            </template>
          </section>
        </template>
      </main>

      <footer class="sv-actions">
        <button class="action-btn" aria-label="???" @click="onMinimize">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 5h18a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-7l-2 2-2-2H3a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zm0 2v9h18V7H3z"></path></svg>
        </button>
        <button class="action-btn" :class="{ active: subtitleEnabled }" aria-label="??" @click="toggleSubtitle">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h16a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H9l-5 4v-4H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zm4 5a1.25 1.25 0 1 0 0 .001V9zm4 0a1.25 1.25 0 1 0 0 .001V9zm4 0a1.25 1.25 0 1 0 0 .001V9z"></path></svg>
        </button>
        <button class="action-btn mic" :class="{ active: inCall }" aria-label="???" @click="toggleMic">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15a4 4 0 0 0 4-4V7a4 4 0 1 0-8 0v4a4 4 0 0 0 4 4zm-6-4a1 1 0 1 1 2 0 4 4 0 1 0 8 0 1 1 0 1 1 2 0 6 6 0 0 1-5 5.91V20h3a1 1 0 1 1 0 2H8a1 1 0 1 1 0-2h3v-2.09A6 6 0 0 1 6 11z"></path></svg>
        </button>
        <button class="action-btn end" aria-label="??" @click="onHangup">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 15.5c-2-2-5-3.5-9-3.5s-7 1.5-9 3.5a1 1 0 0 0-.1 1.3l1.9 2.4a1 1 0 0 0 1.4.2l2.8-2.2a1 1 0 0 0 .3-1.1l-.3-.8c.8-.1 1.7-.3 3-.3s2.2.2 3 .3l-.3.8a1 1 0 0 0 .3 1.1l2.8 2.2a1 1 0 0 0 1.4-.2l1.9-2.4a1 1 0 0 0-.1-1.3z"></path></svg>
        </button>
      </footer>
    </section>

    <button v-if="miniBarVisible" class="mini-bar" @click="restorePanel">
      <img class="mini-avatar" src="/logo.jpg" alt="Assistant avatar">
      <span class="mini-title">??? {{ callDurationText }}</span>
      <span class="mini-hang" @click.stop="onHangup">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 15.5c-2-2-5-3.5-9-3.5s-7 1.5-9 3.5a1 1 0 0 0-.1 1.3l1.9 2.4a1 1 0 0 0 1.4.2l2.8-2.2a1 1 0 0 0 .3-1.1l-.3-.8c.8-.1 1.7-.3 3-.3s2.2.2 3 .3l-.3.8a1 1 0 0 0 .3 1.1l2.8 2.2a1 1 0 0 0 1.4-.2l1.9-2.4a1 1 0 0 0-.1-1.3z"></path></svg>
      </span>
    </button>
  </div>
</template>

<script>
export default {
  name: 'SimpleVoice',
  data () {
    return {
      ws: null,
      wsReady: false,
      reconnTimer: null,

      inCall: false,
      panelVisible: true,
      subtitleEnabled: false,

      stream: null,
      audioCtx: null,
      sourceNode: null,
      processor: null,
      inputSampleRate: 48000,

      audioSampleRate: 16000,
      audioChannels: 1,
      bitsPerSample: 16,
      frameMs: 40,
      frameSamples: 640,
      frameBytes: 1280,
      targetBitrate: 256000,
      pcmRing: new Int16Array(0),
      serverAudioProfile: null,
      audioProfileWarnings: [],

      isSpeaking: false,
      silenceCount: 0,
      speechCount: 0,
      rmsLevel: 0,
      vadThreshold: 0.012,
      silenceFramesNeeded: 38,
      minSpeechFrames: 3,
      preBuf: [],
      preBufMax: 10,

      messages: [],
      partialText: '',
      pendingReply: '',
      agentBusy: false,
      busyText: '',

      audioQueue: [],
      isPlaying: false,
      audioEl: null,

      callStartedAt: 0,
      nowTick: Date.now(),
      callTimer: null
    }
  },
  computed: {
    volHeight () {
      return Math.min(20, Math.max(2, this.rmsLevel * 800))
    },
    hasSubtitleContent () {
      return Boolean(this.messages.length || this.partialText || this.pendingReply)
    },
    displayStateText () {
      if (!this.inCall) return '?????'
      if (this.agentBusy && this.busyText) return this.busyText
      if (this.isSpeaking) return '????...'
      return '???...'
    },
    miniBarVisible () {
      return this.inCall && !this.panelVisible
    },
    callDurationText () {
      if (!this.callStartedAt) return '00:00'
      const sec = Math.max(0, Math.floor((this.nowTick - this.callStartedAt) / 1000))
      const mm = String(Math.floor(sec / 60)).padStart(2, '0')
      const ss = String(sec % 60).padStart(2, '0')
      return `${mm}:${ss}`
    }
  },
  mounted () {
    this.audioEl = new Audio()
    this.audioEl.preload = 'auto'
    this.connectWs()
  },
  beforeDestroy () {
    this.teardownAudio()
    this.stopAudio()
    this.stopCallTimer()
    if (this.reconnTimer) clearTimeout(this.reconnTimer)
    if (this.ws) { try { this.ws.close() } catch (e) {} }
  },
  methods: {
    wait (ms) {
      return new Promise(resolve => setTimeout(resolve, ms))
    },
    async ensureWsReady (timeoutMs = 3500) {
      const start = Date.now()
      while (Date.now() - start < timeoutMs) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) return true
        if (!this.ws || this.ws.readyState >= WebSocket.CLOSING) this.connectWs()
        await this.wait(60)
      }
      return Boolean(this.ws && this.ws.readyState === WebSocket.OPEN)
    },

    connectWs () {
      if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      this.ws = new WebSocket(`${proto}://${window.location.hostname}:8001/ws/simple`)
      this.ws.binaryType = 'arraybuffer'
      this.ws.onopen = () => {
        this.wsReady = true
        this.sendJson({ type: 'profile' })
      }
      this.ws.onclose = () => {
        this.wsReady = false
        this.reconnTimer = setTimeout(() => this.connectWs(), 2000)
      }
      this.ws.onerror = () => {}
      this.ws.onmessage = (e) => this.onWsMsg(e)
    },
    sendJson (obj) {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false
      this.ws.send(JSON.stringify(obj))
      return true
    },
    sendBinary (buf) {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false
      this.ws.send(buf)
      return true
    },
    onWsMsg (e) {
      if (typeof e.data !== 'string') return
      let ev
      try { ev = JSON.parse(e.data) } catch (_) { return }

      if (ev.type === 'audio_profile') {
        this.serverAudioProfile = ev
        return
      }
      if (ev.type === 'audio_profile_check') {
        this.audioProfileWarnings = Array.isArray(ev.warnings) ? ev.warnings : []
        return
      }
      if (ev.type === 'state') {
        if (ev.state === 'thinking') {
          this.agentBusy = true
          this.busyText = '????...'
        } else if (ev.state === 'speaking') {
          this.agentBusy = true
          this.busyText = '????...'
        } else if (ev.state === 'idle' || ev.state === 'listening') {
          this.agentBusy = false
          this.busyText = ''
        }
        return
      }
      if (ev.type === 'asr_partial') {
        this.partialText = (ev.text || '').trim()
        this.scrollBottom()
        return
      }
      if (ev.type === 'asr') {
        const text = (ev.text || '').trim()
        this.partialText = ''
        if (text) this.pushMsg('user', text)
        return
      }
      if (ev.type === 'llm_delta') {
        this.pendingReply += (ev.text || '')
        this.scrollBottom()
        return
      }
      if (ev.type === 'llm_done') {
        if (this.pendingReply.trim()) this.pushMsg('assistant', this.pendingReply.trim())
        this.pendingReply = ''
        return
      }
      if (ev.type === 'tts_audio') {
        if (ev.audio_b64) {
          this.audioQueue.push({ b64: ev.audio_b64, mime: ev.mime || 'audio/wav' })
          this.playNext()
        }
        return
      }
      if (ev.type === 'error') {
        this.busyText = ev.message || '??'
        this.agentBusy = true
        setTimeout(() => { this.agentBusy = false }, 3000)
      }
    },

    startCallTimer () {
      this.stopCallTimer()
      this.callStartedAt = Date.now()
      this.nowTick = this.callStartedAt
      this.callTimer = setInterval(() => { this.nowTick = Date.now() }, 1000)
    },
    stopCallTimer () {
      if (this.callTimer) {
        clearInterval(this.callTimer)
        this.callTimer = null
      }
      this.callStartedAt = 0
    },

    async startCall () {
      if (this.inCall) return
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        this.busyText = '?????????'
        this.agentBusy = true
        return
      }

      const wsOk = await this.ensureWsReady(3500)
      if (!wsOk) {
        this.busyText = '??????? (WS)'
        this.agentBusy = true
        return
      }

      try {
        this.stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: { ideal: this.audioChannels },
            sampleRate: { ideal: this.audioSampleRate },
            sampleSize: { ideal: this.bitsPerSample },
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true
          }
        })
      } catch (e) {
        this.busyText = '???????: ' + (e.name || e.message)
        this.agentBusy = true
        return
      }

      this.frameSamples = Math.max(160, Math.round(this.audioSampleRate * this.frameMs / 1000))
      this.frameBytes = this.frameSamples * this.audioChannels * (this.bitsPerSample / 8)
      this.targetBitrate = this.audioSampleRate * this.audioChannels * this.bitsPerSample
      this.pcmRing = new Int16Array(0)

      const AudioCtx = window.AudioContext || window.webkitAudioContext
      this.audioCtx = new AudioCtx()
      this.inputSampleRate = this.audioCtx.sampleRate
      this.sourceNode = this.audioCtx.createMediaStreamSource(this.stream)
      this.processor = this.audioCtx.createScriptProcessor(2048, 1, 1)

      this.isSpeaking = false
      this.silenceCount = 0
      this.speechCount = 0

      this.processor.onaudioprocess = (e) => {
        if (!this.inCall) return
        const input = e.inputBuffer.getChannelData(0)
        const rms = this.calcRms(input)
        this.rmsLevel = rms

        const ds = this.downsample(input, this.inputSampleRate, this.audioSampleRate)
        const int16Chunk = this.floatsToInt16(ds)
        this.appendPcmRing(int16Chunk)

        while (true) {
          const frame = this.popPcmFrame()
          if (!frame) break

          if (this.agentBusy || this.isPlaying) {
            if (rms > this.vadThreshold) {
              this.speechCount += 1
              if (this.speechCount >= this.minSpeechFrames && !this.isSpeaking) {
                this.onInterruptByVoice(this.preBuf)
                this.preBuf = []
              }
            } else {
              this.speechCount = 0
              this.preBuf.push(frame)
              if (this.preBuf.length > this.preBufMax) this.preBuf.shift()
            }
            if (this.isSpeaking) this.sendBinary(frame.buffer)
            continue
          }

          if (rms > this.vadThreshold) {
            this.speechCount += 1
            this.silenceCount = 0
            if (!this.isSpeaking && this.speechCount >= this.minSpeechFrames) {
              this.onSpeechStart(this.preBuf)
              this.preBuf = []
            }
          } else if (this.isSpeaking) {
            this.silenceCount += 1
            if (this.silenceCount >= this.silenceFramesNeeded) {
              this.onSpeechEnd()
              return
            }
          } else {
            this.speechCount = 0
          }

          if (this.isSpeaking) {
            this.sendBinary(frame.buffer)
          } else {
            this.preBuf.push(frame)
            if (this.preBuf.length > this.preBufMax) this.preBuf.shift()
          }
        }
      }

      this.sourceNode.connect(this.processor)
      this.processor.connect(this.audioCtx.destination)

      this.inCall = true
      this.startCallTimer()
      this.panelVisible = true
    },
    buildAudioProfile () {
      return {
        transport: 'websocket',
        encoding: 'pcm_s16le',
        sample_rate: this.audioSampleRate,
        sample_rate_hz: this.audioSampleRate,
        channels: this.audioChannels,
        bits_per_sample: this.bitsPerSample,
        frame_ms: this.frameMs,
        frame_samples: this.frameSamples,
        frame_bytes: this.frameBytes,
        bitrate_bps: this.targetBitrate
      }
    },
    onSpeechStart (preBufferedFrames) {
      this.isSpeaking = true
      this.partialText = ''
      let preAudio = ''
      if (preBufferedFrames && preBufferedFrames.length > 0) {
        let totalLen = 0
        for (let i = 0; i < preBufferedFrames.length; i++) totalLen += preBufferedFrames[i].length
        const merged = new Int16Array(totalLen)
        let off = 0
        for (let i = 0; i < preBufferedFrames.length; i++) {
          merged.set(preBufferedFrames[i], off)
          off += preBufferedFrames[i].length
        }
        const bytes = new Uint8Array(merged.buffer)
        let binary = ''
        for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
        preAudio = btoa(binary)
      }
      this.sendJson({ type: 'speech_start', pre_audio: preAudio, audio_profile: this.buildAudioProfile() })
    },
    onInterruptByVoice (preBufferedFrames) {
      this.stopAudio()
      this.pendingReply = ''
      this.partialText = ''
      this.agentBusy = false
      this.sendJson({ type: 'interrupt' })
      this.$nextTick(() => {
        this.onSpeechStart(preBufferedFrames)
      })
    },
    onSpeechEnd () {
      this.isSpeaking = false
      this.silenceCount = 0
      this.speechCount = 0
      this.sendJson({ type: 'speech_end' })
    },
    endCall () {
      if (this.isSpeaking) this.sendJson({ type: 'speech_end' })
      this.inCall = false
      this.isSpeaking = false
      this.preBuf = []
      this.pcmRing = new Int16Array(0)
      this.teardownAudio()
      this.stopAudio()
      this.stopCallTimer()
      this.sendJson({ type: 'interrupt' })
      this.agentBusy = false
      this.pendingReply = ''
      this.partialText = ''
    },
    teardownAudio () {
      try { if (this.processor) this.processor.disconnect() } catch (e) {}
      try { if (this.sourceNode) this.sourceNode.disconnect() } catch (e) {}
      try { if (this.audioCtx) this.audioCtx.close() } catch (e) {}
      try { if (this.stream) this.stream.getTracks().forEach(t => t.stop()) } catch (e) {}
      this.processor = null
      this.sourceNode = null
      this.audioCtx = null
      this.stream = null
      this.pcmRing = new Int16Array(0)
    },

    onMinimize () {
      if (this.inCall) this.panelVisible = false
    },
    restorePanel () {
      this.panelVisible = true
      this.scrollBottom()
    },
    toggleSubtitle () {
      this.subtitleEnabled = !this.subtitleEnabled
      this.panelVisible = true
      this.scrollBottom()
    },
    async toggleMic () {
      if (this.inCall) {
        this.endCall()
      } else {
        await this.startCall()
      }
    },
    onHangup () {
      this.endCall()
      this.panelVisible = false
      if (this.$router) {
        this.$router.push('/Home/MainDia/new').catch(() => {})
      }
    },

    floatsToInt16 (floats) {
      const int16 = new Int16Array(floats.length)
      for (let i = 0; i < floats.length; i++) {
        const s = Math.max(-1, Math.min(1, floats[i]))
        int16[i] = s < 0 ? Math.round(s * 32768) : Math.round(s * 32767)
      }
      return int16
    },
    appendPcmRing (chunk) {
      if (!chunk || !chunk.length) return
      const merged = new Int16Array(this.pcmRing.length + chunk.length)
      merged.set(this.pcmRing, 0)
      merged.set(chunk, this.pcmRing.length)
      this.pcmRing = merged
    },
    popPcmFrame () {
      if (this.pcmRing.length < this.frameSamples) return null
      const out = this.pcmRing.slice(0, this.frameSamples)
      this.pcmRing = this.pcmRing.slice(this.frameSamples)
      return out
    },
    calcRms (buf) {
      let sum = 0
      for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i]
      return Math.sqrt(sum / buf.length)
    },
    downsample (input, inRate, outRate) {
      if (outRate >= inRate) return input
      const ratio = inRate / outRate
      const outLen = Math.floor(input.length / ratio)
      const out = new Float32Array(outLen)
      for (let i = 0; i < outLen; i++) {
        const pos = i * ratio
        const idx = Math.floor(pos)
        const frac = pos - idx
        const next = Math.min(idx + 1, input.length - 1)
        out[i] = input[idx] * (1 - frac) + input[next] * frac
      }
      return out
    },

    interrupt () {
      this.sendJson({ type: 'interrupt' })
      this.pendingReply = ''
      this.partialText = ''
      this.stopAudio()
    },

    pushMsg (role, text) {
      this.messages.push({ id: Date.now() + '_' + Math.random(), role, text })
      if (this.messages.length > 100) this.messages.shift()
      this.scrollBottom()
    },
    scrollBottom () {
      this.$nextTick(() => {
        const el = this.$refs.msgList
        if (el) el.scrollTop = el.scrollHeight
      })
    },

    playNext () {
      if (this.isPlaying) return
      const item = this.audioQueue.shift()
      if (!item) return
      this.isPlaying = true
      this.audioEl.src = `data:${item.mime};base64,${item.b64}`
      this.audioEl.onended = () => {
        this.isPlaying = false
        if (this.audioQueue.length > 0) {
          this.playNext()
        } else {
          this.agentBusy = false
        }
      }
      this.audioEl.onerror = () => {
        this.isPlaying = false
        if (this.audioQueue.length > 0) {
          this.playNext()
        } else {
          this.agentBusy = false
        }
      }
      this.audioEl.play().catch(() => {
        this.isPlaying = false
        this.playNext()
      })
    },
    stopAudio () {
      this.audioQueue = []
      this.isPlaying = false
      if (this.audioEl) {
        try { this.audioEl.pause() } catch (e) {}
        this.audioEl.src = ''
      }
    }
  }
}
</script>

<style scoped>
.sv-page {
  width: 100%;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: radial-gradient(circle at 30% 20%, #f8f8f9 0, #ececef 48%, #e6e7ea 100%);
  padding: 20px;
  box-sizing: border-box;
}

.sv-card {
  width: min(94vw, 520px);
  height: min(90vh, 760px);
  background: #f3f3f4;
  border-radius: 22px;
  box-shadow: 0 14px 34px rgba(27, 31, 40, 0.22);
  border: 1px solid #e9e9ec;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sv-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 26px;
  padding: 10px 26px 0;
}

.avatar-wrap {
  width: 208px;
  height: 208px;
  border-radius: 50%;
  overflow: hidden;
  background: #bfd3ec;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.7);
}

.avatar-wrap.small {
  width: 56px;
  height: 56px;
  margin-top: -8px;
}

.avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.dots {
  display: flex;
  gap: 8px;
}

.dots span {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #3d4148;
}

.state-text {
  margin: 0;
  font-size: 42px;
  color: #7f838a;
  letter-spacing: 0.5px;
}

.assist-tip {
  margin: 0;
  font-size: 16px;
  color: #8c9097;
  max-width: 82%;
  text-align: center;
  line-height: 1.4;
}

.subtitle-panel {
  width: 100%;
  max-width: 420px;
  flex: 1;
  background: rgba(255, 255, 255, 0.45);
  border-radius: 16px;
  padding: 14px;
  overflow-y: auto;
  margin-bottom: 14px;
}

.msg-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.msg-row {
  display: flex;
}

.msg-row.user {
  justify-content: flex-end;
}

.msg-row.assistant {
  justify-content: flex-start;
}

.msg-bubble {
  max-width: 80%;
  padding: 10px 13px;
  border-radius: 14px;
  font-size: 15px;
  line-height: 1.5;
  color: #333;
  background: #efefef;
  word-break: break-word;
}

.msg-row.user .msg-bubble {
  background: #dedede;
}

.msg-row.pending .msg-bubble {
  opacity: 0.65;
}

.subtitle-placeholder {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #a0a3a8;
  gap: 10px;
}

.quote-mark {
  width: 54px;
  height: 54px;
  border-radius: 12px;
  background: #ececef;
  color: #b9bcc2;
  display: grid;
  place-items: center;
  font-size: 38px;
}

.subtitle-placeholder p {
  margin: 0;
}

.sv-actions {
  height: 86px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 26px;
  padding-bottom: 10px;
}

.action-btn {
  width: 38px;
  height: 38px;
  border: 0;
  background: transparent;
  color: #84878d;
  cursor: pointer;
  border-radius: 50%;
  display: grid;
  place-items: center;
}

.action-btn svg {
  width: 26px;
  height: 26px;
  fill: currentColor;
}

.action-btn:hover {
  background: rgba(0, 0, 0, 0.05);
}

.action-btn.active {
  color: #2d2f35;
}

.action-btn.mic.active {
  color: #26a343;
}

.action-btn.end {
  color: #ff4747;
}

.mini-bar {
  margin-top: 14px;
  height: 86px;
  width: min(94vw, 430px);
  border: 0;
  border-radius: 999px;
  background: #efefef;
  box-shadow: 0 10px 24px rgba(20, 24, 30, 0.16);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  cursor: pointer;
}

.mini-avatar {
  width: 46px;
  height: 46px;
  border-radius: 50%;
}

.mini-title {
  font-size: 44px;
  color: #6c7077;
  letter-spacing: 0.3px;
}

.mini-hang {
  width: 36px;
  height: 36px;
  color: #ff4c4c;
  display: grid;
  place-items: center;
}

.mini-hang svg {
  width: 28px;
  height: 28px;
  fill: currentColor;
}

@media (max-width: 720px) {
  .sv-card {
    width: min(96vw, 380px);
    height: min(90vh, 660px);
    border-radius: 18px;
  }

  .avatar-wrap {
    width: 168px;
    height: 168px;
  }

  .state-text {
    font-size: 34px;
  }

  .sv-actions {
    gap: 20px;
  }

  .mini-title {
    font-size: 34px;
  }
}
</style>
