import streamlit as st
from streamlit.components.v1 import html
from email import policy
from email.parser import BytesParser
from email.generator import BytesGenerator
from io import BytesIO
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from langdetect import detect, DetectorFactory
import base64
import re

DetectorFactory.seed = 0
st.set_page_config(page_title="EML WYSIWYG Editor + Translate", layout="wide")

st.title("📧 EML Visual Editor with TinyMCE + English Translation Preview")

def parse_eml_bytes(raw_bytes):
    return BytesParser(policy=policy.default).parsebytes(raw_bytes)

def extract_html_and_attachments(msg):
    html = None
    plain = None
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = part.get_content_disposition()
            if ctype == "text/html" and html is None:
                html = part.get_content()
            elif ctype == "text/plain" and plain is None:
                plain = part.get_content()
            else:
                if disp in ("attachment", "inline") or part.get_filename():
                    payload = part.get_payload(decode=True)
                    attachments.append({
                        "part": part,
                        "filename": part.get_filename() or "",
                        "bytes": payload,
                        "content_type": part.get_content_type(),
                        "content_id": (part.get("Content-ID") or "").strip("<>"),
                        "is_inline": (disp == "inline")
                    })
    else:
        if msg.get_content_type() == "text/html":
            html = msg.get_content()
        elif msg.get_content_type() == "text/plain":
            plain = msg.get_content()
    return html, plain, attachments

def embed_inline_images_in_html(html_text, attachments):
    if not html_text:
        return html_text
    out_html = html_text
    for att in attachments:
        cid = att.get("content_id")
        if not cid:
            continue
        ctype = att.get("content_type") or "application/octet-stream"
        b = att.get("bytes")
        if not b:
            continue
        b64 = base64.b64encode(b).decode("utf-8")
        datauri = f"data:{ctype};base64,{b64}"
        out_html = out_html.replace(f"cid:{cid}", datauri)
    return out_html

def translate_html_preserve(html_text, target="en"):
    if not html_text:
        return html_text
    soup = BeautifulSoup(html_text, "html.parser")
    texts = []
    nodes = []
    for elem in soup.find_all(text=True):
        if elem.parent.name in ["script", "style"]:
            continue
        if not elem.string or not elem.string.strip():
            continue
        texts.append(elem.string)
        nodes.append(elem)
    if not texts:
        return str(soup)

    delim = "<<<STREAMLIT_DELIM>>>"
    joined = delim.join(texts)
    try:
        translated_joined = GoogleTranslator(source="auto", target=target).translate(joined)
    except Exception as e:
        st.error(f"Translation failed: {e}")
        return str(soup)
    translated_texts = translated_joined.split(delim)
    if len(translated_texts) != len(nodes):
        translated_texts = []
        for t in texts:
            try:
                translated_texts.append(GoogleTranslator(source="auto", target=target).translate(t))
            except:
                translated_texts.append(t)
    for node, new in zip(nodes, translated_texts):
        node.replace_with(new)
    return str(soup)

def set_html_in_message(orig_msg, new_html):
    msg = orig_msg
    if msg.is_multipart():
        replaced = False
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                part.set_content(new_html, subtype="html")
                replaced = True
                break
        if not replaced:
            from email.message import EmailMessage
            html_part = EmailMessage()
            html_part.set_content(new_html, subtype="html")
            msg.make_mixed()
            msg.attach(html_part)
    else:
        if msg.get_content_type() == "text/html":
            msg.set_content(new_html, subtype="html")
        else:
            from email.message import EmailMessage
            new = EmailMessage()
            for k in msg.keys():
                new[k] = msg[k]
            try:
                plain = msg.get_content()
            except:
                plain = ""
            new.set_content(plain or "")
            new.add_alternative(new_html, subtype="html")
            msg = new
    return msg

def eml_to_bytes(msg):
    buf = BytesIO()
    BytesGenerator(buf, policy=policy.default).flatten(msg)
    return buf.getvalue()

# --- TinyMCE editor embed code ---
def tiny_mce_editor(html_content, key="editor"):
    # Returns edited HTML on form submit
    editor_html = f"""
    <script src="https://cdn.tiny.cloud/1/no-api-key/tinymce/6/tinymce.min.js" referrerpolicy="origin"></script>
    <textarea id="tinymce-editor" name="content" style="height:600px;">{html_content}</textarea>
    <script>
      tinymce.init({{
        selector: '#tinymce-editor',
        plugins: 'lists link image table paste help wordcount',
        toolbar: 'undo redo | bold italic underline | alignleft aligncenter alignright | bullist numlist | link image | table | removeformat',
        menubar: false,
        branding: false,
        paste_as_text: true
      }});
    </script>
    """
    # Streamlit component to get edited HTML
    edited_html = st.components.v1.html(editor_html, height=650, scrolling=True, key=key)
    # We cannot get return value from this HTML in pure Streamlit
    # So, we use st.text_area below to get edited content from user
    st.warning("Note: Due to Streamlit limitations, please copy the edited content below and paste it back if you want to save edits.")
    edited_html_text = st.text_area("Paste your edited HTML here to save it", value=html_content, height=250)
    return edited_html_text

# --- Main UI ---
uploaded = st.file_uploader("Upload a single .eml file", type=["eml"])
if not uploaded:
    st.info("Upload an .eml file to start editing.")
    st.stop()

raw = uploaded.read()
try:
    msg = parse_eml_bytes(raw)
except Exception as e:
    st.error(f"Failed to parse .eml file: {e}")
    st.stop()

html_text, plain_text, attachments = extract_html_and_attachments(msg)
embedded_html = embed_inline_images_in_html(html_text, attachments) if html_text else None

# Language detection
sample_text = ""
if html_text:
    try:
        sample_text = BeautifulSoup(html_text, "html.parser").get_text()[:1000]
    except:
        sample_text = html_text[:1000]
elif plain_text:
    sample_text = plain_text[:1000]

detected_lang = None
try:
    if sample_text.strip():
        detected_lang = detect(sample_text)
except:
    detected_lang = None

st.markdown(f"**Detected language (sample):** {detected_lang or 'unknown'}")

st.markdown("---")
st.subheader("Left: Original Email HTML (Editable with TinyMCE)")
if embedded_html:
    edited_html = tiny_mce_editor(embedded_html, key="tiny-editor")
else:
    edited_html = st.text_area("Plain text body (edit)", value=plain_text or "", height=600)

st.subheader("Right: English Translation Preview (read-only)")
if embedded_html:
    with st.spinner("Translating to English..."):
        try:
            translated_html = translate_html_preserve(embedded_html, target="en")
        except Exception as e:
            st.error(f"Translation error: {e}")
            translated_html = embedded_html
    st.components.v1.html(translated_html, height=650, scrolling=True)
elif plain_text:
    try:
        translated = GoogleTranslator(source="auto", target="en").translate(plain_text)
    except:
        translated = plain_text
    st.text_area("Translated Plain Text", value=translated, height=600, disabled=True)
else:
    st.write("No body to translate.")

st.markdown("---")
if st.button("Save & Download Edited .eml (original language)"):
    if html_text:
        # Use edited HTML from text area input (due to Streamlit limitations)
        final_msg = set_html_in_message(msg, edited_html)
        # Update plain text fallback
        try:
            plain_from_html = BeautifulSoup(edited_html, "html.parser").get_text("\n")
        except:
            plain_from_html = None
        if plain_from_html:
            replaced_plain = False
            if final_msg.is_multipart():
                for part in final_msg.walk():
                    if part.get_content_type() == "text/plain":
                        part.set_content(plain_from_html, subtype="plain")
                        replaced_plain = True
                        break
            if not replaced_plain:
                final_msg.set_content(plain_from_html)
    else:
        final_plain = edited_html if edited_html else plain_text or ""
        if msg.is_multipart():
            replaced_plain = False
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    part.set_content(final_plain, subtype="plain")
                    replaced_plain = True
                    break
            if not replaced_plain:
                msg.set_content(final_plain)
        else:
            msg.set_content(final_plain)
        final_msg = msg

    out_bytes = eml_to_bytes(final_msg)
    st.success("Edited .eml ready for download.")
    st.download_button("Download .eml file", data=out_bytes, file_name=f"edited_{uploaded.name}", mime="message/rfc822")
