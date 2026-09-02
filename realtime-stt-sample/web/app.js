'use strict';

const $ = (id) => document.getElementById(id);

const els = {
  start: $('btn-start'),
  stop: $('btn-stop'),
  clear: $('btn-clear'),
  interimToggle: $('interim-toggle'),
  meter: $('meter'),
  vadDot: $('vad-dot'),
  conn: $('conn'),
  transcript: $('transcript'),
  log: $('log'),
  costNote: $('cost-note'),
};

const state = {
  ws: null,
  ctx: null,
  node: null,
  stream: null,
  running: false,
  finals: [],
  interim: '',
  t0: 0,
};

// ---------------------------------------------------------------- 렌더링

function renderTranscript() {
  if (!state.finals.length && !state.interim) {
    els.transcript.innerHTML = '<p class="placeholder">녹음을 시작하면 여기에 표시됩니다.</p>';
    return;
  }
  const parts = state.finals.map((t) => `<p class="final">${escapeHtml(t)}</p>`);
  if (state.interim) parts.push(`<p class="interim">${escapeHtml(state.interim)}</p>`);
  els.transcript.innerHTML = parts.join('');
  els.transcript.scrollTop = els.transcript.scrollHeight;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function renderStats(st) {
  if (!st) return;
  $('s-final').textContent = st.final_calls;
  $('s-interim').textContent = st.interim_calls;
  $('s-lat').textContent = `${st.latency_avg_ms} ms`;
  $('s-p95').textContent = `${st.latency_p95_ms} ms`;
  $('s-tok').textContent = st.total_tokens.toLocaleString();
  $('s-ftok').textContent = st.final_tokens.toLocaleString();
  $('s-audio').textContent = `${st.audio_sent_s} s`;
  $('s-drop').textContent = st.dropped_segments;

  if (st.interim_multiplier > 1) {
    els.costNote.innerHTML =
      `잠정 표시 때문에 확정 경로만 돌렸을 때의 <strong>${st.interim_multiplier}배</strong> 토큰을 쓰고 있다 ` +
      `(총 ${st.total_tokens.toLocaleString()} / 확정만 ${st.final_tokens.toLocaleString()}). ` +
      `추정 ${st.krw.toFixed(4)}원 — 단가 단위는 미확인이라 참고치다.`;
  }
}

function log(kind, text) {
  const el = document.createElement('div');
  el.className = `t-${kind}`;
  const t = state.t0 ? ((performance.now() - state.t0) / 1000).toFixed(2) : '0.00';
  el.textContent = `${t.padStart(6)}s [${kind}] ${text}`;
  els.log.appendChild(el);
  els.log.scrollTop = els.log.scrollHeight;
}

function setConn(text, cls) {
  els.conn.textContent = text;
  els.conn.className = `badge${cls ? ' ' + cls : ''}`;
}

// ---------------------------------------------------------------- 이벤트

function onEvent(ev) {
  switch (ev.type) {
    case 'ready':
      setConn('연결됨', 'on');
      break;

    case 'vad':
      els.vadDot.classList.toggle('active', ev.state === 'speech');
      if (ev.state === 'idle') {
        // 발화가 끝나면 잠정 문구를 지운다. 곧 확정본이 온다.
        state.interim = '';
        renderTranscript();
      }
      log('vad', `${ev.state} utt=${ev.utt}`);
      break;

    case 'interim':
      state.interim = ev.text;
      renderTranscript();
      renderStats(ev.stats);
      log('interim', `(${ev.audio_s}s ${ev.latency_ms}ms ${ev.tokens}tok) ${ev.text}`);
      break;

    case 'final':
      state.interim = '';
      state.finals.push(ev.text);
      renderTranscript();
      renderStats(ev.stats);
      log('final', `(${ev.reason} ${ev.audio_s}s ${ev.latency_ms}ms ${ev.tokens}tok) ${ev.text}`);
      break;

    case 'dropped':
      log('dropped', `${ev.reason} (${ev.audio_s}s flatness=${ev.flatness})`);
      break;

    case 'warn':
      // 잠정 전사 실패 등. 화면 상태는 유지하고 로그로만 알린다.
      log('dropped', `${ev.where}: ${ev.message}`);
      break;

    case 'error':
      log('error', `${ev.where}: ${ev.message}`);
      setConn('오류', 'err');
      break;

    case 'done':
      renderStats(ev.stats);
      log('final', '세션 종료');
      break;
  }
}

// ---------------------------------------------------------------- 오디오

async function start() {
  if (state.running) return;
  els.start.disabled = true;

  try {
    state.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
  } catch (err) {
    log('error', `마이크 접근 실패: ${err}`);
    setConn('마이크 거부됨', 'err');
    els.start.disabled = false;
    return;
  }

  const cfg = await fetch('/api/config').then((r) => r.json());

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  // APP_ACCESS_KEY 를 쓰는 배포에서는 쿠키가 붙지만, 쿠키가 막힌 환경을 대비해
  // 주소창의 ?key= 를 그대로 넘긴다.
  const key = new URLSearchParams(location.search).get('key');
  const qs = key ? `?key=${encodeURIComponent(key)}` : '';
  const ws = new WebSocket(`${proto}//${location.host}/ws${qs}`);
  ws.binaryType = 'arraybuffer';
  state.ws = ws;
  state.t0 = performance.now();

  ws.onmessage = (e) => onEvent(JSON.parse(e.data));
  ws.onclose = () => { setConn('연결 끊김'); stop(); };
  ws.onerror = () => setConn('연결 오류', 'err');

  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    setTimeout(() => reject(new Error('WebSocket 연결 시간 초과')), 5000);
  });

  ws.send(JSON.stringify({ type: 'config', interim: els.interimToggle.checked }));

  state.ctx = new AudioContext();
  await state.ctx.audioWorklet.addModule('/static/pcm-worklet.js');

  const src = state.ctx.createMediaStreamSource(state.stream);
  state.node = new AudioWorkletNode(state.ctx, 'pcm-worklet', {
    numberOfInputs: 1,
    numberOfOutputs: 0,
    processorOptions: {
      targetRate: cfg.sample_rate,
      frameSamples: (cfg.sample_rate * cfg.frame_ms) / 1000,
    },
  });

  state.node.port.onmessage = (e) => {
    const { pcm, level } = e.data;
    els.meter.style.width = `${Math.min(100, level * 140)}%`;
    if (ws.readyState !== WebSocket.OPEN) return;
    // 네트워크가 밀리면 프레임을 버린다. 쌓아두면 지연만 늘어난다.
    if (ws.bufferedAmount > 1 << 18) return;
    ws.send(pcm);
  };

  src.connect(state.node);

  state.running = true;
  els.stop.disabled = false;
  els.start.textContent = '녹음 중';
  els.start.classList.add('recording');
  log('vad', `시작 — ctx ${state.ctx.sampleRate}Hz → ${cfg.sample_rate}Hz`);
}

async function stop() {
  if (!state.running) return;
  state.running = false;

  if (state.node) { state.node.port.onmessage = null; state.node.disconnect(); state.node = null; }
  if (state.ctx) { await state.ctx.close().catch(() => {}); state.ctx = null; }
  if (state.stream) { state.stream.getTracks().forEach((t) => t.stop()); state.stream = null; }

  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ type: 'stop' }));
  }

  els.meter.style.width = '0%';
  els.vadDot.classList.remove('active');
  els.start.disabled = false;
  els.stop.disabled = true;
  els.start.textContent = '녹음 시작';
  els.start.classList.remove('recording');
}

// ---------------------------------------------------------------- 바인딩

els.start.addEventListener('click', start);
els.stop.addEventListener('click', stop);
els.clear.addEventListener('click', () => {
  state.finals = [];
  state.interim = '';
  els.log.innerHTML = '';
  renderTranscript();
});
els.interimToggle.addEventListener('change', () => {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ type: 'config', interim: els.interimToggle.checked }));
  }
});

renderTranscript();
