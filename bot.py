import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.request import HTTPXRequest
import PyPDF2
import docx
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
import os
import google.generativeai as genai
import pdf2image
import logging
from dotenv import load_dotenv
import aiohttp
from aiohttp import web

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Get environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Log Tesseract version
print(f"Tesseract version: {pytesseract.get_tesseract_version()}")

# Configure Gemini API
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# Store the last generated MCQs for download
last_mcqs = {}

# Function to split long messages
async def send_long_message(update: Update, text: str, max_length=4096):
    if len(text) <= max_length:
        await update.message.reply_text(text)
    else:
        for i in range(0, len(text), max_length):
            chunk = text[i:i + max_length]
            await update.message.reply_text(chunk)
            await asyncio.sleep(0.5)  # Small delay to avoid rate limits

# Preprocess image for better OCR
def preprocess_image_for_ocr(image):
    image = image.convert("L")  # Convert to grayscale
    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(3)  # Increase contrast
    enhancer = ImageEnhance.Brightness(image)
    image = enhancer.enhance(1.5)  # Increase brightness
    image = image.filter(ImageFilter.MedianFilter())  # Reduce noise
    return image

# Extract text from PDF (with OCR fallback)
def extract_text_from_pdf(file_path):
    try:
        with open(file_path, "rb") as file:
            reader = PyPDF2.PdfReader(file)
            text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            if text.strip():
                print("Direct PDF text extraction successful.")
                print(f"Extracted text: {text[:500]}...")
                return text[:10000]  # Limit text to 10,000 chars
    except Exception as e:
        print(f"Direct PDF text extraction failed: {e}")

    # Use OCR if direct extraction fails
    try:
        images = pdf2image.convert_from_path(file_path, dpi=300)  # Reduced DPI
        text = ""
        for img in images:
            img = preprocess_image_for_ocr(img)
            page_text = pytesseract.image_to_string(img, config='--psm 3 --oem 1')
            text += page_text + "\n"
        if text.strip():
            print("PDF OCR successful.")
            print(f"Extracted text: {text[:500]}...")
            return text[:10000]
        else:
            print("PDF OCR extracted no text.")
            return ""
    except Exception as e:
        print(f"PDF OCR failed: {e}")
        return ""

# Extract text from DOCX
def extract_text_from_docx(file_path):
    try:
        doc = docx.Document(file_path)
        text = ""
        for para in doc.paragraphs:
            text += para.text + "\n"
        if text.strip():
            print("DOCX text extraction successful.")
            print(f"Extracted text: {text[:500]}...")
            return text[:10000]
        else:
            print("DOCX extracted no text.")
            return ""
    except Exception as e:
        print(f"DOCX extraction failed: {e}")
        return ""

# Extract text from Image using OCR
def extract_text_from_image(file_path):
    try:
        img = Image.open(file_path)
        img = preprocess_image_for_ocr(img)
        text = pytesseract.image_to_string(img, config='--psm 3 --oem 1')
        if text.strip():
            print("Image OCR successful.")
            print(f"Extracted text: {text[:500]}...")
            return text[:10000]
        else:
            print("Image OCR extracted no text.")
            return ""
    except Exception as e:
        print(f"Image OCR failed: {e}")
        return ""

# Generate highly advanced, real-life applicable MCQs
def generate_mcqs(text):
    prompt = (
        "Generate 15-50 (depending on the length and contents of the note) highly advanced, real-life applicable multiple-choice questions (MCQs) based on the following notes. "
        "Each question should have 4 options (A, B, C, D) with one correct answer marked with ✅. "
        "Focus on complex, practical, applied-learning scenarios that require critical thinking and real-world problem-solving skills, rather than rote memorization. "
        "Ensure the questions are challenging and suitable for professionals or advanced learners in the relevant field.\n\n"
        "Notes:\n" + text
    )
    try:
        response = model.generate_content(prompt)
        mcqs = response.text
        print(f"Generated MCQs length: {len(mcqs)} characters")
        return mcqs
    except Exception as e:
        print(f"Gemini API failed: {e}")
        return f"Error generating MCQs: {str(e)}"

# Handle the /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Upload File", callback_data="upload")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Welcome to the MCQ Generator Bot!\n"
        "Click the button below to upload a PDF, DOCX, or image file with your notes, and I’ll generate real-life applicable MCQs.\nHACKER VIRUS INC!!!",
        reply_markup=reply_markup
    )

# Handle the /upload command
async def upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Please upload a PDF, DOCX, or image file with your notes.")

# Handle the /new command
async def new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Please upload a new PDF, DOCX, or image file with your notes.")

# Handle file uploads
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    file = update.message.document or (update.message.photo[-1] if update.message.photo else None)
    if not file:
        await update.message.reply_text("Please upload a PDF, DOCX, or image file.")
        return

    for attempt in range(3):
        try:
            await update.message.reply_text("Processing your file... Please wait.")
            break
        except telegram.error.TimedOut as e:
            print(f"TimedOut error on attempt {attempt + 1}: {e}")
            if attempt == 2:
                await update.message.reply_text("Network error: Unable to process your file due to a timeout. Please try again later.")
                return
            await asyncio.sleep(2)

    if update.message.photo:
        file_obj = await file.get_file()
        file_path = "downloaded_file.jpg"
        await file_obj.download_to_drive(file_path)
    else:
        file_obj = await file.get_file()
        file_path = f"downloaded_file.{file.file_name.split('.')[-1]}"
        await file_obj.download_to_drive(file_path)

    text = ""
    if file_path.endswith(".pdf"):
        text = extract_text_from_pdf(file_path)
    elif file_path.endswith(".docx"):
        text = extract_text_from_docx(file_path)
    elif file_path.endswith((".png", ".jpg", ".jpeg")):
        text = extract_text_from_image(file_path)
    else:
        await update.message.reply_text("Unsupported file type. Use PDF, DOCX, or images.")
        os.remove(file_path)
        return

    if not text.strip():
        await update.message.reply_text("No text could be extracted from the file. Please try another file.")
        os.remove(file_path)
        return

    mcqs = generate_mcqs(text)
    last_mcqs[user_id] = mcqs
    await send_long_message(update, mcqs)

    os.remove(file_path)

    keyboard = [
        [
            InlineKeyboardButton("Upload New File (/new)", callback_data="new"),
            InlineKeyboardButton("Download MCQs (/download)", callback_data="download"),
        ],
        [InlineKeyboardButton("End Session (/end)", callback_data="end")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("What next?", reply_markup=reply_markup)

# Handle button clicks
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "upload":
        await upload(query, context)
    elif query.data == "new":
        await new(query, context)
    elif query.data == "download":
        await download(query, context)
    elif query.data == "end":
        await end(query, context)

# Handle /download command
async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mcqs = last_mcqs.get(user_id, "No MCQs available to download.")
    with open("mcqs.txt", "w") as f:
        f.write(mcqs)
    with open("mcqs.txt", "rb") as f:
        await update.effective_message.reply_document(document=f, filename="mcqs.txt")
    os.remove("mcqs.txt")

# Handle /end command
async def end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    last_mcqs.pop(user_id, None)
    await update.effective_message.reply_text("Session ended. Use /start to begin again.")

# Main function
def main():
    # Log environment variables (without printing sensitive values)
    print("Environment variables:")
    print(f"TELEGRAM_TOKEN set: {bool(TELEGRAM_TOKEN)}")
    print(f"GEMINI_API_KEY set: {bool(GEMINI_API_KEY)}")
    print(f"PORT: {os.environ.get('PORT', '8000')}")
    print(f"RAILWAY: {os.environ.get('RAILWAY', 'not set')}")

    request = HTTPXRequest(
        connection_pool_size=10,
        read_timeout=60.0,
        connect_timeout=60.0,
        pool_timeout=60.0,
    )

    application = Application.builder().token(TELEGRAM_TOKEN).request(request).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("upload", upload))
    application.add_handler(CommandHandler("new", new))
    application.add_handler(CommandHandler("download", download))
    application.add_handler(CommandHandler("end", end))
    application.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_file))
    application.add_handler(CallbackQueryHandler(button))

    if "RAILWAY" in os.environ:
        port = int(os.environ.get("PORT", 8000))
        if "RAILWAY_PUBLIC_DOMAIN" not in os.environ:
            raise ValueError("RAILWAY_PUBLIC_DOMAIN environment variable is not set")
        webhook_url = f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN']}/webhook"

        # Create a custom aiohttp app with a health check endpoint
        app = aiohttp.web.Application()
        app.router.add_post("/webhook", application.create_webhook_handler())
        app.router.add_get("/health", lambda _: web.Response(text="OK"))

        try:
            print(f"Starting webhook server on port {port}...")
            application.run_webhook(
                listen="0.0.0.0",
                port=port,
                url_path="/webhook",
                webhook_url=webhook_url,
                custom_app=app
            )
            print(f"Bot is running with webhook at {webhook_url}")
        except Exception as e:
            print(f"Failed to start webhook server: {e}")
            raise
    else:
        application.run_polling()

if __name__ == "__main__":
    main()