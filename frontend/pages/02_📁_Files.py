"""
Files page — 라이브러리 파일 + 업로드 파일을 AI로 처리.

섹션:
  1. 분석 파일 라이브러리 — excel/ 디렉토리의 사전 적재 파일 (예실대비표 등)
  2. 내 업로드 파일 — 사용자가 직접 올린 파일
  3. AI 처리 패널 — 선택 파일 + 프롬프트 → pandas 코드 생성 → 결과 테이블
"""
import pandas as pd
import streamlit as st

from frontend.components.file_manager import render_file_table, render_upload_zone
from frontend.utils.api_client import (
    chat_excel,
    list_files,
    list_library_files,
    list_models,
)
from frontend.utils.session import init_session

st.set_page_config(page_title="Files · AI Prompt Platform", page_icon="📁", layout="wide")
init_session()

session_id: str = st.session_state.get("session_id", "")

st.title("📁 파일 관리 & AI 처리")

# ── 예실대비표 분석 프롬프트 템플릿 ──────────────────────────────────────────
PROMPT_TEMPLATES = {
    "선택하세요...": "",
    "월별 예산 집행 현황 비교": (
        "각 파일은 월별 예실대비표입니다. 파일명에서 월(4월, 5월, 7월 등)을 추출하여 "
        "'월' 컬럼을 추가한 뒤 세 파일을 하나로 합쳐주세요. "
        "결과에는 분류, 세목명, 월, 계획예산(합계), 당기도달액(합계), 잔액(합계) 컬럼을 포함해주세요."
    ),
    "항목별 예산 집행률 계산": (
        "수정예산 합계 대비 당기도달액 합계의 비율을 계산하여 '집행률(%)' 컬럼을 추가해 주세요. "
        "집행률이 높은 순서로 정렬하고, 분류·세목명·계획예산·수정예산합계·당기도달액합계·집행률 컬럼을 출력하세요."
    ),
    "잔액 상위 10개 항목": (
        "세출잔액 기준 상위 10개 항목을 추출해 주세요. "
        "분류, 세목명, 수정예산합계, 당기도달액합계, 세출잔액 컬럼을 포함하고 잔액 내림차순으로 정렬하세요."
    ),
    "소계/합계 행 제외 항목 목록": (
        "소계, 합계, NaN 등 집계 행을 제외하고 실제 세목 데이터 행만 추출해 주세요. "
        "목코드, 세목명, 계획예산, 당기도달액합계, 잔액합계를 보여주세요."
    ),
    "3개월 통합 집행 요약": (
        "세 파일(4월, 5월, 7월)을 합쳐서 세목명 기준으로 그룹화하고, "
        "계획예산 평균, 당기도달액합계 합산, 세출잔액 합산을 계산해 주세요."
    ),
}

# ═══════════════════════════════════════════════════════════════════════════════
# 섹션 1 — 분석 파일 라이브러리
# ═══════════════════════════════════════════════════════════════════════════════
st.subheader("📚 분석 파일 라이브러리")
st.caption("excel/ 폴더에 있는 사전 적재 파일입니다. 삭제 불가.")

try:
    library_files = list_library_files()
except Exception as e:
    st.warning(f"라이브러리 파일 불러오기 실패: {e}")
    library_files = []

lib_selected: list[str] = []
if library_files:
    for f in library_files:
        col_chk, col_icon, col_name, col_size, col_badge = st.columns([0.4, 0.3, 4, 1.2, 1.2])
        with col_chk:
            if st.checkbox("", key=f"lib_{f['id']}", label_visibility="collapsed"):
                lib_selected.append(f["id"])
        with col_icon:
            st.write("📊")
        with col_name:
            st.write(f"**{f['original_name']}**")
        with col_size:
            st.caption(f"{f['size_bytes'] / 1024:.1f} KB")
        with col_badge:
            st.markdown(
                "<span style='background:#e8f4f8;color:#1a6fa0;padding:2px 8px;"
                "border-radius:4px;font-size:0.75rem'>라이브러리</span>",
                unsafe_allow_html=True,
            )
else:
    st.info("excel/ 폴더에 파일이 없습니다.")

st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
# 섹션 2 — 내 업로드 파일
# ═══════════════════════════════════════════════════════════════════════════════
st.subheader("⬆️ 내 업로드 파일")

with st.expander("새 파일 업로드", expanded=False):
    new_files = render_upload_zone(session_id=session_id)
    if new_files:
        st.rerun()

try:
    uploaded_files = list_files(session_id=session_id)
except Exception as e:
    st.error(f"업로드 파일 불러오기 실패: {e}")
    uploaded_files = []

upload_selected: list[str] = []
if uploaded_files:
    upload_selected = render_file_table(uploaded_files, show_select=True)
    st.caption(f"{len(uploaded_files)}개 파일 · {len(upload_selected)}개 선택")
else:
    st.info("업로드한 파일이 없습니다.")

st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
# 섹션 3 — AI 처리 패널
# ═══════════════════════════════════════════════════════════════════════════════
all_selected: list[str] = lib_selected + upload_selected

st.subheader("🤖 AI 처리")

if not all_selected:
    st.info("위에서 파일을 하나 이상 선택하면 AI 처리 패널이 활성화됩니다.")
else:
    # 선택된 파일 이름 표시
    all_files_map = {f["id"]: f["original_name"] for f in library_files + uploaded_files}
    selected_names = [all_files_map.get(fid, fid) for fid in all_selected]
    st.success(f"선택된 파일 {len(all_selected)}개: **{', '.join(selected_names)}**")

    # 프롬프트 템플릿 선택
    template_key = st.selectbox(
        "분석 템플릿 (선택 후 수정 가능)",
        list(PROMPT_TEMPLATES.keys()),
        key="template_select",
    )

    col_left, col_right = st.columns([3, 1])

    with col_left:
        default_prompt = PROMPT_TEMPLATES.get(template_key, "")
        prompt = st.text_area(
            "AI에게 무엇을 할지 알려주세요",
            value=default_prompt,
            height=130,
            placeholder=(
                "예: 세 파일을 합쳐서 세목명별 예산 집행률을 계산하고 집행률 내림차순으로 정렬해 주세요."
            ),
        )

    with col_right:
        try:
            model_map = list_models()
            all_models: list[str] = [m for names in model_map.values() for m in names]
        except Exception:
            all_models = []
        if not all_models:
            all_models = ["gpt-4o"]

        proc_model = st.selectbox("모델", all_models, key="proc_model")
        executor = st.selectbox(
            "실행 환경",
            ["local", "gpu", "spark"],
            help="local: 이 서버 | gpu: RTX 5090 서버 | spark: 분산 처리",
        )
        save_result = st.toggle("결과 저장", value=True)

    run_btn = st.button(
        "▶  AI 분석 실행",
        type="primary",
        disabled=not prompt.strip(),
        use_container_width=False,
    )

    if run_btn:
        with st.spinner("분석 중… 최대 60초 소요될 수 있습니다."):
            try:
                result = chat_excel(
                    file_ids=all_selected,
                    prompt=prompt,
                    model=proc_model,
                    executor=executor,
                )
            except Exception as e:
                st.error(f"처리 실패: {e}")
                result = None

        if result:
            error = result.get("error")
            if error:
                st.error(f"실행 오류:\n```\n{error}\n```")
            else:
                shape = result.get("result_shape")
                st.success(
                    f"완료! 결과: {shape['rows']}행 × {shape['cols']}열"
                    if shape else "완료!"
                )

                # 결과 테이블
                preview = result.get("result_preview")
                if preview:
                    df_preview = pd.DataFrame(preview)
                    st.dataframe(
                        df_preview,
                        use_container_width=True,
                        height=min(400, 40 + len(df_preview) * 35),
                    )

                    # CSV 다운로드
                    csv_bytes = df_preview.to_csv(index=False, encoding="utf-8-sig").encode()
                    st.download_button(
                        "CSV 다운로드",
                        data=csv_bytes,
                        file_name="ai_result.csv",
                        mime="text/csv",
                    )

                # 생성된 코드
                code = result.get("code", "")
                if code:
                    with st.expander("생성된 pandas 코드 보기", expanded=False):
                        st.code(code, language="python")

                # 설명
                explanation = result.get("explanation", "")
                if explanation:
                    with st.expander("결과 설명", expanded=True):
                        st.info(explanation)

                # 저장 경로 안내
                col_xl, col_md = st.columns(2)
                if result.get("saved_excel"):
                    col_xl.success(f"Excel 저장됨: `{result['saved_excel']}`")
                if result.get("saved_markdown"):
                    col_md.success(f"Markdown 저장됨: `{result['saved_markdown']}`")
