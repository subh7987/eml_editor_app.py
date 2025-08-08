import streamlit as st
import email
from email import policy
from email.generator import BytesGenerator
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from io import BytesIO
from deep_translator import GoogleTranslator

st.set_page_config(page_title="Email Editor", layout="wide")

st.title("📧 EML File Editor with Translate Option")

uploaded_file = st.file_uploader("Upload an .eml file", type=["eml"])

if uploaded_file:
    msg = email.message_from_bytes(uploaded_file.read(), policy=policy.default)

    # Extract metadata
    from_addr = st.text_input("From", msg.get("From", ""))
    to_addr = st.text_input("To", msg.get("To", ""))
    subject = st.text_input("Subject", msg.get("Subject", ""))

    # Extract body
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_payload(decode=True).decode(part.get_content_charset("utf-8"), errors="replace")
                break
    else:
        body = msg.get_payload(decode=True).decode(msg.get_content_charset("utf-8"), errors="replace")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Email Body (Editable)")
        edited_body = st.text_area("Edit the content", body, height=300)

    with col2:
        st.subheader("Translation Tools")
        if st.button("Translate to English"):
            edited_body = GoogleTranslator(source="auto", target="en").translate(edited_body)
            st.success("Translated to English!")

        target_lang = st.text_input("Translate back to language code (e.g., hi, fr, es)", "")
        if st.button("Translate Back"):
            if target_lang.strip():
                edited_body = GoogleTranslator(source="auto", target=target_lang.strip()).translate(edited_body)
                st.success(f"Translated back to {target_lang}!")

    if st.button("Save EML"):
        new_msg = MIMEMultipart()
        new_msg["From"] = from_addr
        new_msg["To"] = to_addr
        new_msg["Subject"] = subject
        new_msg.attach(MIMEText(edited_body, "plain"))

        buf = BytesIO()
        BytesGenerator(buf).flatten(new_msg)
        buf.seek(0)

        st.download_button("Download Edited EML", buf, file_name="edited_email.eml")
