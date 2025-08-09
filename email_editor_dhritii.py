import streamlit as st
from email import policy
from email.parser import BytesParser
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from langdetect import detect
from streamlit_tinymce import st_tinymce
import io

st.set_page_config(page_title="EML Visual Editor", layout="wide")

st.title("📧 EML File Visual Editor with Translation View")

# Function to parse .eml file
def parse_eml(file_bytes):
    msg = BytesParser(policy=policy.default).parsebytes(file_bytes)
    subject = msg["subject"]
    from_ = msg["from"]
    to = msg["to"]
    date = msg["date"]

    # Get HTML or plain text part
    html_content = None
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            html_content = part.get_content()
            break
        elif part.get_content_type() == "text/plain" and not html_content:
            html_content = f"<pre>{part.get_content()}</pre>"

    return subject, from_, to, date, html_content

# Upload .eml file
uploaded_file = st.file_uploader("Upload an .eml file", type=["eml"])

if uploaded_file:
    file_bytes = uploaded_file.read()
    subject, from_, to, date, html_body = parse_eml(file_bytes)

    st.sidebar.subheader("Email Metadata")
    st.sidebar.text_input("Subject", value=subject)
    st.sidebar.text_input("From", value=from_)
    st.sidebar.text_input("To", value=to)
    st.sidebar.text_input("Date", value=date)

    if html_body:
        col1, col2 = st.columns(2)

        # Detect language
        try:
            detected_lang = detect(BeautifulSoup(html_body, "html.parser").get_text())
        except:
            detected_lang = "unknown"

        # Column 1: Visual editor (original language)
        with col1:
            st.subheader(f"Edit Email (Language: {detected_lang})")
            edited_html = st_tinymce(
                value=html_body,
                height=600,
                key="tinymce",
                config={
                    "menubar": False,
                    "plugins": "lists link image table paste help wordcount",
                    "toolbar": "undo redo | bold italic underline | alignleft aligncenter alignright | bullist numlist | link image | table | removeformat",
                    "branding": False,
                    "paste_as_text": True
                }
            )

        # Column 2: English translation (read-only)
        with col2:
            st.subheader("English Translation (for review)")
            if detected_lang != "en" and detected_lang != "unknown":
                try:
                    translated_text = GoogleTranslator(source='auto', target='en').translate(
                        BeautifulSoup(html_body, "html.parser").get_text()
                    )
                    st.text_area("Translated Text", value=translated_text, height=600)
                except Exception as e:
                    st.error(f"Translation failed: {e}")
            else:
                st.info("Email is already in English or language could not be detected.")

        # Save button
        if st.button("💾 Download Edited EML"):
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            # Create new email
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = from_
            msg["To"] = to
            msg.attach(MIMEText(edited_html, "html"))

            # Save as .eml
            eml_bytes = msg.as_bytes()
            st.download_button(
                label="Download Edited EML",
                data=eml_bytes,
                file_name="edited_email.eml",
                mime="message/rfc822"
            )
