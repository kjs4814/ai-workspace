# RAG Suite 실시간 STT 샘플

`openai/whisper-large-v3` 로 실시간 음성 전사를 하는 최소 구현.
브라우저에서 마이크를 받아 WebSocket 으로 흘려보내고, 발화 단위로 확정 텍스트를
만들면서 그 사이에는 growing window 로 잠정 결과를 보여준다.

전제 하나를 먼저 짚고 간다. **이 API 는 스트리밍 API 가 아니다.**
`/v1/audio/transcriptions` 는 파일을 올리면 처리 후 JSON 을 한 번에 돌려주는
batch 엔드포인트다. SSE 도 WebSocket 도 없다. 그래서 "실시간" 은 오디오를 잘라
반복 호출하는 의사 스트리밍으로 만든다. 이 저장소의 설계는 전부 그 제약에서 나왔다.

---

## 실행

```bash
./setup.sh              # venv 생성 + 의존성 설치 + .env 준비
# .env 에 RAG_SUITE_BASE_URL / RAG_SUITE_TOKEN 채우기
./run.sh
```

http://127.0.0.1:8848 에서 `녹음 시작`.

토큰은 각자 kt cloud RAG Suite 콘솔에서 발급받은 것을 쓴다.
`.env` 는 gitignore 되어 있으니 커밋되지 않는다.

> 마이크는 보안 컨텍스트에서만 열린다. `127.0.0.1` 은 허용되지만 LAN IP 로 접속하면
> HTTPS 가 필요하다.

### 화면에서 볼 것

- **전사** — 확정(검정)과 잠정(회색 이탤릭, 왼쪽 파란 선)이 구분된다.
  말하는 중에 회색 글씨가 갱신되다가 확정되면 검정으로 대체된다.
- **레벨 미터와 VAD 점** — 초록이면 발화 감지 중. 꺼져 있으면 API 를 호출하지 않는 상태다.
- **측정값** — 호출 수, 지연, 토큰, 차단된 세그먼트. 잠정 표시로 인한 토큰 배율이 실시간으로 뜬다.
- **이벤트 로그** — `vad` / `interim` / `final` / `dropped` 가 시각과 함께 찍힌다.

`잠정 결과 표시` 체크박스를 껐다 켜보면 이 샘플의 핵심 트레이드오프가 그대로 보인다.
끄면 말이 끝날 때까지 화면이 비어 있다가 한 번에 뜨고, 켜면 실시간으로 따라오지만 토큰이 약 6배다.

조용한 곳에서 아무 말 없이 두면 VAD 점이 계속 꺼져 있고 호출도 0건이다.
무음 hallucination 방어가 도는 것을 눈으로 확인할 수 있다.

---

## 다른 사람에게 공유하기

이 서버는 **`.env` 에 든 토큰으로 API 를 호출한다.** 주소를 아는 사람은 누구나
그 토큰을 태울 수 있다는 뜻이다. 공유 방식에 따라 필요한 준비가 다르다.

### 압축파일이나 저장소로 전달 (권장)

각자 자기 토큰으로 로컬에서 돌리는 방식이다. 토큰을 나눠 갖지 않고, 과금도 각자 진다.

**폴더를 그냥 압축하면 안 된다.** 두 가지가 딸려간다.

- `.env` — 내 RAG Suite 토큰이 평문으로 들어간다
- `.venv` — 77MB 인데다 실행 파일 shebang 에 내 홈 경로가 박혀 있어 남의 PC 에서 깨진다

`make-dist.sh` 가 둘을 빼고 묶고, 묶은 뒤 토큰이 없는지 확인까지 한다.

```bash
./make-dist.sh              # realtime-stt-sample.zip (약 360KB)
```

받는 사람은 이렇게 한다.

```bash
unzip realtime-stt-sample.zip
cd realtime-stt-sample
./setup.sh                  # venv 생성 + 의존성 설치 + .env 준비
# .env 에 자기 RAG_SUITE_BASE_URL / RAG_SUITE_TOKEN 채우고
./run.sh                    # http://127.0.0.1:8848
```

토큰이 아직 없는 사람도 `./setup.sh && .venv/bin/python test_offline.py` 로
VAD·잡음 게이트·오디오 변환까지는 확인할 수 있다. API 호출이 없어 요금이 들지 않는다.
`samples/sample-female-calm.wav` 가 함께 들어 있어 마이크 없이도
`.venv/bin/python simulate.py` 로 파이프라인을 돌려볼 수 있다.

받는 쪽 요구사항은 **Python 3.10 이상**과 bash 다. macOS 와 Linux 는 그대로 되고,
Windows 는 WSL 을 쓰거나 `run.sh` 안의 uvicorn 명령을 직접 실행해야 한다.
브라우저는 AudioWorklet 을 지원하는 최신 Chrome / Edge / Safari 면 된다.

### 터널이나 배포로 공유

내 서버 주소를 그대로 넘기는 방식이라 **반드시 아래 둘을 켜야 한다.**
`.env` 에 넣으면 된다.

```bash
APP_ACCESS_KEY=아무거나-긴-문자열   # 없으면 페이지도 WebSocket 도 401
MAX_SESSION_TOKENS=50000           # 연결 1개당 토큰 상한
```

접속은 `https://호스트/?key=<값>` 형태로 한다. 첫 접속에서 쿠키가 발급되고
WebSocket 도 같은 키로만 열린다. 상한에 닿으면 그 연결의 전사가 멈춘다.
잠정 표시를 켠 상태에서 1분 발화가 대략 6,400 토큰이니 상한은 이 기준으로 잡으면 된다.

마이크는 HTTPS 에서만 열리므로 평문 HTTP 로 노출하면 동작하지 않는다.

두 값을 비워두면 게이트가 통째로 꺼진다. localhost 전용일 때만 그렇게 둔다.

### 마이크 없이 검증

```bash
.venv/bin/python test_offline.py                      # API 호출 없음, 요금 0
./run.sh &
.venv/bin/python ws_test.py                           # WS 포함 종단 검증
.venv/bin/python simulate.py <파일.wav> --pad 1.0     # Session 직접 구동
.venv/bin/python simulate.py <파일.wav> --no-interim  # 확정 경로만
```

---

## 설계

```
브라우저  AudioWorklet ── 48kHz Float32 → 16kHz mono int16 (선형보간)
             │            20ms 프레임 단위로 WS 바이너리 전송
             ▼
서버      EnergyVad ────── 무음 구간은 아예 올리지 않는다
             │
          spectral gate ── 잡음/순음 구간은 API 호출 전에 버린다
             │
             ├─ 잠정: 발화 시작부터 누적한 창을 재전사 (single-flight)
             └─ 확정: 발화 끝에서 전체 + 직전 확정 텍스트를 prompt 로
             ▼
RAG Suite /v1/audio/transcriptions
```

### 왜 MediaRecorder 를 안 쓰나

`MediaRecorder` 의 webm/opus 는 두 번째 chunk 부터 EBML 헤더가 없어 단독 디코딩이
안 된다. 그대로 잘라 올리면 400 이거나 빈 텍스트가 온다. AudioWorklet 으로 raw PCM 을
받아 서버에서 구간마다 WAV 헤더를 붙이면 모든 chunk 가 독립 파일이 되고 ffmpeg 도 필요 없다.

### 왜 고정 시간 분할을 안 쓰나

측정했더니 못 쓸 물건이었다. 아래 표는 7.68초 한국어 샘플 하나를 전략별로 돌려
전체 1회 전사 대비 CER 을 잰 것이다 (`probe_quality.py`).

| 전략 | CER | tokens | 호출 |
|---|---|---|---|
| prompt-chain 3초 | **0.0%** | 882 | 3 |
| growing window 2초 | 0.0% | 2093 | 4 |
| overlap 3초+1초 | 6.8% | 1033 | 3 |
| fixed 5초 | 20.5% | 826 | 2 |
| fixed 2초 | 22.7% | 837 | 4 |
| fixed 1초 | **68.2%** | 847 | 8 |

fixed-1s 결과는 이랬다.

```
원본   지금 들으시는 음성은 KT 클라우드 AI 파운드리의 모스티 TS 모델로 생성한 테스트용 레퍼런스입니다.
1초분할 고맙습니다. -. 기상캐스터 파운드리에 모스티티에스 모델로 생성한 기상캐스터 날씨였습니다.
```

"기상캐스터" 는 오디오에 없는 말이다. 단어 중간이 잘리면 whisper 가 지어낸다.
그래서 자르는 위치를 시간이 아니라 **무음 경계**로 잡고, 직전 확정 텍스트를
`prompt` 로 넘겨 문맥을 잇는다.

---

## 실측값

전부 `probe*.py` 로 이 엔드포인트에서 직접 잰 값이다.

### 과금은 오디오 길이에 선형 — 쪼개도 손해가 없다

| 오디오 | 1s | 2s | 3s | 5s | 7s | 7.68s |
|---|---|---|---|---|---|---|
| total_tokens | 110 | 220 | 319 | 536 | 746 | 814 |

약 107 토큰/초. 전체 1회(814) 대 1초씩 7회(770) = **0.95배**.
whisper 가 30초로 패딩해 과금할 것이라 예상했는데 그렇지 않았다.
chunk 크기는 비용이 아니라 **정확도** 기준으로 정하면 된다.

### 지연

| chunk | 1s | 2s | 3s | 5s | 7s |
|---|---|---|---|---|---|
| 왕복 median | 0.21s | 0.29s | 0.30s | 0.73s | 0.54s |

실시간의 약 0.1배 속도. 동시 8 요청도 전부 200, wall 0.94초였고 rate limit 헤더는 없었다.

### 파라미터

| 항목 | 결과 |
|---|---|
| `language` / `temperature` / `prompt` | 동작. `prompt` 는 토큰이 늘어나므로 실제로 모델에 들어간다 |
| `response_format=verbose_json` | 지원. `segments[]` 에 start/end/avg_logprob/compression_ratio |
| `verbose_json` 의 `usage` | **없음**. 타임스탬프와 정확한 과금 집계는 택일 |
| `words[]` (word 타임스탬프) | `timestamp_granularities[]=word` 를 줘도 항상 빈 배열 |
| `no_speech_prob` | 항상 `null` |
| `response_format=srt` / `vtt` | 400 |
| CORS preflight | 401, `Access-Control-*` 헤더 없음 → 브라우저 직접 호출 불가 |

이 프록시는 STT 전용이다. `/v1/models` 는 `openai/whisper-large-v3` 하나만 반환하고
`/v1/chat/completions`, `/v1/audio/speech`, `/v1/embeddings`, `/v1/realtime` 은 전부 404다.

---

## 잡음 게이트

무음이나 잡음을 그대로 올리면 whisper 는 길이와 무관하게 `" 감사합니다."` 를 반환한다.
초당 107 토큰이 그대로 과금되고 그 문장이 확정 텍스트로 들어간다.

사후 필터를 두 번 시도했고 둘 다 실패했다.

- `avg_logprob` — 실제 발화 최저 -0.453 이 무음 -0.430 보다 나빴다. 값이 겹쳐 판별 불가.
- `compression_ratio` — 텍스트만의 함수다. 같은 문자열이면 항상 같은 값이라 무의미.
- 텍스트 패턴 차단 — 사용자가 진짜로 "감사합니다" 라고 말하면 구분할 방법이 없다.

그래서 판정을 오디오 쪽으로 옮겼다. **spectral flatness** 하나로 자른다.

| 신호 | flatness |
|---|---|
| 발화 | 0.17 ~ 0.22 (0.6초 창부터 7.7초 창까지 안정적) |
| 백색잡음 | 0.85 (진폭 300~4000 에서 동일) |
| 순음 / 60Hz 험 | 0.001 |

위로는 잡음, 아래로는 순음을 자른다(`0.02 ≤ flatness ≤ 0.45`).
진폭과 무관해서 에너지 VAD 가 놓치는 큰 잡음도 잡히고, API 호출 자체를 막으므로
요금도 나가지 않는다.

`speech-band ratio`(300~3400Hz 비율)도 후보였으나 **판정에서 뺐다.** 긴 발화는 0.61 로
잘 나오지만 발화 시작 직후 짧은 창에서 0.30~0.44 까지 떨어져 백색잡음(0.38)과 겹친다.
이걸로 자르면 짧은 실제 발화가 버려진다. 지표로만 보고한다.

유성 프레임이 12개 미만이면 판단을 보류하고 통과시킨다(fail-open). 실제 발화를
버리는 쪽이 잡음 한 조각을 통과시키는 쪽보다 나쁘다.

---

## 잠정 결과의 비용

growing window 는 같은 오디오를 반복해서 전사한다. 7.7초 발화 하나에서:

| | 호출 | 토큰 |
|---|---|---|
| 확정만 | 1 | 844 |
| 확정 + 잠정 | 11 | 5140 |

**약 6배.** UI 의 `잠정 결과 표시` 체크박스로 끌 수 있고, 배율은 화면에 실시간으로 표시된다.

줄이려면 `Settings.interim_min_interval_s` 를 올리면 된다(기본 0.8초).
잠정 호출은 single-flight 라서 앞 요청이 끝나야 다음이 나간다. 서버가 느려지면
호출 빈도가 자동으로 낮아진다.

---

## 알려진 한계

- **에너지 VAD 가 약한 고리다.** 잡음 게이트가 뒤를 받치지만, 시끄러운 환경이나
  겹침 발화에서는 Silero VAD 같은 신경망 VAD 로 바꾸는 편이 낫다.
- **화자 분리 없음.** whisper 는 diarization 모델이 아니라 단일 전사 텍스트만 낸다.
- **확정 지연의 하한은 `vad_end_silence_ms`(기본 600ms)다.** 줄이면 문장이 토막나고
  늘리면 확정이 늦어진다.
- **프록시가 간헐적으로 502 를 낸다.** 연속 호출 27회에 1회꼴로 관측됐다.
  5xx 와 연결 오류는 2회까지 재시도하므로 대개 흡수되지만, 원인은 상단이라
  이쪽에서 없앨 수 없다. 잠정 전사가 실패하면 이벤트 로그에 `경고` 로 남는다.
- **측정 표본이 1개다.** 7.68초, TTS 로 만든 깨끗한 한국어 음성 하나로 잰 값이다.
  방향성은 분명하지만 절대값은 참고치다. 실사용 녹음으로 다시 재는 것을 권한다.
- **단가 단위 미확인.** 문서의 Input 30원 / Output 610원이 1M 토큰 기준인지 확실하지
  않다. `Settings.krw_per_1m_*` 에 1M 기준으로 가정해 넣었으니 확인 후 고쳐야 한다.
- **인증은 단일 공유 키다.** `APP_ACCESS_KEY` 는 팀 내부에 잠깐 돌려보는 용도지
  사용자별 계정이 아니다. 상한도 연결 단위라 새로고침하면 초기화된다.
  제대로 운영하려면 사용자 인증과 서버 전체 사용량 집계가 따로 필요하다.

---

## 파일

| 경로 | 설명 |
|---|---|
| `server/config.py` | 설정. 기본값의 근거를 주석으로 남겼다 |
| `server/audio.py` | PCM ↔ WAV, 리샘플, RMS |
| `server/vad.py` | 적응형 노이즈 플로어 에너지 VAD |
| `server/spectral.py` | flatness 기반 잡음 게이트 |
| `server/stt.py` | RAG Suite 클라이언트 (동시성 제한 포함) |
| `server/session.py` | 잠정/확정 두 경로 상태 머신 |
| `server/app.py` | FastAPI + WebSocket |
| `web/pcm-worklet.js` | 마이크 → 16kHz int16 PCM |
| `web/app.js` | UI, WS, 통계 |
| `probe.py` | 엔드포인트 실측 (과금/지연/파라미터/동시성/CORS) |
| `probe_quality.py` | chunk 전략별 CER 비교 |
| `probe_threshold.py` | hallucination 필터 임계값 탐색 |
| `test_offline.py` | API 호출 없는 검증 |
| `make-dist.sh` | 배포용 zip 생성 (.env·.venv 제외) |
| `setup.sh` | venv 생성 + 의존성 설치 |
| `samples/` | 마이크 없이 테스트할 예제 음성 |
| `simulate.py` / `ws_test.py` | 마이크 없이 파이프라인 구동 |

`.env` 는 gitignore 되어 있다. 토큰을 커밋하지 않도록 주의.
