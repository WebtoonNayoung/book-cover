import streamlit as st
import os
import requests
from PIL import Image
from io import BytesIO
from fpdf import FPDF
import warnings
from datetime import datetime, timedelta

warnings.filterwarnings('ignore')

# --- 설정값 ---
TARGET_HEIGHT_MM = 30
PAGE_WIDTH_MM = 210
MARGIN_MM = 10
DPI = 300
GAP_MM = 1

# --- 주차별 비밀번호 목록 (passwords.json에서 로드) ---
import json

with open("passwords.json", "r") as f:
    PASSWORDS = json.load(f)

def get_this_week_monday() -> str:
    """이번 주 월요일 날짜를 YYYY-MM-DD 형식으로 반환"""
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
def get_cover_from_naver(book_title):
    try:
        url = "https://openapi.naver.com/v1/search/book.json"
        headers = {
            "X-Naver-Client-Id": st.secrets["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": st.secrets["NAVER_CLIENT_SECRET"],
        }
        params = {"query": book_title, "display": 1}

        res = requests.get(url, headers=headers, params=params, timeout=10)
        res.raise_for_status()
        items = res.json().get("items", [])

        if not items:
            return None

        image_url = items[0].get("image")
        if not image_url:
            return None

        img_res = requests.get(image_url, timeout=10)
        if img_res.status_code != 200:
            return None

        img = Image.open(BytesIO(img_res.content))
        target_height_px = int((TARGET_HEIGHT_MM / 25.4) * DPI)
        width_ratio = target_height_px / img.height
        target_width_px = int(img.width * width_ratio)

        return img.resize((target_width_px, target_height_px), Image.Resampling.LANCZOS)

    except Exception:
        return None

# --- 메인 앱 ---
def show_app():
    st.set_page_config(page_title="책 표지 메이커", page_icon="📚")
    st.title("📚 책 표지 자동 수집기")
    st.markdown("책 제목을 입력하면 세로 **3cm**에 맞춰진 인쇄용 PDF를 만들어줍니다!")

    titles_input = st.text_area(
        "책 제목을 한 줄에 하나씩 입력하세요:",
        height=150,
        placeholder="구름 사람들\n파친코\n불편한 편의점"
    )

    if st.button("🚀 PDF 만들기 시작!"):
        titles = [t.strip() for t in titles_input.split('\n') if t.strip()]

        if not titles:
            st.warning("책 제목을 먼저 입력해주세요!")
        else:
            images = []
            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, t in enumerate(titles):
                status_text.text(f"'{t}' 표지 찾는 중... ({i+1}/{len(titles)})")
                img = get_cover_from_naver(t)
                if img:
                    images.append(img)
                else:
                    st.toast(f"'{t}' 표지 찾기 실패 ❌")
                progress_bar.progress((i + 1) / len(titles))

            status_text.text("PDF 생성 중...")

            if images:
                pdf = FPDF()
                pdf.add_page()
                x, y = MARGIN_MM, MARGIN_MM

                for i, img in enumerate(images):
                    temp_path = f"temp_{i}.png"
                    img.save(temp_path)
                    w_mm = (img.width / DPI) * 25.4

                    if x + w_mm > PAGE_WIDTH_MM - MARGIN_MM:
                        x = MARGIN_MM
                        y += TARGET_HEIGHT_MM + GAP_MM
                    if y + TARGET_HEIGHT_MM > 280:
                        pdf.add_page()
                        y = MARGIN_MM
                        x = MARGIN_MM

                    pdf.image(temp_path, x=x, y=y, h=TARGET_HEIGHT_MM)
                    x += w_mm + GAP_MM
                    os.remove(temp_path)

                now = datetime.now()
                filename = f"result_covers_{now.strftime('%Y%m%d_%H%M%S')}.pdf"
                pdf.output(filename)

                with open(filename, "rb") as f:
                    pdf_bytes = f.read()
                os.remove(filename)

                st.success("🎉 작업 완료! 아래 버튼을 눌러 저장하세요.")
                st.download_button(
                    label="📥 완성된 PDF 다운로드",
                    data=pdf_bytes,
                    file_name=filename,
                    mime="application/pdf"
                )
            else:
                st.error("저장할 표지가 없습니다. 제목을 확인해주세요.")

# --- 진입점 ---
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if st.session_state["authenticated"]:
    show_app()
else:
    show_login()
