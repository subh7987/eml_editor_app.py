# app.py
import streamlit as st
from email import policy
from email.parser import BytesParser
from email.generator import BytesGenerator
from email.message import EmailMessage
from io import BytesIO
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from langdetect import detect, DetectorFactory
import base64

DetectorFactory.seed = 0

st.set_page_config(page_title="EML Visual Editor (TinyMCE) + Translate", layout="wide")
st.title("📧 EML Visual Editor — TinyMCE + English preview (copy-paste workflow)")

# ---------- Helpers ----------
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
                try:
                    html = part.get_content()
                except:
                    html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
            elif ctype == "text/plain" and plain is None:
                try:
                    plain = part.get_content()
                except:
                    plain = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
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

def translate_text_to_english(text):
    try:
        return GoogleTranslator(source="auto", target="en").translate(text)
    except Exception as e:
        st.warning(f"Translation failed: {e}")
        return text

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
            html_part = EmailMessage()
            html_part.set_content(new_html, subtype="html")
            msg.make_mixed()
            msg.attach(html_part)
    else:
        if msg.get_content_type() == "text/html":
            msg.set_content(new_html, subtype="html")
        else:
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

# ---------- UI ----------
st.markdown("**Instructions:** Upload .eml → Edit visually (TinyMCE) → Click editor's *Copy HTML* button → Paste into the 'Edited HTML' box below → Save & Download. Right-side shows English preview for PII spotting (not saved).")

uploaded = st.file_uploader("Upload a single .eml file (drag & drop supported)", type=["eml"], accept_multiple_files=False)
if not uploaded:
    st.stop()

raw = uploaded.read()
try:
    msg = parse_eml_bytes(raw)
except Exception as e:
    st.error(f"Cannot parse .eml: {e}")
    st.stop()

# Metadata show/edit
st.sidebar.header("Email headers (editable)")
from_val = st.sidebar.text_input("From", value=msg.get("From", "") or "")
to_val = st.sidebar.text_input("To", value=msg.get("To", "") or "")
subject_val = st.sidebar.text_input("Subject", value=msg.get("Subject", "") or "")
date_val = st.sidebar.text_input("Date", value=msg.get("Date", "") or "")

html_text, plain_text, attachments = extract_html_and_attachments(msg)
embedded_html = embed_inline_images_in_html(html_text, attachments) if html_text else None

# Detect language sample
sample_text = ""
if html_text:
    try:
        sample_text = BeautifulSoup(html_text, "html.parser").get_text()[:1500]
    except:
        sample_text = html_text[:1500]
elif plain_text:
    sample_text = plain_text[:1500]

detected_lang = None
if sample_text.strip():
    try:
        detected_lang = detect(sample_text)
    except:
        detected_lang = None

# Layout
left, right = st.columns([1.3, 1])

with left:
    st.subheader(f"Visual Editor (original language) — Detected: {detected_lang or 'unknown'}")
    if embedded_html:
        # TinyMCE embed + Copy button inside iframe
        tinymce_html = f"""
        <html>
        <head>
          <script src="https://cdn.tiny.cloud/1/no-api-key/tinymce/6/tinymce.min.js" referrerpolicy="origin"></script>
        </head>
        <body>
          <button onclick="copyContent()" style="margin-bottom:6px;padding:8px 12px;background:#1f77b4;color:#fff;border-radius:6px;border:0;">Copy HTML to clipboard</button>
          <textarea id="editor">{embedded_html}</textarea>
          <script>
            tinymce.init({{
              selector:'#editor',
              plugins: 'lists link image table paste help wordcount',
              toolbar: 'undo redo | bold italic underline | alignleft aligncenter alignright | bullist numlist | link image | table | removeformat',
              menubar: false,
              branding: false,
              paste_as_text: false,
              height: 520
            }});
            function copyContent(){{
              const content = tinymce.get('editor').getContent();
              navigator.clipboard.writeText(content).then(() => {{
                // show tiny message
                let b = document.querySelector('button');
                let old = b.innerText;
                b.innerText = 'Copied ✓ — now paste into Edited HTML box below';
                setTimeout(()=> b.innerText = old, 3000);
              }}, (err) => {{
                alert('Copy failed: ' + err);
              }});
            }}
          </script>
        </body>
        </html>
        """
        st.components.v1.html(tinymce_html, height=640, scrolling=True)
        st.markdown("**After editing inside the visual editor:** click **Copy HTML to clipboard**, then paste the HTML into the box below and click *Apply Edited HTML*.")
        edited_html_text = st.text_area("Edited HTML (paste editor content here to save)", value=html_text or "", height=280)
        if st.button("Apply Edited HTML"):
            # update session state copy
            st.session_state["edited_html"] = edited_html_text
            st.success("Edited HTML applied — you can now Download the .eml (below).")
    else:
        st.info("No HTML body found; showing plain text editor.")
        st.session_state["edited_html"] = st.text_area("Edit plain text body", value=plain_text or "", height=600)

    st.markdown("---")
    st.subheader("Attachments (kept when saving)")
    if attachments:
        for a in attachments:
            name = a.get("filename") or "(unnamed)"
            inline = " (inline)" if a.get("is_inline") else ""
            st.write(f"- {name} — {a.get('content_type')}{inline}")
    else:
        st.write("No attachments found.")

with right:
    st.subheader("English preview (read-only) — for PII spotting")
    if sample_text.strip():
        if detected_lang and detected_lang != "en":
            with st.spinner("Translating to English..."):
                translated = translate_text_to_english(sample_text)
            st.text_area("English translation (read-only)", value=translated, height=700)
        else:
            st.info("Detected language is English or unknown — translation not needed.")
            st.text_area("Email text (read-only)", value=sample_text, height=700)
    else:
        st.write("(no body to show)")

# Final save / download
st.markdown("---")
if st.button("💾 Prepare & Download Edited .eml (original language)"):
    # get final html to insert
    final_html = st.session_state.get("edited_html", html_text or "")
    # ensure we fallback to plain if none
    if html_text:
        final_msg = set_html_in_message(msg, final_html)
        # update/plain fallback
        try:
            plain_from_html = BeautifulSoup(final_html, "html.parser").get_text("\n")
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
        # only plain
        final_plain = st.session_state.get("edited_html", plain_text or "")
        if msg.is_multipart():
            replaced_plain = False
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    part.set_content(final_plain, subtype="plain")
                    replaced_plain = True
                    break
            if not replaced_plain:
                msg.set_content(final_plain)
        final_msg = msg

    # update headers from sidebar edits
    header_map = {"From": from_val, "To": to_val, "Subject": subject_val, "Date": date_val}
    for h, v in header_map.items():
        if h in final_msg:
            del final_msg[h]
        if v and v.strip():
            final_msg[h] = v

    out_bytes = eml_to_bytes(final_msg)
    st.success("Edited .eml ready.")
    st.download_button("⬇️ Download edited .eml", data=out_bytes, file_name=f"edited_{uploaded.name}", mime="message/rfc822")
