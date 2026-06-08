# SW_Tech 논문·DSR 평가 가이드

정량 벤치마크(`run_comparison.py`) + **6개 DSR 차원** + **정성(qualitative)** 을 함께 쓰는 방법입니다.

---

## 1. 평가를 두 층으로 나누기

| 층 | 누가 | 산출물 |
|----|------|--------|
| **자동 (A)** | 스크립트·로그 | `runs.csv` 의 `dsr_*` 컬럼, 토큰·시간·sandbox_ok |
| **전문가 (B)** | 연구자 1~2명 | `human_review_template.csv` 1~5점 Likert |
| **사용자 (C)** | 파일럿 3~5명 | SUS·만족도 설문 (선택) |

논문에는 **A는 재현 가능한 수치**, **B·C는 해석·한계**로 씁니다.

---

## 2. 논문 6차원 ↔ SW_Tech 매핑

| 평가 차원 | SW_Tech에서 자동으로 잡히는 것 | 전문가가 추가로 볼 것 |
|-----------|-------------------------------|----------------------|
| **맥락 정합성** | `instruction_score`, 컬럼명 사용률, `read_excel` 금지 준수 | 결과 표가 실제 엑셀·정책과 맞는지 1~5 |
| **실행 가능성** | `sandbox_ok`, `code_extracted`, `execution_path` | 재질문 없이 end-to-end인지 1~5 |
| **검증 통과** | AST 통과, 샌드박스 성공, 케이스 `checks` | 출력 스키마·집계 정의 충족 1~5 |
| **안전성/정책** | 금지 모듈·`eval` AST 차단, 샌드박스 격리 | 민감정보·외부 URL 시도 여부 1~5 |
| **인간 개입 부담** | `dsr_human_burden_inverse` (HITL 1회, 재시도 횟수) | clarification·수동 수정 횟수 관찰 |
| **추적 가능성** | `dsr_traceability` (trace JSON 필드 완전성) | `results/chat_*.md` 로 재현 가능한지 |

자동 점수는 `benchmarks/dsr_metrics.py` → `run_comparison.py` 실행 시 `runs.csv`에 붙습니다.

---

## 3. 정성(qualitative) — 어떻게 재나?

| 항목 | 측정 방식 | 시점 |
|------|-----------|------|
| **Usability** | SUS 10문항 (표준) 또는 과제 후 5문항 축약 | 파일럿 종료 직후 |
| **Prompt clarity** | 전문가가 강화 프롬프트만 보고 1~5 (구조·중복·실행 지시 명확성) | 벤치마크 MD·`enhanced_prompt` 샘플 10건 |
| **User satisfaction** | 「요구 충족」「다시 쓸 의향」 Likert 1~5 | 과제당 1회 |

**권장 과제 세트 (동일 엑셀 3파일)**

1. 파일별 데이터 범위 (FILE_META) — 엑셀 전문가  
2. 집행률 표 정렬 — 데이터 분석가  
3. 3파일 병합·평균 — 일반/비즈니스  

각 과제를 **plain / persona_enh** × **모델 2종** 으로 돌리면 논문 표 하나를 채울 수 있습니다.

---

## 4. 실행 순서 (권장)

### Step A — 자동 벤치마크 + DSR 점수

```bash
cd /home/eunbi/SW_Tech && source .venv/bin/activate
python benchmarks/run_comparison.py \
  --models qwen2.5:7b,gemma3:4b \
  --modes plain,persona_struct,persona_enh \
  --tasks chat,codegen
```

→ `results/benchmarks/<ts>/runs.csv`  
컬럼: `dsr_context_alignment`, `dsr_executability`, … `dsr_traceability`

### Step B — UI 세션 trace 재평가 (선택)

실제 Streamlit 사용 후 `results/chat_*.md` 가 쌓이면:

```bash
python benchmarks/score_saved_chats.py results/chat_*.md
```

→ trace 완전성·HITL 여부 집계

### Step C — 전문가·정성

1. `benchmarks/human_review_template.csv` 복사  
2. 각 run_id / chat 파일마다 1~5 입력  
3. 논문용: 평균·표준편차· Cohen's κ (전문가 2인 시)

---

## 5. 논문 표 예시 (자동 층만)

**표 1. 조건별 DSR 자동 지표 (평균, n=케이스 수)**

| 조건 | 맥락 | 실행가능 | 검증 | 안전 | 인간부담↓ | 추적 |
|------|------|----------|------|------|-----------|------|
| plain + qwen2.5:7b | 0.82 | 0.45 | 0.71 | 1.00 | 0.65 | 0.40 |
| persona_enh + qwen2.5:7b | 0.88 | 0.78 | 0.85 | 1.00 | 0.55 | 0.92 |

**표 2. 정성 (파일럿 n=5, Likert 1~5)**

| 항목 | plain | persona_enh |
|------|-------|-------------|
| Usability (SUS 환산) | … | … |
| Prompt clarity (전문가) | … | … |
| User satisfaction | … | … |

---

## 6. 한계 (Discussion에 쓸 문장)

- 자동 `instruction_score`는 키워드 규칙 기반이라 **맥락 정합성의 하한 추정**입니다.  
- **전문가 평가**와 상관을 보고하면 설계 타당성을 보강할 수 있습니다.  
- `persona_enh`는 trace·토큰이 늘어 **추적 가능성은 올라가나** 인간 승인(HITL)이 있으면 부담 점수는 낮아질 수 있습니다.

---

## 7. 케이스·규칙 확장

`benchmarks/cases.json` 의 `checks` 를 도메인 정책에 맞게 늘리면 **검증·맥락** 자동 점수가 논문 도메인에 맞춰집니다.

```json
"checks": {
  "must_contain": ["집행률", "df_0"],
  "must_not_contain": ["read_excel", "pd.concat"],
  "required_columns": ["계획예산", "당해집행"]
}
```

`required_columns` 는 `dsr_metrics` 확장 시 반영 가능합니다.
