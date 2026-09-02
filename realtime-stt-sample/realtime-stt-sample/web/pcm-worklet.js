/**
 * 마이크 입력을 16kHz mono int16 raw PCM 프레임으로 바꿔 메인 스레드로 넘긴다.
 *
 * MediaRecorder 를 쓰지 않는 이유: webm/opus 는 두 번째 chunk 부터 EBML 헤더가 없어
 * 단독 파일로 디코딩되지 않는다. 그대로 잘라 올리면 400 이나 빈 텍스트가 돌아온다.
 * raw PCM 을 받아 서버에서 구간마다 WAV 헤더를 붙이면 모든 chunk 가 독립 재생 가능하고
 * ffmpeg 도 필요 없다.
 */
class PcmWorklet extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const opts = options.processorOptions || {};
    this.targetRate = opts.targetRate || 16000;
    this.frameSamples = opts.frameSamples || 320; // 20ms @ 16kHz
    // AudioContext 의 실제 샘플레이트(보통 48000)에서 목표 레이트로 내린다.
    this.ratio = sampleRate / this.targetRate;
    this.pos = 0;
    this.tail = new Float32Array(0);
    this.out = new Int16Array(this.frameSamples);
    this.outLen = 0;
    this.peak = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0 || !input[0]) return true;
    const block = input[0];

    // 직전 블록에서 남은 샘플을 앞에 붙여야 보간이 블록 경계에서 끊기지 않는다.
    const buf = new Float32Array(this.tail.length + block.length);
    buf.set(this.tail, 0);
    buf.set(block, this.tail.length);

    while (this.pos + 1 < buf.length) {
      const i = Math.floor(this.pos);
      const frac = this.pos - i;
      let s = buf[i] + (buf[i + 1] - buf[i]) * frac;
      if (s > 1) s = 1;
      else if (s < -1) s = -1;

      const a = Math.abs(s);
      if (a > this.peak) this.peak = a;

      this.out[this.outLen++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (this.outLen === this.frameSamples) {
        const frame = this.out.slice();
        this.port.postMessage({ pcm: frame.buffer, level: this.peak }, [frame.buffer]);
        this.outLen = 0;
        this.peak = 0;
      }
      this.pos += this.ratio;
    }

    const consumed = Math.floor(this.pos);
    this.tail = buf.slice(consumed);
    this.pos -= consumed;
    return true;
  }
}

registerProcessor('pcm-worklet', PcmWorklet);
