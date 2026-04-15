import streamlit as st
import os
import re
import zipfile
import warnings
from io import BytesIO
from datetime import datetime, timedelta, timezone

import requests
from PIL import Image
from fpdf import FPDF
import gdown

warnings.filterwarnings('ignore')

st.set_page_config(page_title="책 표지 메이커", page_icon="📚")

# ── 상수 ──────────────────────────────────────────────────────────────
PAGE_W_MM = 210
MARGIN_MM = 10
DPI       = 300
GAP_MM    = 1

SERIES = {
    "민음사 세계문학전집":    {"id": "1A3Zik6ak8djGmVLYHL-2ct5pF0dshyfW", "folder": "minumsa"},
    "문학동네 세계문학전집":  {"id": "1jQcPpfZ6FLigQbvU5RZEcVS3KTvOMK1K", "folder": "munhakdongne"},
    "문학동네 먼슬리 클래식": {"id": "1j2NygAXhAh5j3SeeoY5GCEIbevpnB3-y", "folder": "monthly_classic"},
    "은행나무 세계문학 에세": {"id": "1kUkjIebu6vUdIw1SfJG44pwo6wbBv32_", "folder": "eunhaengnamu"},
    "블루홀식스":            {"id": "1xNRNrbKrdERCY9gnHrjsagr2wRKSWVsf", "folder": "blueholesix"},
}

# ── 비밀번호 (매주 월요일 오전 10시 KST 변경) ──────────────────────────
_KST         = timezone(timedelta(hours=9))
_PASSWD_START = datetime(2026, 4, 15, 10, 0, 0, tzinfo=_KST)   # 최초 비밀번호 적용 시각

def _load_password_list():
    """비밀번호목록.txt 에서 한 줄에 하나씩 읽어 반환."""
    passwords = []
    try:
        with open("비밀번호목록.txt", "r", encoding="utf-8") as f:
            for line in f:
                pw = line.strip()
                if pw:
                    passwords.append(pw)
    except Exception:
        pass
    return passwords

_PASSWORD_LIST = _load_password_list()

def get_current_password():
    now = datetime.now(_KST)
    if not _PASSWORD_LIST:
        return None
    if now < _PASSWD_START:
        idx = 0
    else:
        weeks_elapsed = (now - _PASSWD_START).days // 7
        idx = weeks_elapsed % len(_PASSWORD_LIST)
    return _PASSWORD_LIST[idx]

# ── CSS ───────────────────────────────────────────────────────────────
def inject_css():
    st.markdown("""
    <style>
    .main .block-container { max-width: 760px; padding-top: 2.5rem; padding-bottom: 3rem; }
    .stButton > button {
        width: 100%;
        background: linear-gradient(135deg, #3D6B9E, #2C4F7C);
        color: white !important; border: none; border-radius: 10px;
        padding: 0.65rem 1.5rem; font-size: 1rem; font-weight: 600;
        letter-spacing: 0.02em; transition: opacity 0.2s, transform 0.1s;
    }
    .stButton > button:hover  { opacity: 0.88; transform: translateY(-1px); border: none; }
    .stButton > button:active { transform: translateY(0px); }
    .stDownloadButton > button {
        width: 100%;
        background: linear-gradient(135deg, #2D7A4F, #1F5C3A);
        color: white !important; border: none; border-radius: 10px;
        padding: 0.65rem 1.5rem; font-size: 1rem; font-weight: 600;
        transition: opacity 0.2s, transform 0.1s;
    }
    .stDownloadButton > button:hover { opacity: 0.88; transform: translateY(-1px); }
    .stTextInput input, .stTextArea textarea {
        border-radius: 8px; border: 1.5px solid #D4CFC8; background: white;
        font-size: 0.95rem; transition: border-color 0.2s, box-shadow 0.2s;
    }
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: #3D6B9E; box-shadow: 0 0 0 3px rgba(61,107,158,0.12);
    }
    .stRadio label, .stSlider label { font-weight: 500; color: #4A4A4A; }
    .stSuccess, .stWarning, .stError { border-radius: 10px; }
    hr { border: none; border-top: 1px solid #DDD8D0; margin: 1.8rem 0; }
    </style>
    """, unsafe_allow_html=True)

# ── Google Drive 다운로드 (서버 재시작 전까지 캐시 유지) ────────────────
@st.cache_resource(show_spinner=False)
def download_series(series_key: str) -> str:
    """ZIP을 Google Drive에서 받아 /tmp에 압축 해제, 폴더 경로 반환"""
    info    = SERIES[series_key]
    tmp_dir = f"/tmp/{info['folder']}"
    if os.path.exists(tmp_dir) and os.listdir(tmp_dir):
        return tmp_dir
    os.makedirs(tmp_dir, exist_ok=True)
    zip_path = f"/tmp/{info['folder']}.zip"
    gdown.download(id=info['id'], output=zip_path, quiet=True)
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(tmp_dir)
    os.remove(zip_path)
    return tmp_dir

# ── 이미지 / 파일 생성 유틸 ───────────────────────────────────────────
def load_images(folder: str, target_height_mm: float):
    target_h_px = int((target_height_mm / 25.4) * DPI)
    results = []
    for filename in sorted(os.listdir(folder)):
        if not filename.lower().endswith('.png'):
            continue
        try:
            img   = Image.open(os.path.join(folder, filename)).convert("RGB")
            ratio = target_h_px / img.height
            img_r = img.resize((max(1, int(img.width * ratio)), target_h_px), Image.Resampling.LANCZOS)
            title = re.sub(r'^\d+_', '', os.path.splitext(filename)[0])
            results.append((img_r, title, ""))
        except Exception:
            continue
    return results

def find_korean_font():
    for p in [
        "C:/Windows/Fonts/malgun.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]:
        if os.path.exists(p): return p
    return None

def build_pdf(results, target_height_mm: float) -> bytes:
    FONT_PT = 6; TEXT_H_MM = 4
    pdf = FPDF(); pdf.add_page()
    fp = find_korean_font(); has_font = False
    if fp:
        try:
            pdf.add_font("K", fname=fp); pdf.set_font("K", size=FONT_PT); has_font = True
        except Exception:
            pass
    if not has_font:
        pdf.set_font("Helvetica", size=FONT_PT)

    x, y   = MARGIN_MM, MARGIN_MM
    row_h  = target_height_mm + TEXT_H_MM + GAP_MM

    for i, (img, title, _) in enumerate(results):
        tmp = f"/tmp/_cover_{i}.png"; img.save(tmp)
        w_mm = (img.width / DPI) * 25.4
        if x + w_mm > PAGE_W_MM - MARGIN_MM:
            x = MARGIN_MM; y += row_h
        if y + row_h > 280:
            pdf.add_page(); y = MARGIN_MM; x = MARGIN_MM
        pdf.image(tmp, x=x, y=y, h=target_height_mm)
        if has_font:
            pdf.set_xy(x, y + target_height_mm + 0.5)
            pdf.cell(w_mm, TEXT_H_MM - 0.5, txt=title[:30])
        x += w_mm + GAP_MM
        os.remove(tmp)

    out_path = "/tmp/_result.pdf"; pdf.output(out_path)
    with open(out_path, "rb") as f: data = f.read()
    os.remove(out_path)
    return data

def build_zip(results) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, (img, title, _) in enumerate(results):
            b    = BytesIO(); img.save(b, format="PNG")
            safe = re.sub(r'[\\/:*?"<>|]', '', title).strip()
            zf.writestr(f"{i+1:03d}_{safe}.png", b.getvalue())
    return buf.getvalue()

# ── 네이버 API (검색하여 받기) ────────────────────────────────────────
def get_cover_from_naver(book_title, publisher, target_height_mm):
    try:
        headers = {
            "X-Naver-Client-Id":     st.secrets["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": st.secrets["NAVER_CLIENT_SECRET"],
        }
        query  = f"{book_title} {publisher}".strip() if publisher else book_title
        res    = requests.get("https://openapi.naver.com/v1/search/book.json",
                              headers=headers, params={"query": query, "display": 1}, timeout=10)
        res.raise_for_status()
        items  = res.json().get("items", [])
        if not items: return None, ""
        item   = items[0]
        img_url = item.get("image", "")
        api_pub = item.get("publisher", "")
        if not img_url: return None, api_pub
        ir = requests.get(img_url, timeout=10)
        if ir.status_code != 200: return None, api_pub
        img = Image.open(BytesIO(ir.content))
        th  = int((target_height_mm / 25.4) * DPI)
        tw  = int(img.width * th / img.height)
        return img.resize((tw, th), Image.Resampling.LANCZOS), api_pub
    except Exception:
        return None, ""

# ══════════════════════════════════════════════════════════════════════
# 페이지 함수
# ══════════════════════════════════════════════════════════════════════

def show_login():
    inject_css()
    st.markdown("""
    <div style="text-align:center; padding:2rem 0 2.5rem 0;">
        <div style="font-size:3rem; margin-bottom:0.5rem;">📚</div>
        <h1 style="font-size:2rem; color:#2C4F7C; margin:0 0 0.5rem 0; font-weight:700;">책 표지 수집기</h1>
        <p style="color:#8A8278; font-size:0.95rem; margin:0;">이번 주 입장 코드를 입력하세요</p>
    </div>""", unsafe_allow_html=True)

    pw = st.text_input("입장 코드", type="password", label_visibility="collapsed",
                       placeholder="입장 코드를 입력하세요")
    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
    if st.button("입장하기"):
        correct = get_current_password()
        if correct is None:
            st.error("이번 주 비밀번호가 설정되지 않았습니다. 관리자에게 문의하세요.")
        elif pw == correct:
            st.session_state["authenticated"] = True
            st.session_state["page"] = "main"
            st.rerun()
        else:
            st.error("입장 코드가 올바르지 않습니다.")


def show_main():
    inject_css()
    st.markdown("""
    <div style="padding:1rem 0 2.5rem 0;">
        <h1 style="font-size:1.9rem; color:#2C4F7C; margin:0 0 0.4rem 0; font-weight:700;">📚 책 표지 수집기</h1>
        <p style="color:#8A8278; font-size:0.95rem; margin:0;">원하는 방식을 선택하세요</p>
    </div>""", unsafe_allow_html=True)

    col1, col2 = st.columns(2, gap="large")
    with col1:
        st.markdown("""
        <div style="background:white; border:2px solid #E8E4DC; border-radius:16px;
                    padding:2rem 1.5rem; text-align:center; margin-bottom:0.8rem; min-height:160px;">
            <div style="font-size:2.4rem; margin-bottom:0.7rem;">📦</div>
            <div style="font-size:1.05rem; font-weight:700; color:#2C4F7C; margin-bottom:0.4rem;">한번에 몰아 받기</div>
            <div style="font-size:0.82rem; color:#8A8278; line-height:1.5;">
                저장된 시리즈 표지를<br>바로 PDF / PNG로 다운로드
            </div>
        </div>""", unsafe_allow_html=True)
        if st.button("📦  몰아 받기", key="go_bulk"):
            st.session_state["page"] = "bulk"
            st.session_state.pop("bulk_series", None)
            st.rerun()

    with col2:
        st.markdown("""
        <div style="background:white; border:2px solid #E8E4DC; border-radius:16px;
                    padding:2rem 1.5rem; text-align:center; margin-bottom:0.8rem; min-height:160px;">
            <div style="font-size:2.4rem; margin-bottom:0.7rem;">🔍</div>
            <div style="font-size:1.05rem; font-weight:700; color:#2C4F7C; margin-bottom:0.4rem;">검색하여 받기</div>
            <div style="font-size:0.82rem; color:#8A8278; line-height:1.5;">
                책 제목으로 직접 검색해<br>표지를 자동 수집
            </div>
        </div>""", unsafe_allow_html=True)
        if st.button("🔍  검색 시작", key="go_search"):
            st.session_state["page"] = "search"
            st.rerun()


def show_bulk():
    inject_css()
    if st.button("← 뒤로", key="bulk_back"):
        st.session_state["page"] = "main"
        st.session_state.pop("bulk_series", None)
        st.rerun()

    st.markdown("""
    <div style="padding:0.5rem 0 1.5rem 0;">
        <h2 style="font-size:1.6rem; color:#2C4F7C; margin:0 0 0.3rem 0; font-weight:700;">📦 한번에 몰아 받기</h2>
        <p style="color:#8A8278; font-size:0.88rem; margin:0;">받고 싶은 시리즈를 선택하세요</p>
    </div>""", unsafe_allow_html=True)

    selected = st.session_state.get("bulk_series", None)
    cols = st.columns(len(SERIES))
    for i, name in enumerate(SERIES):
        with cols[i]:
            is_sel  = (selected == name)
            border  = "#3D6B9E" if is_sel else "#E8E4DC"
            bg      = "#EEF4FB" if is_sel else "white"
            fw      = "700"     if is_sel else "500"
            st.markdown(f"""
            <div style="background:{bg}; border:2px solid {border}; border-radius:12px;
                        padding:0.9rem 0.4rem; text-align:center; margin-bottom:0.4rem;">
                <div style="font-size:0.78rem; font-weight:{fw}; color:#2C4F7C;
                            line-height:1.4;">{name}</div>
            </div>""", unsafe_allow_html=True)
            if st.button("선택" if not is_sel else "✓ 선택됨", key=f"sel_{i}"):
                st.session_state["bulk_series"] = name
                st.rerun()

    if not selected:
        return

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown(f"<p style='font-weight:600; color:#2C4F7C; margin-bottom:1rem;'>✅ {selected}</p>",
                unsafe_allow_html=True)

    col_a, col_b = st.columns([3, 2])
    with col_a:
        height_cm = st.slider("표지 높이 (최대 5cm)", min_value=1.0, max_value=5.0,
                              value=3.0, step=0.5, format="%.1f cm")
    with col_b:
        fmt = st.radio("저장 형식", ["PDF", "PNG"], horizontal=True, key="bulk_fmt")

    if st.button("🚀  만들기 시작", key="bulk_gen"):
        # 1. Google Drive에서 다운로드 (캐시됨)
        with st.spinner(f"'{selected}' 이미지 준비 중… (첫 실행 시 다운로드 포함)"):
            try:
                folder = download_series(selected)
            except Exception as e:
                st.error(f"다운로드 실패: {e}")
                return

        # 2. 이미지 로드 & 리사이즈
        with st.spinner("이미지 처리 중…"):
            results = load_images(folder, height_cm * 10)

        if not results:
            st.error("이미지를 찾을 수 없습니다.")
            return

        # 3. 파일 생성 & 다운로드
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = re.sub(r'[^\w]', '_', selected)

        with st.spinner("파일 생성 중…"):
            if fmt == "PDF":
                data = build_pdf(results, height_cm * 10)
                st.success(f"완료! {len(results)}권 → PDF")
                st.download_button("📥  PDF 다운로드", data=data,
                                   file_name=f"{base}_{ts}.pdf", mime="application/pdf")
            else:
                data = build_zip(results)
                st.success(f"완료! {len(results)}권 → PNG ZIP")
                st.download_button("📥  PNG ZIP 다운로드", data=data,
                                   file_name=f"{base}_{ts}.zip", mime="application/zip")


def show_search():
    inject_css()
    if st.button("← 뒤로", key="search_back"):
        st.session_state["page"] = "main"
        st.rerun()

    st.markdown("""
    <div style="padding:0.5rem 0 2rem 0;">
        <h2 style="font-size:1.6rem; color:#2C4F7C; margin:0 0 0.4rem 0; font-weight:700;">🔍 검색하여 받기</h2>
        <p style="color:#8A8278; font-size:0.95rem; margin:0;">책 제목을 입력하면 인쇄용 파일을 자동으로 만들어드립니다</p>
    </div>""", unsafe_allow_html=True)

    col1, col2 = st.columns([3, 2])
    with col1:
        height_cm = st.slider("표지 높이 (최대 5cm)", min_value=1.0, max_value=5.0,
                              value=3.0, step=0.5, format="%.1f cm")
    with col2:
        fmt = st.radio("저장 형식", ["PDF", "PNG"], horizontal=True, key="search_fmt")

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown("<p style='font-weight:500; color:#4A4A4A; margin-bottom:0.3rem;'>책 목록</p>",
                unsafe_allow_html=True)
    st.markdown("<p style='font-size:0.82rem; color:#9A9690; margin-bottom:0.5rem;'>"
                "한 줄에 한 권씩 &nbsp;·&nbsp; 출판사는 쉼표로 구분 "
                "<code>파친코, 문학사상</code></p>", unsafe_allow_html=True)

    titles_input = st.text_area("책 목록", height=180,
                                placeholder="구름 사람들\n파친코, 문학사상\n불편한 편의점",
                                label_visibility="collapsed")

    if st.button("🚀  만들기 시작", key="search_gen"):
        lines = [l.strip() for l in titles_input.split('\n') if l.strip()]
        entries = []
        for line in lines:
            if ',' in line:
                p = line.split(',', 1)
                entries.append((p[0].strip(), p[1].strip()))
            else:
                entries.append((line.strip(), ""))

        if not entries:
            st.warning("책 제목을 먼저 입력해주세요.")
            return

        results      = []
        progress_bar = st.progress(0)
        status_text  = st.empty()

        for i, (title, pub) in enumerate(entries):
            status_text.markdown(
                f"<p style='color:#8A8278; font-size:0.9rem;'>"
                f"'{title}' 표지 찾는 중… ({i+1}/{len(entries)})</p>",
                unsafe_allow_html=True)
            img, api_pub = get_cover_from_naver(title, pub, height_cm * 10)
            if img:
                results.append((img, title, pub if pub else api_pub))
            else:
                st.toast(f"'{title}' 표지를 찾지 못했습니다.")
            progress_bar.progress((i + 1) / len(entries))

        status_text.markdown("<p style='color:#8A8278; font-size:0.9rem;'>파일 생성 중…</p>",
                             unsafe_allow_html=True)
        if not results:
            st.error("저장할 표지가 없습니다. 제목을 확인해주세요.")
            return

        ts   = datetime.now().strftime('%Y%m%d_%H%M%S')
        status_text.empty()

        with st.spinner("파일 생성 중…"):
            if fmt == "PDF":
                data = build_pdf(results, height_cm * 10)
                st.success("작업 완료! 아래 버튼을 눌러 저장하세요.")
                st.download_button("📥  PDF 다운로드", data=data,
                                   file_name=f"covers_{ts}.pdf", mime="application/pdf")
            else:
                data = build_zip(results)
                st.success("작업 완료! 아래 버튼을 눌러 저장하세요.")
                st.download_button("📥  PNG ZIP 다운로드", data=data,
                                   file_name=f"covers_{ts}.zip", mime="application/zip")


# ══════════════════════════════════════════════════════════════════════
# 진입점
# ══════════════════════════════════════════════════════════════════════
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "page" not in st.session_state:
    st.session_state["page"] = "main"

if not st.session_state["authenticated"]:
    show_login()
elif st.session_state["page"] == "bulk":
    show_bulk()
elif st.session_state["page"] == "search":
    show_search()
else:
    show_main()
