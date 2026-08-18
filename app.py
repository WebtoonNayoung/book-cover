import streamlit as st
import os
import re
import zipfile
import warnings
from io import BytesIO
from datetime import datetime, timedelta, timezone

import json
from urllib.parse import unquote

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
GAP_DEFAULT_MM = 0        # 표지 사이 간격 기본값 (사용자가 조절)

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
    """비밀번호 목록을 읽는다.

    비밀번호는 저장소에 올리지 않는다. 배포 환경에서는 Streamlit secrets의
    PASSWORD_LIST(줄바꿈으로 구분)를 쓰고, 로컬 개발에서는 비밀번호목록.txt를 쓴다.
    """
    raw = None
    try:
        raw = st.secrets["PASSWORD_LIST"]
    except Exception:
        raw = None
    if not raw:
        raw = os.environ.get("PASSWORD_LIST")

    if raw:
        lines = raw.splitlines() if isinstance(raw, str) else list(raw)
        return [pw.strip() for pw in lines if pw and pw.strip()]

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

def build_pdf(results, target_height_mm: float,
              gap_x_mm: float = GAP_DEFAULT_MM,
              gap_y_mm: float = GAP_DEFAULT_MM) -> bytes:
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

    # 한글 폰트가 없으면 제목을 못 찍으므로 제목용 여백도 잡지 않는다
    text_h = TEXT_H_MM if has_font else 0
    x, y   = MARGIN_MM, MARGIN_MM
    row_h  = target_height_mm + text_h + gap_y_mm

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
            pdf.cell(w_mm, text_h - 0.5, txt=title[:30])
        x += w_mm + gap_x_mm
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

# ── 표지 검색 (검색하여 받기) ─────────────────────────────────────────
# 네이버 '책' 검색 API는 2026-07-31 종료(SE05). 대체로 네이버 '이미지' 검색을
# 써봤지만 도서 DB가 아니라 키워드 매칭이라 뒤표지·내지·다른 책이 섞이고,
# 정작 찾아야 할 책을 못 찾는 경우가 많아 알라딘 TTB API로 전환했다.
# 알라딘은 제목·출판사·저자가 함께 오므로 정확히 지정할 수 있다.

_ALADIN_ENDPOINT = "https://www.aladin.co.kr/ttb/api/ItemSearch.aspx"
_ALADIN_DAILY_LIMIT = 5000        # 알라딘 OpenAPI 일일 호출 한도
# 표지가 아니거나 다른 상품인 결과를 걸러내는 단어
_REJECT_WORDS  = ("세트", "중고", "사은품", "굿즈", "전자책", "오디오북",
                  "블루레이", "DVD", "OST")
_EDITION_WORDS = ("에디션", "특별판", "한정", "워터프루프", "포토", "리커버")
_FOREIGN_WORDS = ("중문판", "영문판", "일문판", "중국어", "영어판", "번체", "간체")
_HTTP_HEADERS  = {"User-Agent": "Mozilla/5.0"}

QUOTA_MESSAGE = ("오늘 사용할 수 있는 검색 횟수를 모두 썼습니다. "
                 f"(알라딘 OpenAPI 일일 {_ALADIN_DAILY_LIMIT:,}회) 내일 다시 이용해주세요.")


class QuotaExceeded(Exception):
    """알라딘 일일 호출 한도 초과."""


def _get_secret(name: str):
    """st.secrets → 환경변수 순으로 조회. 없으면 None."""
    try:
        v = st.secrets[name]
        if v:
            return v
    except Exception:
        pass
    return os.environ.get(name) or None


def _norm(s: str) -> str:
    return re.sub(r'[^0-9a-z가-힣]', '', (s or "").lower())


def _product_name(title: str) -> str:
    """'소년이 온다 (10주년 특별판)' → '소년이 온다'"""
    t = re.sub(r'^\s*\[[^\]]*\]\s*', '', title or "")   # 앞머리 [POD] 등 제거
    t = re.split(r'\s-\s', t)[0]                         # 부제 분리
    return re.sub(r'\([^)]*\)', '', t).strip()


def _aladin_hi_res(url: str) -> str:
    """알라딘 표지 URL을 500px 판본으로 (coversum/cover200 → cover500)."""
    return re.sub(r'/cover(?:sum|big|\d+)?/', '/cover500/', url or "", count=1)


def _aladin_request(query: str, key: str, attempts: int = 3):
    params = {"ttbkey": key, "Query": query, "QueryType": "Title",
              "MaxResults": 50, "start": 1, "SearchTarget": "Book",
              "output": "js", "Version": "20131101", "Cover": "Big"}
    # 알라딘 응답이 가끔 느려 한 번의 타임아웃으로 책을 통째로 놓치지 않도록 재시도
    for attempt in range(attempts):
        try:
            r = requests.get(_ALADIN_ENDPOINT, params=params, timeout=15)
            r.raise_for_status()
            break
        except requests.RequestException:
            if attempt == attempts - 1:
                raise
    data = json.loads(r.text.strip().rstrip(';'))
    msg = data.get("errorMessage")
    if msg:
        # 한도 초과는 사용자에게 다르게 안내해야 하므로 따로 구분한다
        if any(w in msg for w in ("한도", "초과", "제한", "Limit", "limit", "Over")):
            raise QuotaExceeded(msg)
        raise RuntimeError(f"알라딘 API: {msg}")
    return data.get("item", [])


def _build_candidate(it, publisher, nb, exact):
    cover = _aladin_hi_res(it.get("cover", ""))
    if not cover:
        return None
    title = it.get("title", "")
    if any(bad in title for bad in _REJECT_WORDS):
        return None
    pub, author = it.get("publisher", ""), it.get("author", "")
    if exact:
        score = 100
        if publisher and _norm(publisher) in _norm(pub):
            score += 40                                # 지정한 출판사면 크게 우대
        if any(e in title for e in _EDITION_WORDS):
            score -= 20
        if any(f in title for f in _FOREIGN_WORDS):
            score -= 30
        if _norm(_product_name(title)) == nb:
            score += 15
        label = " · ".join(x for x in (pub, author[:22]) if x)
    else:
        score = 0
        label = "유사 · " + " · ".join(x for x in (pub, title[:26]) if x)
    return {"url": cover, "score": score, "source": "알라딘", "label": label}


def get_cover_candidates(book_title, publisher="", limit=6):
    """([{url, label, source}], 실패 사유 | None)

    알라딘 TTB API로 조회한다. 제목이 정확히 맞는 결과를 우선 쓰고, 하나도 없으면
    검색어를 뒤에서부터 줄여가며 다시 찾아 '유사' 후보로 보여준다(오타·부제 차이 대응).
    """
    key = _get_secret("ALADIN_TTB_KEY")
    if not key:
        return [], ("알라딘 API 키가 없습니다. Streamlit secrets에 "
                    "ALADIN_TTB_KEY를 설정하세요.")

    nb    = _norm(book_title)
    full  = f"{book_title} {publisher}".strip() if publisher else book_title
    words = book_title.split()
    # 전체 검색어 → 제목만 → 뒤 단어를 하나씩 떼며 재시도
    queries = [full, book_title] + [" ".join(words[:i]) for i in range(len(words) - 1, 0, -1)]

    seen_q, similar = set(), []
    for qi, query in enumerate(queries):
        if not query or query in seen_q:
            continue
        seen_q.add(query)
        try:
            items = _aladin_request(query, key)
        except QuotaExceeded:
            return [], QUOTA_MESSAGE
        except Exception as e:
            return [], str(e)

        # 정확히 일치하는 것과 유사한 것을 나눈다
        exact, loose = [], []
        for it in items:
            is_exact = _norm(_product_name(it.get("title", ""))).startswith(nb)
            cand = _build_candidate(it, publisher, nb, is_exact)
            if not cand:
                continue
            (exact if is_exact else loose).append(cand)

        if exact:
            exact.sort(key=lambda c: -c["score"])
            return exact[:limit], None
        if loose and not similar:
            similar = loose            # 더 짧은 검색어의 결과보다 먼저 찾은 쪽을 남긴다

    if similar:
        return similar[:limit], None
    return [], "알라딘에서 해당 도서를 찾지 못했습니다. 제목을 확인해주세요."


def download_cover(url):
    ir = requests.get(url, timeout=10, headers=_HTTP_HEADERS)
    ir.raise_for_status()
    return Image.open(BytesIO(ir.content)).convert("RGB")


def resize_to_height(img, target_height_mm: float):
    th = int((target_height_mm / 25.4) * DPI)
    tw = max(1, int(img.width * th / img.height))
    return img.resize((tw, th), Image.Resampling.LANCZOS)


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

    gap_x, gap_y = layout_gap_controls("bulk")

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
                data = build_pdf(results, height_cm * 10, gap_x, gap_y)
                st.success(f"완료! {len(results)}권 → PDF")
                st.download_button("📥  PDF 다운로드", data=data,
                                   file_name=f"{base}_{ts}.pdf", mime="application/pdf")
            else:
                data = build_zip(results)
                st.success(f"완료! {len(results)}권 → PNG ZIP")
                st.download_button("📥  PNG ZIP 다운로드", data=data,
                                   file_name=f"{base}_{ts}.zip", mime="application/zip")


def layout_gap_controls(key_prefix: str):
    """표지 사이 간격(좌우·상하) 슬라이더. 기본값 0mm = 표지끼리 딱 붙음."""
    st.markdown("<p style='font-size:0.82rem; color:#9A9690; margin:0.6rem 0 0.2rem 0;'>"
                "표지 사이 간격 (0 = 붙여서 배치)</p>", unsafe_allow_html=True)
    g1, g2 = st.columns(2)
    with g1:
        gap_x = st.slider("좌우 간격", min_value=0.0, max_value=20.0, value=0.0,
                          step=0.5, format="%.1f mm", key=f"{key_prefix}_gap_x")
    with g2:
        gap_y = st.slider("상하 간격", min_value=0.0, max_value=20.0, value=0.0,
                          step=0.5, format="%.1f mm", key=f"{key_prefix}_gap_y")
    return gap_x, gap_y


def show_search():
    inject_css()
    if st.button("← 뒤로", key="search_back"):
        st.session_state["page"] = "main"
        for k in ("sr_books", "sr_quota"):
            st.session_state.pop(k, None)
        st.rerun()

    st.markdown("""
    <div style="padding:0.5rem 0 2rem 0;">
        <h2 style="font-size:1.6rem; color:#2C4F7C; margin:0 0 0.4rem 0; font-weight:700;">🔍 검색하여 받기</h2>
        <p style="color:#8A8278; font-size:0.95rem; margin:0;">책마다 표지 후보를 보여드립니다. 원하는 판본을 고르세요.</p>
    </div>""", unsafe_allow_html=True)

    st.markdown("<p style='font-weight:500; color:#4A4A4A; margin-bottom:0.3rem;'>책 목록</p>",
                unsafe_allow_html=True)
    st.markdown("<p style='font-size:0.82rem; color:#9A9690; margin-bottom:0.5rem;'>"
                "한 줄에 한 권씩 &nbsp;·&nbsp; 출판사를 쉼표로 덧붙이면 원하는 판본이 위로 옵니다 "
                "<code>데미안, 민음사</code></p>", unsafe_allow_html=True)

    titles_input = st.text_area("책 목록", height=180,
                                placeholder="구름 사람들\n파친코, 문학사상\n데미안, 민음사",
                                label_visibility="collapsed")

    if st.button("🔍  표지 찾기", key="search_run"):
        entries = []
        for line in [l.strip() for l in titles_input.split('\n') if l.strip()]:
            if ',' in line:
                t, pub = line.split(',', 1)
                entries.append((t.strip(), pub.strip()))
            else:
                entries.append((line, ""))
        if not entries:
            st.warning("책 제목을 먼저 입력해주세요.")
            return

        books = []
        progress_bar = st.progress(0)
        status_text  = st.empty()
        for i, (title, pub) in enumerate(entries):
            status_text.markdown(
                f"<p style='color:#8A8278; font-size:0.9rem;'>"
                f"'{title}' 표지 찾는 중… ({i+1}/{len(entries)})</p>", unsafe_allow_html=True)
            cands, err = get_cover_candidates(title, pub)
            books.append({"title": title, "pub": pub, "candidates": cands, "error": err})
            progress_bar.progress((i + 1) / len(entries))
            if err == QUOTA_MESSAGE:
                break                  # 한도를 넘겼으면 나머지도 실패하므로 즉시 중단
        status_text.empty(); progress_bar.empty()
        st.session_state["sr_books"]  = books
        st.session_state["sr_quota"]  = any(b["error"] == QUOTA_MESSAGE for b in books)
        st.rerun()

    books = st.session_state.get("sr_books")
    if books is None:
        return

    st.markdown("<hr>", unsafe_allow_html=True)

    if st.session_state.get("sr_quota"):
        st.error(f"⏳ {QUOTA_MESSAGE}")

    missing = [b for b in books if not b["candidates"]]
    if missing:
        with st.expander(f"⚠️ 표지를 찾지 못한 책 {len(missing)}권 — 원인 보기"):
            for b in missing:
                st.write(f"• {b['title']} — {b['error']}")

    usable = [b for b in books if b["candidates"]]
    if not usable:
        st.error("표지를 하나도 찾지 못했습니다. 제목·출판사를 확인해주세요.")
        return

    st.markdown("<p style='font-weight:600; color:#2C4F7C; margin-bottom:0.2rem;'>"
                "표지 고르기</p>", unsafe_allow_html=True)
    st.markdown("<p style='font-size:0.82rem; color:#9A9690; margin-bottom:1rem;'>"
                "같은 책도 리커버·개정판 등 판본이 여러 개일 수 있습니다. "
                "원하는 것을 고르고, 쓰지 않을 책은 <b>제외</b>를 선택하세요.</p>",
                unsafe_allow_html=True)

    for bi, book in enumerate(usable):
        label = book["title"] + (f" ({book['pub']})" if book["pub"] else "")
        st.markdown(f"<p style='font-weight:600; color:#4A4A4A; margin:1.2rem 0 0.4rem 0;'>"
                    f"{label}</p>", unsafe_allow_html=True)

        cands = book["candidates"]
        cols  = st.columns(max(len(cands), 3))
        for ci, cand in enumerate(cands):
            with cols[ci]:
                # 서점 이미지는 핫링크가 열려 있어 URL로 바로 미리보기 (서버 부담 없음)
                st.image(cand["url"], width='stretch')
                st.markdown(f"<p style='font-size:0.72rem; color:#9A9690; margin:-0.3rem 0 0 0;'>"
                            f"{ci+1}. {cand['source']}<br>{cand['label']}</p>",
                            unsafe_allow_html=True)

        st.radio("선택", options=list(range(len(cands))) + [-1],
                 format_func=lambda i: "제외" if i == -1 else f"{i+1}번",
                 horizontal=True, key=f"pick_{bi}", label_visibility="collapsed")

    st.markdown("<hr>", unsafe_allow_html=True)
    col1, col2 = st.columns([3, 2])
    with col1:
        height_cm = st.slider("표지 높이 (최대 5cm)", min_value=1.0, max_value=5.0,
                              value=3.0, step=0.5, format="%.1f cm")
    with col2:
        fmt = st.radio("저장 형식", ["PDF", "PNG"], horizontal=True, key="search_fmt")

    gap_x, gap_y = layout_gap_controls("search")

    if st.button("🚀  선택한 표지로 만들기", key="search_gen"):
        picked = []
        for bi, book in enumerate(usable):
            idx = st.session_state.get(f"pick_{bi}", 0)
            if idx != -1:
                picked.append((book, book["candidates"][idx]))
        if not picked:
            st.warning("표지를 하나 이상 선택해주세요.")
            return

        results, failed = [], []
        with st.spinner("선택한 표지 내려받는 중…"):
            for book, cand in picked:
                try:
                    img = download_cover(cand["url"])
                    results.append((resize_to_height(img, height_cm * 10),
                                    book["title"], book["pub"]))
                except Exception as e:
                    failed.append(f"{book['title']} — 내려받기 실패: {e}")
        if failed:
            for f in failed:
                st.warning(f)
        if not results:
            st.error("표지를 내려받지 못했습니다.")
            return

        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        with st.spinner("파일 생성 중…"):
            if fmt == "PDF":
                data = build_pdf(results, height_cm * 10, gap_x, gap_y)
                st.success(f"완료! {len(results)}권 → PDF")
                st.download_button("📥  PDF 다운로드", data=data,
                                   file_name=f"covers_{ts}.pdf", mime="application/pdf")
            else:
                data = build_zip(results)
                st.success(f"완료! {len(results)}권 → PNG ZIP")
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
