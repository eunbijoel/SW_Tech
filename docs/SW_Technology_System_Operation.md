# SW Technology — 컴퓨터 시스템 관점 설명서

> **작성 기준:** `/SW_Tech` 저장소 현재 구현 코드 (2026-06-11)  
> **목적:** "사용자가 브라우저에 질문을 입력하면, 어떤 네트워크 경로를 타고, 어떤 프로세스에서 어떤 처리를 거쳐, 어떤 모델이 응답을 생성하고, 그 결과가 다시 브라우저까지 돌아오는가"를 컴퓨터 시스템 관점에서 설명

---

## 1. 전체 시스템 아키텍처

### 1.1 시스템 구성도 (계층)

```
┌──────────────────────────────────────────────────────────────────────┐
│                        사용자의 PC (또는 노트북)                        │
│  ┌──────────────┐                                                    │
│  │   웹 브라우저  │  ◄── HTML/CSS/JS 렌더링, 사용자 입력 수집             │
│  │  (Chrome 등) │                                                     │
│  └──────┬───────┘                                                    │
│         │ HTTP 요청 (localhost:8502 또는 원격IP:포트)                   │
└─────────┼────────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     서버 (RTX 5090 서버)                              │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │              Python 런타임 (.venv 가상환경)                    │    │
│  │                                                             │     │
│  │  ┌──────────────────────────────────────┐                   │     │
│  │  │     Streamlit 웹 서버 (app.py)        │                   │     │
│  │  │     - HTTP 요청 수신 (포트 8502)       │                   │     │
│  │  │     - 사용자 입력 → Python 함수 실행    │                   │     │
│  │  │     - st.session_state 관리           │                   │     │
│  │  │     - UI 컴포넌트 렌더링               │                   │     │
│  │  └──────────────┬───────────────────────┘                   │     │
│  │                 │                                           │     │
│  │     ┌───────────┼────────────────────────┐                  │     │
│  │     │  src/     │   services/    ui/     │                  │     │
│  │     │  persona  │   ollama      persona  │                  │     │
│  │     │  prompt   │   trace       trace    │                  │     │
│  │     │  router   │   enhancer    dash     │                  │     │
│  │     │  tool     │   store       flow     │                  │     │
│  │     └───────────┼────────────────────────┘                  │     │
│  │                 │ HTTP POST (localhost:11434)                │     │
│  └─────────────────┼───────────────────────────────────────────┘     │
│                    ▼                                                  │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │              Ollama (LLM 추론 서버)                           │     │
│  │              - 포트 11434                                    │     │
│  │              - GPU/RAM에 모델 로드                            │     │
│  │              - REST API (/api/chat, /api/tags)              │     │
│  └──────────────────────────────┬──────────────────────────────┘     │
│                                 │                                    │
│  ┌──────────────────────────────▼──────────────────────────────┐     │
│  │              GPU (NVIDIA RTX 5090 등)                        │     │
│  │              - VRAM에 모델 가중치 적재                         │     │
│  │              - 행렬 연산으로 토큰 생성                          │     │
│  └─────────────────────────────────────────────────────────────┘     │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │              파일 시스템                                      │     │
│  │  ./excel/     — 업로드된 엑셀 파일                            │     │
│  │  ./results/   — 대화 저장 마크다운                             │     │
│  │  ./outputs/   — 비교 테스트 결과                               │     │
│  │  ./config/    — personas.json (Persona 설정)                │     │
│  └─────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.2 계층별 역할 요약


| 계층                 | 구현                                    | 역할                                                                                           |
| ------------------ | ------------------------------------- | -------------------------------------------------------------------------------------------- |
| **웹 브라우저**         | Chrome, Edge 등                        | Streamlit이 생성한 HTML/CSS/JS를 렌더링. 사용자 입력(타이핑, 클릭, 파일 업로드)을 HTTP 요청으로 서버에 전송                   |
| **Streamlit 웹 서버** | `streamlit run app.py` (포트 8502)      | HTTP 요청을 수신하고, 사용자 상호작용마다 `app.py` 전체를 위에서 아래로 재실행. UI 변경 사항을 WebSocket으로 브라우저에 푸시           |
| **Python 런타임**     | `.venv` + `requirements.txt`          | pandas, requests, streamlit 등 라이브러리 실행 환경. `app.py`와 `src/`, `services/`, `ui/` 모듈이 이 위에서 동작 |
| **Ollama LLM 서버**  | `localhost:11434`                     | REST API로 LLM 추론 제공. 모델을 GPU VRAM에 로드하고, 프롬프트를 받아 텍스트(코드)를 생성                                |
| **GPU**            | NVIDIA RTX 5090 (32GB VRAM) 등         | Ollama가 사용. 대형 모델(27B, 32B 파라미터)의 가중치를 VRAM에 적재하고 행렬 연산으로 추론 수행                              |
| **파일 시스템**         | `./excel/`, `./results/`, `./config/` | 엑셀 파일 저장, 대화 이력 마크다운 저장, Persona 설정 JSON 저장                                                  |


### 1.3 핵심 설계 특징

- **단일 프로세스 아키텍처**: React/Node 백엔드나 별도 REST API 서버 없이, `app.py` **하나**로 UI + 로직 + LLM 호출 + 코드 실행을 모두 담당
- **서버-사이드 렌더링**: 브라우저는 "화면 표시 + 입력 수집"만 담당. 모든 로직은 서버의 Python 프로세스에서 실행
- **Ollama는 브라우저가 아닌 app.py만 호출**: 브라우저 → Streamlit → app.py → Ollama 순서 (브라우저가 Ollama에 직접 접속하지 않음)

---

## 2. 네트워크 및 실행 환경

### 2.1 `streamlit run app.py` 실행 시 일어나는 일

터미널에서 다음 명령을 실행하면:

```bash
streamlit run app.py --server.port 8502 --server.address 0.0.0.0
```

**운영체제 수준에서 일어나는 과정:**

1. **Python 인터프리터 시작**: 쉘이 `.venv/bin/python`(가상환경)을 실행
2. **Streamlit 프레임워크 로드**: `streamlit` 패키지가 내장 Tornado 웹 서버를 초기화
3. **TCP 소켓 바인딩**: 운영체제에 포트 8502를 요청하여 HTTP 리스닝 소켓을 생성. `0.0.0.0`은 "모든 네트워크 인터페이스에서 접속 허용"
4. **app.py 최초 실행**: 파일 전체를 위에서 아래로 한 번 실행. 이때:
  - `st.set_page_config()` → 페이지 메타데이터 설정
  - `_DEFAULTS` → `st.session_state` 초기값 등록
  - CSS 주입, Ollama 연결 함수 정의, UI 컴포넌트 배치
5. **HTTP 서버 대기**: 브라우저 접속을 기다리는 상태

**이 시점에서 실행 중인 프로세스:**


| 프로세스            | PID           | 역할                         |
| --------------- | ------------- | -------------------------- |
| `python app.py` | Streamlit이 할당 | Streamlit 웹 서버 + 애플리케이션 로직 |
| `ollama serve`  | 별도 실행         | LLM 추론 서버 (GPU 점유)         |


> `app.py`에는 `if __name__ == "__main__"` 블록이 **없습니다.** Streamlit이 파일 전체를 모듈처럼 로드하고, **사용자 상호작용(입력, 버튼 클릭)마다 스크립트를 다시 실행**합니다. `st.session_state`에 저장된 값은 같은 브라우저 세션 동안 유지됩니다.

실행 스크립트: 

```bash
scripts/run_studio.sh
```

### 2.2 네트워크 구조 — 포트, IP, DNS

#### 로컬 실행 (개발자 PC에서 직접 실행)

```
브라우저 주소창: http://localhost:8502
         │
         │  ← localhost = 127.0.0.1 (자기 자신을 가리키는 루프백 주소)
         │  ← 8502 = Streamlit이 리스닝하는 TCP 포트 번호
         ▼
┌─────────────────────────────────────────────┐
│  같은 PC                                     │
│  Streamlit (포트 8502) ─→ Ollama (포트 11434)│
│  브라우저 + Python + Ollama + GPU 모두 여기   │
└─────────────────────────────────────────────┘
```

- **localhost** (= 127.0.0.1): TCP/IP에서 자기 자신을 가리키는 특수 주소. 네트워크 카드를 거치지 않고 OS 내부에서 통신
- **포트(Port)**: 하나의 IP 주소에서 여러 서비스를 구분하는 번호 (0~65535). Streamlit은 8502, Ollama는 11434를 사용
- `.streamlit/config.toml`에서 포트 설정:

```toml
[server]
port = 8502
address = "0.0.0.0"    # 모든 네트워크 인터페이스에서 접속 허용
```

#### 원격 실행 (RTX 5090 서버)

```
사용자 노트북 브라우저                             RTX 5090 서버
┌──────────────┐                              ┌──────────────────────┐
│ Chrome       │  HTTP                        │ Streamlit (8502)     │
│ 주소창:       │ ──────────────────────────→  │ Ollama (11434)       │
│ 서버IP:8502   │                              │ GPU (RTX 5090)       │
└──────────────┘                              └──────────────────────┘
```

**원격 접속 방식 3가지:**


| 방식               | 브라우저 주소                           | 설명                                                                 |
| ---------------- | --------------------------------- | ------------------------------------------------------------------ |
| **직접 IP 접속**     | `http://192.168.0.51:8502`        | 같은 네트워크(LAN) 내에서 서버의 사설 IP로 접속                                     |
| **DDNS + 포트포워딩** | `http://bigsoft.iptime.org:7780`  | 공유기가 외부 포트 7780 → 내부 8502로 변환. DDNS가 유동 공인 IP를 도메인 이름으로 매핑         |
| **SSH 터널링**      | `http://localhost:8502` (로컬처럼 보임) | SSH 포트포워딩으로 원격 서버의 8502를 로컬 8502에 연결. Cursor Remote SSH 사용 시 자동 설정 |


**DNS/IP/포트 흐름 (DDNS 접속 시):**

```
브라우저: http://bigsoft.iptime.org:7780
         │
         ▼ DNS 조회
bigsoft.iptime.org → 공인 IP (예: 211.xxx.xxx.xxx)
         │
         ▼ 인터넷을 통해 공인 IP:7780 에 TCP 연결
공유기 (NAT/포트포워딩)
    외부 포트 7780 → 내부 192.168.0.100:8502
         │
         ▼
RTX 5090 서버의 Streamlit (포트 8502)
```

**SSH 터널링 (Cursor Remote SSH):**

```bash
# 원격 서버의 localhost:8502를 내 노트북의 localhost:8502로 연결
ssh -L 8502:localhost:8502 user@서버IP
```

이후 내 노트북 브라우저에서 `http://localhost:8502`로 접속하면, 실제로는 SSH 암호화 터널을 통해 원격 서버의 Streamlit에 연결됩니다.

### 2.3 로컬 vs 원격 — 차이 비교


| 항목              | 로컬 PC                  | 원격 서버 (RTX 5090)      |
| --------------- | ---------------------- | --------------------- |
| Streamlit 실행 위치 | 내 PC                   | 서버                    |
| Ollama 실행 위치    | 내 PC                   | 서버                    |
| GPU             | 내 PC의 GPU (없을 수도 있음)   | RTX 5090 (32GB VRAM)  |
| 브라우저 접속 주소      | `localhost:8502`       | `서버IP:8502` 또는 SSH 터널 |
| LLM 성능          | GPU 없으면 CPU 추론 (매우 느림) | GPU 추론 (빠름)           |
| 코드상 차이          | 없음                     | 없음                    |


### 2.4 환경 변수

`.env.example` 및 `app.py`에서 확인되는 설정:


| 변수                     | 기본값                      | 용도                                      |
| ---------------------- | ------------------------ | --------------------------------------- |
| `OLLAMA_BASE_URL`      | `http://localhost:11434` | Ollama API 서버 주소. 원격 Ollama 사용 시 변경     |
| `OLLAMA_KEEP_ALIVE`    | `30m`                    | 모델을 GPU/RAM에 유지하는 시간 (30분간 요청 없으면 언로드)  |
| `SW_TECH_BENCHMARK`    | (미설정)                    | `1`이면 UI 블록 생략, 벤치마크 모드로 import         |
| `CUDA_VISIBLE_DEVICES` | (미설정)                    | GPU가 여러 개일 때 사용할 GPU 지정 (예: `0`, `0,1`) |


---

## 3. 사용자 입력 처리 흐름 (Input → Output 전체 경로)

### 3.1 전체 흐름도

```
[1단계: 사용자 입력]
 브라우저에서 st.chat_input에 질문 타이핑 + Enter
         │
         ▼ HTTP POST (브라우저 → Streamlit 서버)
[2단계: Streamlit 서버 수신]
 app.py 전체 재실행 (st.session_state는 유지)
 prompt 변수에 사용자 입력 저장
         │
         ▼
[3단계: process_message(prompt) 호출]
         │
         ├─ [3-1] 모델 선택: ollama_models() + pick_safe_ollama_model()
         │        Input:  사용자 선택 모델, GPU VRAM 정보
         │        Output: 실제 사용할 모델 이름
         │
         ├─ [3-2] 파일 확인: 첨부 파일 없으면 경고 후 종료
         │
         ├─ [3-3] 데이터 로드: build_data_context(attached_files)
         │        Input:  파일명 목록
         │        Output: DataFrame dict + 텍스트 컨텍스트
         │
         ├─ [3-4] Persona 파이프라인: _prepare_enhancement()
         │        Input:  사용자 질문, persona_id, 파일 메타데이터
         │        Output: 구조화된 프롬프트, 도구 실행 결과, 실행 경로
         │
         ▼
[4단계: 코드 생성 — generate_excel_code_only()]
         │
         ├─ 경로A: tool_response  → LLM 없이 도구 결과로 직접 응답
         ├─ 경로B: template_code  → 내장 pandas 코드 (LLM 생략)
         └─ 경로C: llm_codegen    → Ollama에 프롬프트 전송
                    │
                    ▼ HTTP POST (app.py → localhost:11434/api/chat)
              [5단계: Ollama LLM 추론]
                    Input:  프롬프트 (system + user 메시지)
                    Output: Python/pandas 코드 문자열
                    │
                    ▼
[6단계: 코드 실행 승인]
 pending_excel_run에 코드 저장 → 브라우저에 "실행" 버튼 표시
 (auto_run_excel_code=True이면 자동 실행)
         │
         ▼ 사용자가 "실행" 클릭
[7단계: 샌드박스 실행 — execute_pandas_code()]
         Input:  생성된 Python 코드, DataFrame dict
         Process: 별도 Python 서브프로세스에서 실행 (60초 제한)
         Output: 결과 DataFrame, 차트 이미지(PNG)
         │
         ▼
[8단계: 응답 저장 및 표시]
         ├─ st.session_state.messages에 assistant 턴 추가
         ├─ results/chat_live_*.md에 자동 저장
         └─ render_message_with_trace() → 브라우저에 표시
                    │
                    ▼ WebSocket (Streamlit 서버 → 브라우저)
[9단계: 브라우저 화면 갱신]
 결과 표(DataFrame), 차트(PNG), 실행 추적 정보 렌더링
```

### 3.2 입력이 들어오는 3가지 경로


| 경로            | UI 위치        | 코드 위치                               | 동작                                  |
| ------------- | ------------ | ----------------------------------- | ----------------------------------- |
| **메인 채팅 입력**  | 화면 하단 텍스트 박스 | `st.chat_input()` (app.py 2688행)    | 직접 `process_message(prompt)` 호출     |
| **제안 버튼 클릭**  | 채팅 영역 내 버튼   | `pending_prompt`에 저장 → `st.rerun()` | 재실행 시 `process_message(pending)` 호출 |
| **Step Flow** | 사이드바 플로우     | `handle_flow_execution()`           | `pending_prompt` 설정 → 재실행           |


### 3.3 session_state — 브라우저 세션 동안 유지되는 상태

`st.session_state`는 Streamlit이 제공하는 **서버 메모리 기반 상태 저장소**입니다. 브라우저 탭과 1:1로 매핑되며, app.py가 재실행되어도 값이 유지됩니다.


| 키                        | 초기값         | 역할                                       |
| ------------------------ | ----------- | ---------------------------------------- |
| `messages`               | `[]`        | 전체 대화 목록 (user/assistant dict, trace 포함) |
| `selected_model`         | `""`        | 사용자가 선택한 Ollama 모델 태그                    |
| `attached_files`         | `[]`        | 첨부된 `./excel/` 파일명 목록                    |
| `persona_id`             | `"general"` | 현재 선택된 Persona ID                        |
| `use_enhancement`        | `True`      | 프롬프트 보강 파이프라인 ON/OFF                     |
| `pending_excel_run`      | `None`      | 생성된 코드의 승인 대기 데이터                        |
| `persona_execution_plan` | —           | Persona 파이프라인 실행 결과                      |
| `auto_run_excel_code`    | `False`     | 코드 자동 실행 여부                              |


---

## 4. Persona 및 Prompt 생성 흐름

### 4.1 Persona 시스템 개요

Persona는 "같은 질문에 다른 관점으로 답하게 하는 구조화된 설정"입니다. 단순히 system_prompt 문자열을 붙이는 수준이 아니라, **의도 감지 → 도구 선택 → 실행 경로 분기 → 구조화 프롬프트 생성**의 파이프라인으로 동작합니다.

### 4.2 Persona 정의 — `config/personas.json`

5개의 내장 Persona가 정의되어 있습니다:


| Persona ID            | 이름           | 분석 관점            | 주요 도구                                                            |
| --------------------- | ------------ | ---------------- | ---------------------------------------------------------------- |
| `data_analyst`        | 📊 데이터 분석가   | 통계, 패턴, 트렌드      | `dataframe_summary`, `statistics_analyzer`, `excel_analyzer`     |
| `excel_expert`        | 📋 엑셀 전문가    | 시트 구조, 입력 범위, 정제 | `excel_analyzer`, `excel_actions`                                |
| `business_consultant` | 💼 비즈니스 컨설턴트 | KPI, 경영 인사이트     | `kpi_summary`, `insight_generator`, `dataframe_summary`          |
| `researcher`          | 🔬 연구원       | 방법론, 증거, 한계      | `report_generator`, `methodology_checker`, `statistics_analyzer` |
| `general`             | 🎯 일반 어시스턴트  | 범용 요약            | `basic_chat`, `dataframe_summary`                                |


각 Persona는 다음 필드를 가집니다:

- `system_prompt`: LLM에게 전달할 역할 지시 (예: "당신은 10년 경력 비즈니스 컨설턴트입니다")
- `task_hints`: 의도(intent)별 구체적 행동 지침 (예: FILE_META 의도일 때 "파일마다 따로 분석하세요")
- `analysis_focus`: 분석 시 집중할 관점 리스트
- `response_template`: 응답 출력 순서 (예: "요약 → 상세 → 다음 단계")
- `style_rules`: 톤, 상세 수준, 출력 형식

### 4.3 Persona 파이프라인 — 단계별 입출력

프롬프트 보강 ON (`use_enhancement=True`) 일 때의 전체 흐름:

```
사용자 입력: "각 파일별 입력 범위 알려줘"
       │
       ▼
┌─────────────────────────────────────────────────────┐
│ [단계 1] 의도 감지 — detect_intent()                   │
│                                                     │
│ Input:  사용자 메시지 문자열                            │
│ Process: INTENT_KEYWORDS 사전에서 키워드 매칭           │
│          "파일별" → FILE_META, "분석" → ANALYSIS 등     │
│ Output: intent = "FILE_META"                        │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│ [단계 2] 전략 결정 — persona_router.decide_strategy()  │
│                                                     │
│ Input:  PersonaProfile, intent, user_prompt,        │
│         has_attachments                             │
│ Process:                                            │
│   - Persona별 허용 도구에서 실행 도구 목록 선택          │
│   - intent + Persona 조합으로 실행 경로 결정            │
│ Output: AnalysisStrategy                            │
│   - tools_to_run: ["excel_analyzer", "excel_actions"] │
│   - execution_path: "tool_response"                 │
│   - analysis_focus: ["시트 구조", "입력 범위", ...]     │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│ [단계 3] 도구 실행 — tool_registry.run_tools()         │
│                                                     │
│ Input:  도구 이름 목록, 파일명, DataFrame dict          │
│ Process:                                            │
│   - excel_analyzer: 파일별 used range, 빈 행/열 계산   │
│   - excel_actions: 후속 처리 제안 생성                  │
│   - statistics_analyzer: 기술통계 계산                  │
│   - kpi_summary: 예산/집행 관련 KPI 후보 탐색           │
│ Output: tool_results dict (JSON 구조의 분석 결과)      │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│ [단계 4] 구조화 프롬프트 생성                            │
│          — prompt_builder.build_structured_sections() │
│                                                     │
│ Input:  PersonaProfile, user_request, intent,       │
│         file_context, tool_context, task_hint       │
│ Process: 각 요소를 섹션별로 분리                        │
│ Output: sections dict                               │
│   {                                                 │
│     "persona_role": "📋 엑셀 전문가 — 엑셀 파일 구조...",│
│     "analysis_focus": "- 시트 구조\n- 입력 범위\n...",  │
│     "system_instruction": "당신은 엑셀 전문가...",      │
│     "detected_intent": "FILE_META",                 │
│     "task_hint": "각 파일의 행·열 범위를...",            │
│     "tool_context": "{...분석 결과 JSON...}",         │
│     "user_request": "각 파일별 입력 범위 알려줘"        │
│   }                                                 │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│ [단계 5] LLM 메시지 구성                               │
│          — prompt_builder.build_chat_messages()      │
│                                                     │
│ Input:  sections dict                               │
│ Output: Ollama API용 messages 배열                    │
│   [                                                 │
│     { "role": "system",                             │
│       "content": "## Persona Role\n📋 엑셀 전문가..."  │
│     },                                              │
│     { "role": "user",                               │
│       "content": "## User Request\n각 파일별..."      │
│     }                                               │
│   ]                                                 │
└─────────────────────────────────────────────────────┘
```

### 4.4 프롬프트 보강 OFF 일 때

`use_enhancement=False`이면:

- `prepare_persona_execution()` **호출 안 함**
- 도구 실행, 구조화 섹션, intent 분기 **모두 생략**
- 선택된 Persona의 `system_prompt`만 기본 system 메시지로 사용

---

## 5. LLM 모델 처리

### Ollama란 무엇인가

**Ollama**는 오픈소스 대형 언어 모델(LLM)을 로컬 컴퓨터에서 실행할 수 있게 해주는 **로컬 LLM 추론 서버**입니다.

**핵심 역할:**

- 오픈소스 LLM 모델 파일을 다운로드하고 관리
- GPU VRAM에 모델 가중치를 로드
- REST API를 통해 외부 애플리케이션(app.py)에 추론 서비스 제공
- 모델 양자화(quantization)를 적용하여 제한된 VRAM에서도 대형 모델 실행

**Docker와의 비유:**

- Docker가 컨테이너 이미지를 pull/run 하듯, Ollama는 LLM 모델을 `ollama pull`/`ollama run`으로 관리
- `ollama serve`: API 서버를 데몬으로 실행 (기본 포트 11434)
- `ollama list`: 설치된 모델 목록 확인

## 6. 응답 반환 흐름

### 6.1 코드 실행 흐름 (샌드박스)

LLM이 생성한 pandas 코드는 **보안을 위해 별도의 서브프로세스**에서 실행됩니다:

```
생성된 Python 코드
         │
         ▼
execute_pandas_code(code, dataframes)
         │
         ├─ [검증] AST 파싱으로 금지 import 검사
         │         (os.system, subprocess 등 차단)
         │
         ├─ [준비] 임시 디렉터리에 DataFrame을 pickle로 저장
         │
         ├─ [실행] subprocess.run()으로 별도 Python 프로세스 생성
         │         ┌─────────────────────────────────┐
         │         │ __runner__.py (서브프로세스)       │
         │         │  - pickle에서 DataFrame 로드      │
         │         │  - 사용자 코드 실행               │
         │         │  - result DataFrame pickle 저장  │
         │         │  - 차트 있으면 PNG 저장            │
         │         │  (타임아웃: 60초)                 │
         │         └─────────────────────────────────┘
         │
         ├─ [수집] 결과 pickle/PNG/텍스트 수집
         │
         ▼
{ dataframe: DataFrame, chart_bytes: bytes, shape: {...} }
```

### 6.2 Human-in-the-loop: 코드 실행 승인

기본적으로 LLM이 생성한 코드는 **사용자 승인 후 실행**됩니다:

```
코드 생성 완료
         │
         ▼
pending_excel_run에 저장 → 브라우저에 코드 미리보기 + 버튼 표시
         │
         ├─ [✅ 실행] → execute_pandas_code() → 결과 표시
         │
         └─ [❌ 취소] → "실행이 취소되었습니다" 표시
```

`auto_run_excel_code = True` 토글을 켜면 승인 없이 자동 실행됩니다.

### 6.3 응답 저장


| 저장소                              | 내용                           | 시점                              |
| -------------------------------- | ---------------------------- | ------------------------------- |
| `st.session_state.messages`      | 전체 대화 (role, content, trace) | 매 턴마다 즉시                        |
| `results/chat_live_{session}.md` | 마크다운 형식 자동 저장                | `_autosave_messages()` — 매 응답 후 |
| `results/chat_YYYYMMDD_*.md`     | 수동 저장                        | 사용자가 "💾 보내기" 클릭 시              |


trace 정보(토큰 수, 소요 시간, 생성 코드)는 마크다운에 `<!--sw_trace:...-->` HTML 주석으로 삽입되어, 나중에 다시 로드할 때 복원됩니다.

### 6.4 브라우저 화면 표시

```
st.chat_message("assistant")
         │
         ├─ 본문 텍스트 (마크다운 렌더링)
         │
         ├─ 결과 표 (st.dataframe — DataFrame 렌더링)
         │
         ├─ 차트 이미지 (st.image — PNG)
         │
         └─ 실행 추적 (render_message_with_trace)
              ├─ metrics footer: 토큰 수, 소요 시간, 모델명
              └─ "🔍 실행 상세" 확장: thinking, 생성 코드, 파이프라인 단계
```

### 6.5 새로고침 / 세션 종료 시

- **브라우저 새로고침**: `session_state`가 유지되므로 대화 내역 보존 (같은 세션 내)
- **서버 재시작 또는 세션 타임아웃**: `session_state` 초기화. 디스크의 `results/*.md`에서 `render_saved_chats_section()`으로 다시 불러오기 가능

---

## 7. 단계별 입출력 및 산출물 정리

아래는 전체 흐름의 각 단계를 **Input → Process → Output** 형식으로 정리한 것입니다.

### 단계 1: 사용자 입력


| 항목          | 내용                                                                                |
| ----------- | --------------------------------------------------------------------------------- |
| **Input**   | 브라우저의 `st.chat_input`에 입력된 텍스트, 사이드바에서 선택된 Persona·모델·첨부파일                        |
| **Process** | Streamlit이 HTTP POST 요청 수신 → app.py 재실행 → `process_message()` 호출                  |
| **Output**  | `prompt` 변수 (문자열), `st.session_state`의 persona_id, selected_model, attached_files |


### 단계 2: 데이터 로드


| 항목          | 내용                                                                                                              |
| ----------- | --------------------------------------------------------------------------------------------------------------- |
| **Input**   | `attached_files` (파일명 목록), `./excel/` 디렉터리의 실제 파일                                                               |
| **Process** | `build_data_context()` → `read_excel_smart()` → pandas `read_excel()`                                           |
| **Output**  | `frames` dict (`{"df_0": DataFrame, "df_1": DataFrame, ...}`), `data_context` 텍스트 (shape, columns, dtypes, 결측률) |


### 단계 3: 의도 감지


| 항목          | 내용                                                                                                      |
| ----------- | ------------------------------------------------------------------------------------------------------- |
| **Input**   | 사용자 메시지 문자열                                                                                             |
| **Process** | `detect_intent()` — 키워드 사전 매칭 (FILE_META, MERGE, ANALYSIS, COMPARISON, SUMMARY, FILTER, CHART, GENERAL) |
| **Output**  | `intent` 문자열 (예: `"FILE_META"`)                                                                         |


### 단계 4: 전략 결정


| 항목          | 내용                                                                                   |
| ----------- | ------------------------------------------------------------------------------------ |
| **Input**   | PersonaProfile, intent, user_prompt, has_attachments                                 |
| **Process** | `persona_router.decide_strategy()` — Persona tools + intent 조합으로 도구 목록·실행 경로 결정      |
| **Output**  | `AnalysisStrategy` (tools_to_run, execution_path, analysis_focus, response_template) |


### 단계 5: 도구 실행


| 항목          | 내용                                                                                            |
| ----------- | --------------------------------------------------------------------------------------------- |
| **Input**   | 도구 이름 목록, 파일명, DataFrame dict                                                                 |
| **Process** | `tool_registry.run_tools()` — 순서대로 도구 실행, 이전 도구 결과를 다음 도구에 전달                                 |
| **Output**  | `tool_results` dict (예: `{"excel_analyzer": {"files": [...]}, "statistics_analyzer": {...}}`) |


### 단계 6: 프롬프트 생성


| 항목                 | 내용                                                                                          |
| ------------------ | ------------------------------------------------------------------------------------------- |
| **Input**          | PersonaProfile, user_request, intent, file_context, tool_context, task_hint                 |
| **Process**        | `build_structured_sections()` → `build_chat_messages()` 또는 `build_code_generation_prompt()` |
| **Output (chat용)** | `messages` 배열: `[{role: "system", content: "..."}, {role: "user", content: "..."}]`         |
| **Output (코드생성용)** | 단일 프롬프트 문자열 (Persona 분석 관점 + 코드 규칙 + 데이터 컨텍스트 + 사용자 요청)                                     |


### 단계 7: LLM 호출 (llm_codegen 경로만)


| 항목          | 내용                                                                                       |
| ----------- | ---------------------------------------------------------------------------------------- |
| **Input**   | 프롬프트 문자열, 모델 이름                                                                          |
| **Process** | `ollama_generate()` → HTTP POST `localhost:11434/api/chat` → Ollama가 GPU에서 추론 → 토큰 단위 생성 |
| **Output**  | `OllamaCallResult` (content: Python 코드, prompt_tokens, completion_tokens, elapsed_ms)    |


### 단계 8: 코드 실행


| 항목          | 내용                                                                              |
| ----------- | ------------------------------------------------------------------------------- |
| **Input**   | 생성된 Python 코드 문자열, DataFrame dict                                               |
| **Process** | `execute_pandas_code()` — AST 검증 → 임시 디렉터리 → 서브프로세스 실행 (60초 제한)                 |
| **Output**  | `result` dict (dataframe: DataFrame, chart_bytes: PNG 바이트, shape: {rows, cols}) |


### 단계 9: 응답 표시


| 항목          | 내용                                                                                                  |
| ----------- | --------------------------------------------------------------------------------------------------- |
| **Input**   | 결과 DataFrame, 차트 PNG, trace 정보                                                                      |
| **Process** | `_append_assistant_turn()` → `messages` 추가 → `_autosave_messages()` → `render_message_with_trace()` |
| **Output**  | 브라우저 화면에 표/차트/실행추적 렌더링, `results/chat_live_*.md`에 저장                                                |


---

---

## 요약

1. **SW Technology는 `streamlit run app.py`(포트 8502)로 실행되는 단일 Python 웹 애플리케이션**이며, 브라우저는 Streamlit 서버와 HTTP/WebSocket으로 통신합니다.
2. **질문은 `st.chat_input` → `process_message()`로 전달**되며, Persona·엑셀·모델 선택은 서버 메모리의 `st.session_state`에 저장됩니다.
3. **Persona는 단순 문자열 붙이기가 아니라, `prepare_persona_execution()` 파이프라인**으로 의도 감지 → 도구 선택 → 실행 경로 분기 → 구조화 프롬프트 생성까지 수행합니다.
4. **LLM은 Ollama(localhost:11434)를 통해 호출**됩니다. tool_response/template_code 경로는 LLM 없이 응답할 수 있으며, VRAM 부족 시 자동으로 경량 모델로 전환됩니다.
5. **생성된 코드는 샌드박스(서브프로세스)에서 실행**되며, 사용자 승인 후 실행이 기본입니다.
6. **응답은 `messages` + trace로 세션에 저장되고 `results/chat_*.md`에 자동 저장**된 뒤, `render_message_with_trace()`로 표/차트/추적 정보가 브라우저에 표시됩니다.

