# eml_editor_app.py
import streamlit as st
from email import policy
from email.parser import BytesParser
from email.message import EmailMessage
from email.generator import BytesGenerator
from io import BytesIO
from bs4 import BeautifulSoup
from googletrans import Translator
import base64
import re

st.set_page_config(page_title="EML Editor with Translate", layout="wide")
st.title("📧 EML Editor — Translate & Edit (Streamlit Prototype)")

translator = Translator()

# ---------- Helpers ----------
def parse_eml_bytes(raw_bytes):
    msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    return msg

def eml_to_bytes(msg):
    buf = BytesIO()
    BytesGenerator(buf, policy=policy.default).flatten(msg)
    return buf.getvalue()

def extract_parts(msg):
    """
    Returns a tuple: (plain_text, html_text, attachments_list)
    attachments_list: list of dict {filename, content_bytes, content_id, content_type, is_inline}
    """
    plain = None
    html = None
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = part.get_content_disposition()
            if ctype == "text/plain" and plain is None:
                try:
                    plain = part.get_content()
                except:
                    plain = part.get_payload(decode=True).decode(errors='ignore')
            elif ctype == "text/html" and html is None:
                try:
                    html = part.get_content()
                except:
                    html = part.get_payload(decode=True).decode(errors='ignore')
            elif disp in ("attachment", "inline") or part.get_filename():
                payload = part.get_payload(decode=True)
                attachments.append({
                    "filename": part.get_filename(),
                    "bytes": payload,
                    "content_id": (part.get("Content-ID") or "").strip("<>"),
                    "content_type": ctype,
                    "is_inline": (disp == "inline")
                })
    else:
        # single part
        if msg.get_content_type() == "text/plain":
            plain = msg.get_content()
        elif msg.get_content_type() == "text/html":
            html = msg.get_content()
    return plain, html, attachments

def translate_html_preserve(html_text, src, dest):
    """
    Translate only text nodes inside HTML while preserving tags/attributes.
    Uses BeautifulSoup to walk text nodes.
    """
    if not html_text:
        return html_text
    soup = BeautifulSoup(html_text, "html.parser")
    texts = []
    nodes = []
    # collect text nodes which are visible (skip script/style)
    for elem in soup.find_all(text=True):
        if elem.parent.name in ["script", "style"]:
            continue
        # skip whitespace-only
        if not elem.string or not elem.string.strip():
            continue
        texts.append(elem.string)
        nodes.append(elem)
    if not texts:
        return html_text
    # translate in bulk by joining with a delimiter (to reduce API calls)
    delim = "<<<STREAMLIT_DELIM>>>"
    joined = delim.join(texts)
    try:
        translated_joined = translator.translate(joined, src=src, dest=dest).text
    except Exception as e:
        st.error(f"Translation failed: {e}")
        return html_text
    translated_texts = translated_joined.split(delim)
    if len(translated_texts) != len(nodes):
        # fallback: translate individually
        translated_texts = []
        for t in texts:
            try:
                translated_texts.append(translator.translate(t, src=src, dest=dest).text)
            except:
                translated_texts.append(t)
    # replace
    for node, new in zip(nodes, translated_texts):
        node.replace_with(new)
    return str(soup)

def translate_plain_text(text, src, dest):
    if not text:
        return text
    try:
        res = translator.translate(text, src=src, dest=dest).text
        return res
    except Exception as e:
        st.error(f"Translation failed: {e}")
        return text

def detect_language(text_sample):
    if not text_sample or not text_sample.strip():
        return None
    try:
        d = translator.detect(text_sample)
        return d.lang
    except:
        return None

# ---------- UI ----------
uploaded = st.file_uploader("Upload a single .eml file", type=["eml"], accept_multiple_files=False)

if not uploaded:
    st.info("Please upload an .eml file to start editing. (Drag & drop supported)")
    st.stop()

raw = uploaded.read()
try:
    msg = parse_eml_bytes(raw)
except Exception as e:
    st.error(f"Failed to parse .eml: {e}")
    st.stop()

# Header editor
st.subheader("Headers (edit as needed)")
col1, col2 = st.columns(2)
with col1:
    from_val = st.text_input("From", value=msg.get("From", ""))
    to_val = st.text_input("To", value=msg.get("To", ""))
    cc_val = st.text_input("Cc", value=msg.get("Cc", ""))
    bcc_val = st.text_input("Bcc", value=msg.get("Bcc", ""))
with col2:
    subject_val = st.text_input("Subject", value=msg.get("Subject", ""))
    date_val = st.text_input("Date", value=msg.get("Date", ""))
    delivered_val = st.text_input("Delivered-To", value=msg.get("Delivered-To", ""))
    return_path_val = st.text_input("Return-Path", value=msg.get("Return-Path", ""))

# Extract body & attachments
plain_text, html_text, attachments = extract_parts(msg)

st.subheader("Body Editor & Translate")
left, right = st.columns([1,1])
with left:
    st.markdown("**Editable HTML (or plain text)** — edit here. Use Preview to see rendered output.")
    # prefer HTML if exists, else plain
    if html_text:
        body_content = st.text_area("HTML Body", value=html_text, height=320, key="body_html")
        current_source_is_html = True
    else:
        body_content = st.text_area("Plain Body", value=(plain_text or ""), height=320, key="body_plain")
        current_source_is_html = False

    # Language detection & translate buttons
    detected_lang = detect_language((html_text or plain_text)[:1000])
    detected_lang_label = detected_lang if detected_lang else "unknown"
    st.write(f"Detected language (sample): **{detected_lang_label}**")
    # Buttons for translate
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        if st.button("🌐 Translate to English"):
            src = detected_lang if detected_lang else "auto"
            if current_source_is_html:
                new_html = translate_html_preserve(body_content, src=src, dest="en")
                st.session_state["orig_lang"] = detected_lang or "auto"
                st.session_state["body_before_translate"] = body_content
                st.session_state["body_lang"] = detected_lang or "auto"
                # replace body content
                st.experimental_set_query_params()  # small hack to re-render
                st.session_state["body_html"] = new_html
                st.experimental_rerun()
            else:
                new_text = translate_plain_text(body_content, src=src, dest="en")
                st.session_state["orig_lang"] = detected_lang or "auto"
                st.session_state["body_before_translate"] = body_content
                st.session_state["body_lang"] = detected_lang or "auto"
                st.session_state["body_plain"] = new_text
                st.experimental_rerun()
    with col_t2:
        if st.button("↩️ Translate back to Original"):
            orig = st.session_state.get("body_lang", None)
            if not orig:
                st.warning("Original language unknown — cannot translate back reliably.")
            else:
                src = "en"
                dest = orig
                if current_source_is_html:
                    new_html = translate_html_preserve(body_content, src=src, dest=dest)
                    st.session_state["body_html"] = new_html
                    st.experimental_rerun()
                else:
                    new_txt = translate_plain_text(body_content, src=src, dest=dest)
                    st.session_state["body_plain"] = new_txt
                    st.experimental_rerun()

with right:
    st.markdown("**Rendered Preview**")
    if current_source_is_html:
        preview_html = body_content or "<i>(empty)</i>"
        st.components.v1.html(preview_html, height=320, scrolling=True)
    else:
        st.code(body_content or "(empty)")

st.subheader("Attachments")
st.write("Existing attachments found in the .eml (you can choose to keep/remove).")
keep_flags = []
if attachments:
    for i, att in enumerate(attachments):
        fn = att.get("filename") or f"attachment_{i}"
        colA, colB = st.columns([3,1])
        with colA:
            st.write(f"- **{fn}** — {att.get('content_type')} {'(inline)' if att.get('is_inline') else ''}")
        with colB:
            keep = st.checkbox(f"Keep {i}", value=True, key=f"keep_{i}")
            keep_flags.append(bool(keep))
else:
    st.info("No attachments found in uploaded .eml")

st.markdown("**Add new attachments (files you want to include)**")
new_attachments = st.file_uploader("Add attachments (multiple allowed)", accept_multiple_files=True)

# Prepare & Download
st.markdown("---")
if st.button("🛠️ Prepare Edited .eml for Download"):
    # Build new email
    new_msg = EmailMessage()
    # Set headers
    header_map = {
        "From": from_val,
        "To": to_val,
        "Cc": cc_val,
        "Bcc": bcc_val,
        "Subject": subject_val,
        "Date": date_val,
        "Delivered-To": delivered_val,
        "Return-Path": return_path_val
    }
    for h, v in header_map.items():
        # remove if empty
        if v and v.strip():
            new_msg[h] = v

    # Body parts
    final_plain = None
    final_html = None
    if current_source_is_html:
        final_html = body_content
        # try to extract a plain text fallback
        try:
            soup = BeautifulSoup(final_html, "html.parser")
            final_plain = soup.get_text("\n")
        except:
            final_plain = None
    else:
        final_plain = body_content

    if final_html and final_plain:
        new_msg.set_content(final_plain)
        new_msg.add_alternative(final_html, subtype="html")
    elif final_html:
        # only html
        new_msg.add_alternative(final_html, subtype="html")
    elif final_plain:
        new_msg.set_content(final_plain)
    else:
        new_msg.set_content("")

    # Attachments: keep selected existing ones
    for keep, att in zip(keep_flags, attachments):
        if not keep:
            continue
        payload = att["bytes"]
        if payload is None:
            continue
        maintype, subtype = att["content_type"].split("/", 1) if "/" in att["content_type"] else ("application", "octet-stream")
        try:
            new_msg.add_attachment(payload, maintype=maintype, subtype=subtype, filename=att.get("filename"))
        except Exception:
            # fallback: base64 attach as octet-stream
            new_msg.add_attachment(payload, maintype="application", subtype="octet-stream", filename=att.get("filename"))

    # Add newly uploaded attachments
    if new_attachments:
        for f in new_attachments:
            b = f.read()
            # try to guess maintype
            m = f.type or "application/octet-stream"
            maintype, subtype = m.split("/", 1) if "/" in m else ("application", "octet-stream")
            new_msg.add_attachment(b, maintype=maintype, subtype=subtype, filename=f.name)

    out_bytes = eml_to_bytes(new_msg)
    st.success("Edited .eml ready.")
    st.download_button("⬇️ Download edited .eml", data=out_bytes, file_name=f"edited_{uploaded.name}", mime="message/rfc822")
    # Also show small preview
    st.markdown("**Quick preview of headers:**")
    for k in ["From","To","Subject","Date"]:
        if new_msg[k]:
            st.write(f"**{k}:** {new_msg[k]}")
