import os
import json
import base64
from fastapi import FastAPI, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, ImageMessage, TextMessage, TextSendMessage
import anthropic

app = FastAPI()

# ---- ตั้งค่าจาก Environment Variables (ไม่ใส่ค่าจริงตรงนี้) ----
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


@app.get("/")
async def health_check():
    """ใช้เช็คว่า server ยังทำงานอยู่"""
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()

    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    return "OK"


@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    """ตอบข้อความทดสอบเบื้องต้น"""
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="ส่งรูปใบเสร็จมาได้เลยครับ เดี๋ยวช่วยอ่านให้ 📄")
    )


@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    """รับรูปใบเสร็จ -> ส่งให้ Claude อ่าน -> ตอบกลับสรุป"""
    message_id = event.message.id
    content = line_bot_api.get_message_content(message_id)
    image_bytes = b"".join(chunk for chunk in content.iter_content())

    try:
        result = extract_receipt(image_bytes)
        reply_text = format_receipt_reply(result)
    except Exception as e:
        reply_text = f"ขอโทษครับ อ่านรูปนี้ไม่สำเร็จ ({str(e)}) ลองส่งใหม่อีกครั้งนะครับ"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )


def extract_receipt(image_bytes: bytes) -> dict:
    """ส่งรูปไปให้ Claude อ่านและดึงข้อมูลใบเสร็จ คืนค่าเป็น dict"""
    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    response = claude_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": b64_image,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        "อ่านใบเสร็จ/บิลนี้ แล้วตอบกลับเป็น JSON เท่านั้น "
                        "ห้ามมีข้อความอื่นนอกจาก JSON โครงสร้างนี้: "
                        '{"date": "วว/ดด/ปปปป หรือ null ถ้าอ่านไม่ได้", '
                        '"vendor": "ชื่อร้าน/ผู้ขาย", '
                        '"amount": ตัวเลขยอดรวม, '
                        '"vat": ตัวเลขภาษีมูลค่าเพิ่ม หรือ null, '
                        '"category": "หมวดหมู่ค่าใช้จ่าย เช่น ค่าซอฟต์แวร์ ค่าเดินทาง ค่าอาหาร"}'
                    ),
                },
            ],
        }],
    )

    raw_text = response.content[0].text.strip()
    # เผื่อ Claude ตอบมาพร้อม ```json ครอบ ให้ตัดออก
    raw_text = raw_text.replace("```json", "").replace("```", "").strip()
    return json.loads(raw_text)


def format_receipt_reply(data: dict) -> str:
    """แปลง dict เป็นข้อความสรุปอ่านง่ายสำหรับตอบกลับใน LINE"""
    return (
        "📄 อ่านใบเสร็จแล้วครับ\n\n"
        f"ร้าน: {data.get('vendor', '-')}\n"
        f"วันที่: {data.get('date', '-')}\n"
        f"ยอดเงิน: {data.get('amount', '-')} บาท\n"
        f"VAT: {data.get('vat', '-')}\n"
        f"หมวดหมู่: {data.get('category', '-')}\n\n"
        "ถ้าข้อมูลถูกต้อง พิมพ์ \"ยืนยัน\" เพื่อบันทึก"
    )
