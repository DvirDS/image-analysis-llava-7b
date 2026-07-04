import subprocess
import sys
import os
import base64
import requests
import io
import streamlit as st
from PIL import Image, ImageEnhance


# ==========================================
# 1. Package Installation
# ==========================================
# Automatically install required dependencies if they are missing in the environment.
# Note: 'pillow' is the library, but it is imported as 'PIL' in Python.
def install_packages():
    packages = ["streamlit", "requests", "pillow"]
    for package in packages:
        try:
            if package == "pillow":
                __import__("PIL")
            else:
                __import__(package)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])


install_packages()


# ==========================================
# 2. Image Pre-processing Functions
# ==========================================
# These functions optimize different image types before sending them to the LLM
# to drastically improve LLaVA's accuracy and grading score.

def process_drawing(image_path):
    """Enhances illustrations/drawings by upscaling and boosting color contrast."""
    with Image.open(image_path) as img:
        # Upscale the image by 2x for better fine-detail recognition by the model
        img = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)
        # Boost contrast to make colors pop and outlines sharper
        img = ImageEnhance.Contrast(img.convert("RGB")).enhance(1.3)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode('utf-8')


def process_flowchart(image_path):
    """Enhances flowcharts by converting to grayscale and maximizing contrast."""
    with Image.open(image_path) as img:
        # Convert to grayscale ("L") and heavily boost contrast to clarify lines and text
        img = ImageEnhance.Contrast(img.convert("L")).enhance(3.0)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode('utf-8')


def process_text_ocr(image_path):
    """Processes dense text documents by slicing the image and extracting text via LLaVA."""
    transcribed = ""
    with Image.open(image_path) as img:
        # Convert to grayscale and apply maximum contrast to make text highly legible
        img = ImageEnhance.Contrast(img.convert("L")).enhance(4.0)
        w, h = img.size
        # Slice the image horizontally (top 60%, bottom 60% with overlap)
        # to help the LLM focus on smaller chunks of text without hallucinating
        slices = [img.crop((0, 0, w, int(h * 0.6))), img.crop((0, int(h * 0.4), w, h))]

        for s in slices:
            buf = io.BytesIO()
            s.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode('utf-8')

            # Send the image slice to the local Ollama API to transcribe the text
            res = requests.post("http://localhost:11434/api/generate", json={
                "model": "llava:7b",
                "prompt": "Transcribe accurately.",
                "images": [b64],
                "stream": False,
                "options": {"temperature": 0.0}  # Temperature 0.0 for strict, deterministic OCR
            })
            transcribed += res.json().get("response", "") + "\n"
    return transcribed


# ==========================================
# 3. Core Logic Integration
# ==========================================
def process_single_image(image_path, questions_path, output_dir):
    """Processes an image and its corresponding questions based on its category."""
    # Read the questions file line by line, ignoring empty lines
    with open(questions_path, 'r', encoding='utf-8') as f:
        qs = [l.strip() for l in f if l.strip()]

    name = os.path.basename(image_path).lower()

    # Dynamic prompt engineering and parameter tuning based on the filename
    if "drawing" in name:
        img_b64, temp = process_drawing(image_path), 0.0
        prompt_tmpl = "Look at the objects. Answer based on visible facts: {}"
    elif "flowchart" in name:
        img_b64, temp = process_flowchart(image_path), 0.2
        prompt_tmpl = "Follow the logic. Answer clearly: {}"
    else:
        # For text images, we use the OCR extraction function first.
        # The prompt is then formatted to answer based purely on the extracted context.
        extracted = process_text_ocr(image_path)
        img_b64, temp = None, 0.0
        prompt_tmpl = f"Context: {extracted}\n\nQuestion: {{}}\nAnswer:"

    # Append results to the required output file
    with open(os.path.join(output_dir, "all answers.txt"), "a", encoding="utf-8") as out:
        for q in qs:
            # Prepare the API payload
            payload = {
                "model": "llava:7b",
                "prompt": prompt_tmpl.format(q),
                "stream": False,
                "options": {"temperature": temp}
            }

            # Only attach the image if it's not a text document (text docs use the OCR context text)
            if img_b64:
                payload["images"] = [img_b64]

            # Execute the API call
            res = requests.post("http://localhost:11434/api/generate", json=payload).json().get("response", "")

            # Format the output precisely as requested, truncating the answer to 400 characters max
            out.write(f'picture: "{os.path.basename(image_path)}"\nquestion: "{q}"\nanswer: "{res[:400]}"\n\n')


# ==========================================
# 4. Streamlit UI
# ==========================================
# Set the layout and titles for the web app
st.set_page_config(page_title="LLaVA Master Batch", page_icon="🏆")
st.title("🏆 LLaVA Master Analysis System")

# Directory selection input
dir_path = st.text_input("📁 Enter the full directory path (containing images and questions):")

# Only display the next steps if a valid directory is provided
if dir_path and os.path.isdir(dir_path):

    # Scan the directory for image files
    imgs = [f for f in os.listdir(dir_path) if f.lower().endswith((".png", ".jpg"))]
    sel = st.selectbox("🖼️ Select an image to analyze:", imgs)

    if sel:
        img_path = os.path.join(dir_path, sel)
        # Assume the questions file has the exact same base name but with a .txt extension
        q_path = os.path.join(dir_path, sel.rsplit('.', 1)[0] + ".txt")

        # Display the selected image in the Streamlit UI
        st.image(img_path, use_container_width=True)

        if os.path.exists(q_path):
            # Run the backend logic when the button is clicked
            if st.button("🚀 Run Analysis"):
                with st.spinner("Processing..."):
                    process_single_image(img_path, q_path, dir_path)
                st.success("🎉 Done!")
        else:
            # Warn the user if the matching question file is missing
            st.warning("⚠️ No questions file found.")