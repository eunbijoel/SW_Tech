# SW_Tech 정량 벤치마크

일반 Prompt vs Persona 보강 Prompt, 그리고 Foundation Model별 응답을 **수치로 비교**하는 CLI입니다.

## 무엇을 재나요?

| 지표 | 설명 |
|------|------|
| `elapsed_ms` | Ollama 응답 시간 |
| `prompt_tokens` / `completion_tokens` / `total_tokens` | 토큰 사용량 |
| `prompt_chars` / `enhanced_chars` / `enhancement_ratio` | 보강 전·후 프롬프트 길이 |
| `instruction_score` | 케이스별 규칙(필수·금지 키워드) 준수율 0~1 |
| `code_extracted` / `sandbox_ok` | 코드 추출·샌드박스 실행 성공 (codegen) |
| `execution_path` | `tool_response` / `template_code` / `llm_codegen` |

## 모드

| mode | 의미 |
|------|------|
| `plain` | 사용자 원문만 (Persona·보강 없음) |
| `persona_struct` | Persona system + 구조화 섹션 결합 프롬프트 |
| `persona_enh` | 위 + 도구 실행 + (선택) LLM 리라이트 |

## 실행

```bash
cd /home/eunbi/SW_Tech
source .venv/bin/activate

# Ollama 실행 중이어야 함
ollama serve   # 별도 터미널

# 빠른 스모크 (모델 1개, 케이스 각 1개) — persona_enh는 리라이트 LLM 없이 구조화만
python benchmarks/run_comparison.py --models qwen2.5:7b --quick

# persona_enh + LLM 리라이트까지 포함 (느림, 타임아웃 가능)
python benchmarks/run_comparison.py --models qwen2.5:7b --quick --rewrite-model qwen2.5:7b

# 전체 비교 (모델·모드·케이스 확장)
python benchmarks/run_comparison.py \
  --models qwen2.5:7b,gemma3:4b,deepseek-coder-v2:latest \
  --modes plain,persona_struct,persona_enh \
  --personas general,excel_expert,business_consultant \
  --tasks chat,codegen

# 조합만 확인
python benchmarks/run_comparison.py --dry-run
```

## 결과 위치

`results/benchmarks/<UTC타임스탬프>/`

- `runs.csv` / `runs.json` — 실행별 원시 데이터
- `summary.md` — model×mode 집계, Persona 보강 Δ 표

## 케이스 수정

`benchmarks/cases.json` 에서 프롬프트·합성 DataFrame·`checks` 규칙을 편집합니다.

```json
"checks": {
  "must_contain": ["집행률", "result"],
  "must_not_contain": ["read_excel"]
}
```

## 논문·보고용 해석 팁

1. **Prompt 보강 효과**: 같은 `case_id`·`model`에서 `plain` vs `persona_enh`의 `instruction_score`, `sandbox_ok`, `elapsed_ms` 차이
2. **모델별 특성**: 동일 `mode`에서 모델 간 `total_tokens`, `sandbox_ok%`, 평균 `instruction_score`
3. **Instruction 적용**: `persona_struct`만으로도 점수가 오르는지 vs `persona_enh` 추가 이득

실제 엑셀 파일로 돌리려면 `codegen` 케이스에 `excel/` 파일명을 넣고 `build_data_context` 경로를 확장하면 됩니다 (현재는 JSON 합성 DataFrame).

## 논문·DSR 6차원 + 정성 평가

**`benchmarks/EVALUATION.md`** — 맥락 정합성·실행 가능성·검증·안전·인간 부담·추적 가능성 + usability / prompt clarity / satisfaction 절차.

- `runs.csv` → `dsr_*` 컬럼 (자동)
- `human_review_template.csv` → 전문가 Likert 1~5
- `python benchmarks/score_saved_chats.py results/chat_*.md` → UI 세션 trace 집계
