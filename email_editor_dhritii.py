# eml_html_translate_editor.py
import streamlit as st
from email import policy
from email.parser import BytesParser
from email.generator import BytesGenerator
from io import BytesIO
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from langdetect import detect, DetectorFactory
import base64
import re

# make langdetect deterministic
DetectorFactory.seed = 0

st.set_page_config(page_title="EML HTML Editor + Translate (UI-only)", layout="wide")
st.title("📧 EML Editor — HTML preserving + English preview (translation UI-only)")

# ----------------- Helpers -----------------
def parse_eml_bytes(raw_bytes):
    return BytesParser(policy=policy.default).parsebytes(raw_bytes)

def extract_html_and_attachments(msg):
    """
    Returns (html_content (str or None), plain_text (str or None), attachments_list)
    attachments_list: list of dict with keys: part (EmailPart), filename, content_bytes, content_type, content_id, is_inline
    """
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
                # treat attachments and inline images
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
        # single part message
        if msg.get_content_type() == "text/html":
            html = msg.get_content()
        elif msg.get_content_type() == "text/plain":
            plain = msg.get_content()
    return html, plain, attachments

def embed_inline_images_in_html(html_text, attachments):
    """
    Replace cid:... with data:image/...;base64,... so streamed preview shows inline images.
    Returns HTML with embedded data URIs.
    """
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
        # replace both cid:cid and "cid:cid"
        out_html = out_html.replace(f"cid:{cid}", datauri)
    return out_html

def translate_html_preserve(html_text, target="en"):
    """
    Translate visible text nodes inside HTML using deep-translator's GoogleTranslator.
    Uses a delimiter bulk-translate approach to reduce API calls.
    """
    if not html_text:
        return html_text
    soup = BeautifulSoup(html_text, "html.parser")
    texts = []
    nodes = []
    # collect visible text nodes
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
    # if mismatch, fallback to per-text translation (safer)
    if len(translated_texts) != len(nodes):
        translated_texts = []
        for t in texts:
            try:
                translated_texts.append(GoogleTranslator(source="auto", target=target).translate(t))
            except:
                translated_texts.append(t)
    # replace nodes
    for node, new in zip(nodes, translated_texts):
        node.replace_with(new)
    return str(soup)

def set_html_in_message(orig_msg, new_html):
    """
    Replace the first text/html part's content with new_html in-place.
    If no html part exists, add an alternative html part preserving other parts.
    Returns the modified message object.
    """
    msg = orig_msg
    if msg.is_multipart():
        replaced = False
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                # replace content; preserve charset etc.
                part.set_content(new_html, subtype="html")
                replaced = True
                break
        if not replaced:
            # no html part found; attach alternative html while preserving original headers
            # create an HTML part and append - simpler approach:
            from email.message import EmailMessage
            html_part = EmailMessage()
            html_part.set_content(new_html, subtype="html")
            msg.make_mixed()
            msg.attach(html_part)
    else:
        # single part -> replace or create multipart alternative
        if msg.get_content_type() == "text/html":
            msg.set_content(new_html, subtype="html")
        else:
            # convert to multipart/alternative
            from email.message import EmailMessage
            new = EmailMessage()
            # copy headers
            for k in msg.keys():
                new[k] = msg[k]
            # set plain first
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

# ----------------- UI -----------------
uploaded = st.file_uploader("Upload a single .eml file", type=["eml"], accept_multiple_files=False)
if not uploaded:
    st.info("Upload an .eml file (drag & drop supported). App will preserve formatting and attachments.")
    st.stop()

raw = uploaded.read()
try:
    msg = parse_eml_bytes(raw)
except Exception as e:
    st.error(f"Failed to parse .eml: {e}")
    st.stop()

# show basic headers editable
st.subheader("Headers (editable)")
colh1, colh2 = st.columns(2)
with colh1:
    from_val = st.text_input("From", value=msg.get("From", ""))
    to_val = st.text_input("To", value=msg.get("To", ""))
    cc_val = st.text_input("Cc", value=msg.get("Cc", ""))
with colh2:
    subject_val = st.text_input("Subject", value=msg.get("Subject", ""))
    date_val = st.text_input("Date", value=msg.get("Date", ""))

# Extract HTML, attachments
html_text, plain_text, attachments = extract_html_and_attachments(msg)
embedded_html = embed_inline_images_in_html(html_text, attachments) if html_text else None

# Detect language sample (try HTML text or plain)
sample_for_detect = ""
if html_text:
    try:
        soup_tmp = BeautifulSoup(html_text, "html.parser")
        sample_for_detect = soup_tmp.get_text()[:1000]
    except:
        sample_for_detect = html_text[:1000]
elif plain_text:
    sample_for_detect = plain_text[:1000]

detected_lang = None
if sample_for_detect.strip():
    try:
        detected_lang = detect(sample_for_detect)
    except:
        detected_lang = None

# Layout: left = Original (render & edit), right = English preview
left, right = st.columns([1.2, 1])

with left:
    st.markdown("### Original (editable HTML) — this is the version you'll save & download")
    if embedded_html:
        # Show rendered original HTML (with embedded inline images)
        st.markdown("**Rendered preview (Original language, formatting preserved)**")
        st.components.v1.html(embedded_html, height=420, scrolling=True)
        # Provide editable HTML textarea (for advanced edits). You can also add a WYSIWYG later.
        st.markdown("**Edit HTML (advanced)** — edit the HTML body directly. Keep inline `<img src=\"data:...\">` tags intact.")
        # initialize session_state to preserve edits
        if "edited_html" not in st.session_state:
            st.session_state["edited_html"] = html_text
        st.session_state["edited_html"] = st.text_area("HTML Body (edit here)", value=st.session_state["edited_html"], height=280)
    else:
        st.info("No HTML body found — showing plain text body instead.")
        if "edited_plain" not in st.session_state:
            st.session_state["edited_plain"] = plain_text or ""
        st.session_state["edited_plain"] = st.text_area("Plain Body (edit)", value=st.session_state["edited_plain"], height=420)

    st.markdown("---")
    st.markdown("**Attachments found** (kept unchanged when saving):")
    if attachments:
        for i, a in enumerate(attachments):
            name = a.get("filename") or f"attachment_{i}"
            inline_flag = "(inline)" if a.get("is_inline") else ""
            st.write(f"- {name} — {a.get('content_type')} {inline_flag}")
    else:
        st.write("No attachments found.")

with right:
    st.markdown("### English preview (UI-only) — for understanding / PII spotting")
    st.write(f"Detected source language (sample): **{detected_lang or 'unknown'}**")
    st.markdown("**Translated preview (read-only). Translation is not saved into the downloaded .eml.**")
    # Translate HTML (preserve tags)
    if embedded_html:
        # Use translated result cached in session to avoid repeated calls
        cache_key = f"trans_en_{hash(embedded_html)}"
        if cache_key not in st.session_state:
            with st.spinner("Translating to English..."):
                try:
                    translated_html = translate_html_preserve(embedded_html, target="en")
                except Exception as e:
                    st.error(f"Translate error: {e}")
                    translated_html = embedded_html
            st.session_state[cache_key] = translated_html
        else:
            translated_html = st.session_state[cache_key]
        st.components.v1.html(translated_html, height=700, scrolling=True)
    else:
        # plain text
        if plain_text:
            try:
                translated = GoogleTranslator(source="auto", target="en").translate(plain_text)
            except Exception as e:
                translated = plain_text
            st.text_area("Translated Plain Text (read-only)", value=translated, height=600, disabled=True)
        else:
            st.write("(no body to translate)")

# Save / Prepare download
st.markdown("---")
if st.button("🛠️ Prepare & Download Edited .eml (original language)"):
    # Build final message by replacing html part in original message with edited HTML (or edited plain)
    if html_text:
        final_html_to_put = st.session_state.get("edited_html", html_text)
        final_msg = set_html_in_message(msg, final_html_to_put)
        # Also update plain text fallback if present
        try:
            # create plain text from HTML
            plain_from_html = BeautifulSoup(final_html_to_put, "html.parser").get_text("\n")
        except:
            plain_from_html = None
        if plain_from_html:
            # replace first text/plain part if exists
            replaced_plain = False
            if final_msg.is_multipart():
                for part in final_msg.walk():
                    if part.get_content_type() == "text/plain":
                        part.set_content(plain_from_html, subtype="plain")
                        replaced_plain = True
                        break
            if not replaced_plain:
                # add a plain fallback
                final_msg.set_content(plain_from_html)
    else:
        # only plain
        final_plain = st.session_state.get("edited_plain", plain_text or "")
        # replace plain part
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

    # Update headers from user's edits
    header_map = {
        "From": from_val,
        "To": to_val,
        "Cc": cc_val,
        "Subject": subject_val,
        "Date": date_val
    }
    # remove then set for these headers to avoid duplicates
    for h, v in header_map.items():
        if h in final_msg:
            del final_msg[h]
        if v and v.strip():
            final_msg[h] = v

    out_bytes = eml_to_bytes(final_msg)
    st.success("Edited .eml ready for download (original language preserved).")
    st.download_button("⬇️ Download edited .eml", data=out_bytes, file_name=f"edited_{uploaded.name}", mime="message/rfc822")
