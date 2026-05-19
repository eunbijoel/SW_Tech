"""
matplotlib 한글 폰트 설정 (Linux·Windows 공통).

rcParams에 이름만 넣으면 글리프가 없어도 예외가 나지 않아 □□□ 가 뜹니다.
설치된 폰트 파일을 font_manager로 찾아 등록합니다.
"""
from __future__ import annotations

import os
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager as fm


# 우선순위: 한국어 CJK → 나눔 → 기타
_PREFERRED_NAMES = (
    "Noto Sans CJK KR",
    "Noto Sans CJK JP",
    "Noto Sans CJK SC",
    "NanumGothic",
    "Nanum Gothic",
    "Malgun Gothic",
    "AppleGothic",
)

# Linux에 흔한 경로 (Noto CJK)
_FONT_PATHS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/AppleGothic.ttf",
    "C:/Windows/Fonts/malgun.ttf",
)

# 프로젝트 내 번들 폰트 (있으면 사용)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BUNDLED_FONTS = (
    _PROJECT_ROOT / "assets" / "fonts" / "NanumGothic.ttf",
    _PROJECT_ROOT / "assets" / "fonts" / "NotoSansCJK-Regular.ttc",
)


def _names_on_system() -> set[str]:
    return {f.name for f in fm.fontManager.ttflist}


def setup_korean_matplotlib() -> str:
    """
    한글 렌더링용 matplotlib 폰트를 설정합니다.
    Returns: 적용된 폰트 이름 (실패 시 'DejaVu Sans').
    """
    plt.rcParams["axes.unicode_minus"] = False

    available = _names_on_system()
    for name in _PREFERRED_NAMES:
        if name in available:
            plt.rcParams["font.family"] = name
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            return name

    for path in (*_BUNDLED_FONTS, *(Path(p) for p in _FONT_PATHS)):
        if not path.is_file():
            continue
        try:
            path_str = str(path)
            fm.fontManager.addfont(path_str)
            # TTC는 KR/JP 등 여러 패밀리가 함께 등록됨 → KR 우선
            for font in fm.fontManager.ttflist:
                if font.fname == path_str and "CJK KR" in font.name:
                    plt.rcParams["font.family"] = font.name
                    plt.rcParams["font.sans-serif"] = [font.name, "DejaVu Sans"]
                    return font.name
            prop = fm.FontProperties(fname=path_str)
            family = prop.get_name()
            plt.rcParams["font.family"] = family
            plt.rcParams["font.sans-serif"] = [family, "DejaVu Sans"]
            return family
        except Exception:
            continue

    # fc-list 기반 마지막 시도: Noto Sans CJK KR 포함 파일
    for font in fm.fontManager.ttflist:
        if "CJK KR" in font.name or font.name == "Noto Sans CJK KR":
            plt.rcParams["font.family"] = font.name
            plt.rcParams["font.sans-serif"] = [font.name, "DejaVu Sans"]
            return font.name

    plt.rcParams["font.family"] = "DejaVu Sans"
    return "DejaVu Sans"
