import streamlit as st
import os
import requests
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from fpdf import FPDF
import warnings
from datetime import datetime, timedelta
import json
import zipfile

warnings.filterwarnings('ignore')

# --- 설정값 ---
PAGE_WIDTH_MM = 210
MARGIN_MM = 10
DPI = 300
GAP_MM = 1

# --- 주차별 비밀번호 목록 ---
with open("passwords.json", "r") as f:
    PASSWORDS = json.load(f)

def get_this_week_monday() -> str:
    today = datetime.today()
    monday = today - timedelta(days=today.weekday())
    return monday.strftime("%Y-%m-%d")

def get_current_password() -> str:
    monday = get_this_week_monday()
    return PASSWORDS.get(monday, None)

# --- 인증 화면 ---
def show_login():
    st.set_page_config(page_title="책 표지 메이커", page_icon="📚")
    st.title("📚 책 표지 수집기")
    st.markdown("이용하려면 이번 주 입장 코드를 입력하세요.")

    pw_input = st.text_input("입장 코드", type="password")

    if st.button("확인"):
        correct_pw = get_current_password()
        if correct_pw is None:
            st.error("이번 주 비밀번호가 설정되지 않았습니다. 관리자에게 문의하세요.")
        elif pw_input == correct_pw:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("입장 코드가 올바르지 않습니다.")

# --- 핵심 기능 ---
def get_cover_from_naver(book_title, publisher, target_height_mm):
    try:
        url = "https://openapi.naver.com/v1/search/book.json"
        headers = {
            "X-Naver-Client-Id": st.secrets["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": st.secrets["NAVER_CLIENT_SECRET"],
        }
        query = f"{book_title} {publisher}".strip() if publisher else book_title
        params = {"query": query, "display": 1}

        res = requests.get(url, headers=headers, params=params, timeout=10)
        res.raise_for_status()
        items = res.json().get("items", [])

        if not items:
            return None, ""

        item = items[0]
        image_url = item.get("image")
        api_publisher = item.get("publisher", "")

        if not image_url:
            return None, api_publisher

        img_res = requests.get(image_url, timeout=10)
        if img_res.status_code != 200:
            return None, api_publisher

        img = Image.open(BytesIO(img_res.content))
        target_height_px = int((target_height_mm / 25.4) * DPI)
        width_ratio = target_height_px / img.height
        target_width_px = int(img.width * width_ratio)

        return img.resize((target_width_px, target_height_px), Image.Resampling.LANCZOS), api_publisher

    except Exception:
        return None, ""

# --- PDF 저장 ---
def save_pdf(results, target_height_mm, filename_base):
    FONT_SIZE_PT = 6
    TEXT_HEIGHT_MM = 4

    pdf = FPDF()
    pdf.add_page()

    # 한글 폰트 로드 시도
    try:
        pdf.add_font("Korean", fname="C:/Windows/Fonts/malgun.ttf")
        pdf.set_font("Korean", size=FONT_SIZE_PT)
    except Exception:
        pdf.set_font("Helvetica", size=FONT_SIZE_PT)

    x, y = MARGIN_MM, MARGIN_MM
    row_height = target_height_mm + TEXT_HEIGHT_MM + GAP_MM

    for i, (img, title, publisher) in enumerate(results):
        temp_path = f"temp_{i}.png"
        img.save(temp_path)
        w_mm = (img.width / DPI) * 25.4

        if x + w_mm > PAGE_WIDTH_MM - MARGIN_MM:
            x = MARGIN_MM
            y += row_height
        if y + row_height > 280:
            pdf.add_page()
            y = MARGIN_MM
            x = MARGIN_MM

        pdf.image(temp_path, x=x, y=y, h=target_height_mm)

        if publisher:
            pdf.set_xy(x, y + target_height_mm + 0.5)
            pdf.cell(w_mm, TEXT_HEIGHT_MM - 0.5, txt=publisher)

        x += w_mm + GAP_MM
        os.remove(temp_path)

    filename = f"{filename_base}.pdf"
    pdf.output(filename)
    with open(filename, "rb") as f:
        pdf_bytes = f.read()
    os.remove(filename)

    st.success("🎉 작업 완료!")
    st.download_button(label="📥 PDF 다운로드", data=pdf_bytes, file_name=filename, mime="application/pdf")

# --- PNG 저장 (개별 PNG → ZIP) ---
def save_png(results, target_height_mm, filename_base):
    zip_buf = BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, (img, title, publisher) in enumerate(results):
            buf = BytesIO()
            img.save(buf, format="PNG")
            safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()
            png_name = f"{i+1:02d}_{safe_title}.png"
            zf.writestr(png_name, buf.getvalue())

    zip_bytes = zip_buf.getvalue()
    filename = f"{filename_base}.zip"
    st.success("🎉 작업 완료!")
    st.download_button(label="📥 PNG ZIP 다운로드", data=zip_bytes, file_name=filename, mime="application/zip")

# --- 메인 앱 ---
def show_app():
    st.set_page_config(page_title="책 표지 메이커", page_icon="📚")
    st.title("📚 책 표지 자동 수집기")
    st.markdown("책 제목을 입력하면 인쇄용 파일을 만들어줍니다!")

    col1, col2 = st.columns(2)
    with col1:
        target_height_cm = st.slider("표지 높이 (cm)", min_value=1.0, max_value=10.0, value=3.0, step=0.5)
    with col2:
        save_format = st.radio("저장 형식", ["PDF", "PNG"])

    target_height_mm = target_height_cm * 10

    titles_input = st.text_area(
        "책 제목을 한 줄에 하나씩 입력하세요 (출판사는 쉼표로 구분):",
        height=150,
        placeholder="구름 사람들\n파친코, 문학사상\n불편한 편의점"
    )

    if st.button("🚀 만들기 시작!"):
        lines = [l.strip() for l in titles_input.split('\n') if l.strip()]

        entries = []
        for line in lines:
            if ',' in line:
                parts = line.split(',', 1)
                entries.append((parts[0].strip(), parts[1].strip()))
            else:
                entries.append((line.strip(), ""))

        if not entries:
            st.warning("책 제목을 먼저 입력해주세요!")
            return

        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()

        for i, (title, pub) in enumerate(entries):
            status_text.text(f"'{title}' 표지 찾는 중... ({i+1}/{len(entries)})")
            img, api_pub = get_cover_from_naver(title, pub, target_height_mm)
            display_pub = pub if pub else api_pub
            if img:
                results.append((img, title, display_pub))
            else:
                st.toast(f"'{title}' 표지 찾기 실패 ❌")
            progress_bar.progress((i + 1) / len(entries))

        status_text.text("파일 생성 중...")

        if not results:
            st.error("저장할 표지가 없습니다. 제목을 확인해주세요.")
            return

        now = datetime.now()
        filename_base = f"result_covers_{now.strftime('%Y%m%d_%H%M%S')}"

        if save_format == "PDF":
            save_pdf(results, target_height_mm, filename_base)
        else:
            save_png(results, target_height_mm, filename_base)

# --- 진입점 ---
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if st.session_state["authenticated"]:
    show_app()
else:
    show_login()
