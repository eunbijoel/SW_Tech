"""실행 추적 UI — 프롬프트·thinking·토큰·코드 확인."""
from __future__ import annotations

import time
from datetime import timedelta
from typing import Any, Callable, Optional

import streamlit as st


def tokens_dict_from_result(result: Any) -> dict[str, int]:
    if hasattr(result, "prompt_tokens"):
        return {
            "prompt": int(result.prompt_tokens),
            "completion": int(result.completion_tokens),
            "total": int(result.total_tokens),
        }
    if isinstance(result, dict):
        return {
            "prompt": int(result.get("prompt_tokens") or result.get("prompt") or 0),
            "completion": int(result.get("completion_tokens") or result.get("completion") or 0),
            "total": int(result.get("total_tokens") or result.get("total") or 0),
        }
    return {"prompt": 0, "completion": 0, "total": 0}


def merge_trace_metrics(trace: dict[str, Any], *, extra_ms: float = 0) -> dict[str, Any]:
    out = dict(trace)
    elapsed = float(out.get("elapsed_ms") or 0) + extra_ms
    if elapsed > 0:
        out["elapsed_ms"] = elapsed
    return out


def model_wait_hint(model: str) -> None:
    """대형 모델 대기 안내."""
    m = (model or "").lower()
    if any(x in m for x in ("30b", "31b", "32b", "34b", "70b", "120b", "27b")):
        st.warning(
            f"모델 **`{model}`** 은(는) 코드 생성에 **1~5분** 걸릴 수 있습니다. "
            "아래 진행 상황과 실시간 출력을 확인하세요. "
            "빠르게 하려면 사이드바에서 **qwen2.5:7b** 등 작은 모델을 선택하세요."
        )
    else:
        st.info(f"모델 `{model}` 로 처리 중입니다. 아래 진행 단계를 확인하세요.")


def start_busy_timer(label: str) -> None:
    st.session_state["_busy_since"] = time.time()
    st.session_state["_busy_label"] = label


def stop_busy_timer() -> None:
    st.session_state.pop("_busy_since", None)
    st.session_state.pop("_busy_label", None)


def render_busy_timer_fragment() -> None:
    """사이드바 경과 시간 (1초마다 갱신)."""

    @st.fragment(run_every=timedelta(seconds=1))
    def _tick() -> None:
        t0 = st.session_state.get("_busy_since")
        if not t0:
            return
        label = st.session_state.get("_busy_label", "처리 중")
        elapsed = time.time() - float(t0)
        st.caption(f"⏱ **{label}** — {elapsed:.0f}초 경과")

    _tick()


PIPELINE_STAGES: tuple[tuple[str, str], ...] = (
    ("input", "① 프롬프트 입력"),
    ("persona", "② Persona 적용"),
    ("enhance", "③ 강화 Prompt 생성"),
    ("thinking", "④ Thinking Process"),
    ("confirm", "⑤ 실행 여부 확인"),
    ("run", "⑥ Python 실행"),
    ("result", "⑦ 결과 출력"),
)


def render_pipeline_tracker(current_stage: str) -> None:
    """실행 승인 파이프라인 단계 표시."""
    st.markdown("**실행 파이프라인**")
    cols = st.columns(len(PIPELINE_STAGES))
    stage_ids = [s[0] for s in PIPELINE_STAGES]
    cur_idx = stage_ids.index(current_stage) if current_stage in stage_ids else -1
    for i, (sid, label) in enumerate(PIPELINE_STAGES):
        with cols[i]:
            if i < cur_idx:
                st.markdown(f"✅ {label}")
            elif i == cur_idx:
                st.markdown(f"**▶ {label}**")
            else:
                st.markdown(f"○ {label}")


def render_live_progress(
    trace: dict[str, Any],
    *,
    current_step: str = "",
    show_prompts: bool = True,
) -> None:
    """처리 중에도 보이는 진행 패널 (expander 밖)."""
    steps = trace.get("thinking_steps") or []
    if steps or current_step:
        st.markdown("**진행 상황**")
    for step in steps:
        if isinstance(step, dict):
            label = step.get("label", "")
            detail = step.get("detail", "")
            line = f"✅ **{label}**"
            if detail:
                line += f" — {detail}"
            st.markdown(line)
        else:
            st.markdown(f"✅ {step}")
    if current_step:
        st.markdown(f"⏳ **{current_step}** …")

    if show_prompts:
        if trace.get("user_prompt"):
            with st.expander("원본 프롬프트", expanded=False):
                st.text(trace["user_prompt"])
        if trace.get("enhanced_prompt"):
            with st.expander("강화된 프롬프트", expanded=False):
                st.code(trace["enhanced_prompt"][:5000], language=None)


def render_execution_trace(trace: dict[str, Any] | None, *, expanded: bool = True) -> None:
    if not trace:
        return

    with st.expander("🔍 실행 상세", expanded=expanded):
        st.markdown("**원본 프롬프트**")
        st.text(trace.get("user_prompt") or "(없음)")

        if trace.get("enhanced_prompt"):
            st.markdown("**페르소나 강화 프롬프트**")
            st.code(trace["enhanced_prompt"][:8000], language=None)

        steps = trace.get("thinking_steps") or []
        if steps:
            st.markdown("**Thinking process**")
            for i, step in enumerate(steps, 1):
                if isinstance(step, dict):
                    label = step.get("label", f"Step {i}")
                    detail = step.get("detail", "")
                    st.markdown(f"{i}. **{label}**")
                    if detail:
                        st.caption(detail)
                else:
                    st.markdown(f"{i}. {step}")

        if trace.get("thinking"):
            st.markdown("**모델 Thinking**")
            st.text_area(
                "thinking",
                value=trace["thinking"][:6000],
                height=120,
                disabled=True,
                label_visibility="collapsed",
            )

        metrics_cols = st.columns(2)
        elapsed = trace.get("elapsed_ms")
        if elapsed is not None:
            metrics_cols[0].metric("실행 시간", f"{float(elapsed):.0f} ms")
        tok = trace.get("tokens") or {}
        if tok and (tok.get("total") or tok.get("prompt")):
            metrics_cols[1].metric(
                "토큰 (prompt / completion)",
                f"{tok.get('prompt', 0):,} / {tok.get('completion', 0):,}",
            )
            st.caption(f"합계 {tok.get('total', 0):,} tokens")

        if trace.get("generated_code"):
            st.markdown("**생성된 코드**")
            st.code(trace["generated_code"], language="python")

        if trace.get("status") == "awaiting_exec_confirm":
            st.info("아래 **이대로 실행**을 누르면 샌드박스에서 코드가 실행됩니다.")


def render_message_with_trace(msg: dict[str, Any]) -> None:
    """채팅 버블 — trace + 본문."""
    trace = msg.get("trace")
    if trace and msg.get("role") == "assistant":
        render_execution_trace(trace, expanded=msg.get("trace_expanded", False))
    elif trace and msg.get("role") == "user" and trace.get("enhanced_prompt"):
        with st.expander("입력 · 강화 프롬프트", expanded=False):
            st.text(trace.get("user_prompt") or msg.get("content", ""))
            st.code(trace["enhanced_prompt"][:4000], language=None)
    content = msg.get("content") or ""
    if content:
        st.markdown(content, unsafe_allow_html=True)


def render_pending_excel_confirm(pending: dict[str, Any]) -> bool:
    """코드 실행 확인 UI. True if rerun should happen from button."""
    render_pipeline_tracker("confirm")
    render_execution_trace(pending.get("trace"), expanded=True)
    code = pending.get("code") or ""
    if code:
        st.code(code, language="python")
    st.markdown("**이대로 실행할까요?**")
    c1, c2 = st.columns(2)
    confirmed = c1.button("✅ 이대로 실행", type="primary", use_container_width=True, key="confirm_excel_run")
    cancelled = c2.button("❌ 취소", use_container_width=True, key="cancel_excel_run")
    if confirmed:
        st.session_state["_excel_confirm_action"] = "run"
        return True
    if cancelled:
        st.session_state["_excel_confirm_action"] = "cancel"
        return True
    return False
