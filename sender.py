import time
import requests
import base64
import threading #* Needed for gmail_lock

from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from google.genai import types

from email_builder import create_email_body
from locker import gmail_lock
from main import mark_label, LABELS, DEFAULT_BACKUP_MODEL, aesgcm
from crypto_utils import seal, open_sealed

ALLOWED_FILE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/heic", "image/heif", 
                      "application/pdf", "application/x-javascript", "text/javascript", "application/x-python", "text/x-python", "text/plain", "text/html", "text/css", "text/md", "text/csv", "text/xml", "text/rtf",
                      "audio/wav", "audio/mp3", "audio/aiff", "audio/aac", "audio/ogg", "audio/flac"]

def ask_AI(client, model, question, attachments, db, thread_id, user_id):
    try:
        if user_id == 0: #* Not registered = Ignore Previous Conversations, Ignore Attachments 
            response = client.models.generate_content(
                model=model, contents=question
            )
            if response.text:
                return response
            else:
                print("No answer received from AI.1")

        result = db.find_one({"threadID": thread_id})
        if not result: #* No previous conversation found 
            print(f"No previous conversation found for thread ID: {thread_id}.")

            if attachments:
                attachments_raw = []
                size = 0

                for attachment in attachments:
                    if attachment["mimeType"] in ALLOWED_FILE_TYPES:
                        size += attachment["size"]
                        if size > 19900000: #* If the total size of attachments is larger than 19,90 MB
                            break

                        x = types.Part.from_bytes(data=attachment["data"], mime_type=attachment["mimeType"],)
                        attachments_raw.append(x)

                content = [question] + attachments_raw
                response = client.models.generate_content(model=model, contents=content)
                if response.text:
                    return response
                else :
                    print("No answer received from AI.2.1")
            else:
                response = client.models.generate_content(
                    model=model, contents=question
                )
                if response.text:
                    history = []
                    message = {"user": seal(aesgcm, question), "model": seal(aesgcm, response.text)} 
                    history.append(message)

                    newConvo = { "threadID": thread_id, "user_id": user_id, "history": history, "expireAt": datetime.now() + timedelta(days=7)}
                    db.insert_one(newConvo)

                    return response
                else:
                    print("No answer received from AI.2.2")

        elif result != None: #* Previous conversation found (but ignore attachments)
            chat_history = []
            for message in result["history"]:
                user_msg = open_sealed(aesgcm, message["user"])
                model_msg = open_sealed(aesgcm, message["model"])
                x = types.Content(role="user", parts=[types.Part(text=user_msg)])
                y = types.Content(role="model", parts=[types.Part(text=model_msg)])
                chat_history.append(x)
                chat_history.append(y)

            chat = client.chats.create(model=model, history=chat_history)
            response = chat.send_message(question)

            if response.text:
                history = result["history"]
                message = {"user": seal(aesgcm, question), "model": seal(aesgcm, response.text)}
                history.append(message)

                newValues = { "$set": { "history": history, "expireAt": datetime.now() + timedelta(days=7)}}
                db.update_one({"threadID": thread_id}, newValues)

                return response
            else:
                print("No answer received from AI.3")

    except Exception as e:
        print(f"Error generating AI content: {e}")

        if "The model is overloaded" in str(e):
            print("Model is overloaded, retrying with backup model...")
            return "OVERLOADED"

def send_reply(service, to, subject, thread_id, message_id, message_text, model, plan, cost, remaining_tokens):
    reply_start_time = time.perf_counter()

    html_content = create_email_body(message_text, model, plan, cost, remaining_tokens, thread_id)
    if not html_content:
        print("Error: HTML content is empty. Cannot send reply.")
        mark_label(service, message_id, LABELS["broken"])
        return
    
    top_img = requests.get("https://placehold.co/970x40/057dc7/fff/jpg?text=Placeholder")
    top_img_data = top_img.content
    bottom_img = requests.get("https://placehold.co/970x20/057dc7/fff/jpg?text=Placeholder")
    bottom_img_data = bottom_img.content

    message = MIMEMultipart(_subtype='related')
    html_body = MIMEText(html_content, _subtype='html')
    message.attach(html_body)

    top_img = MIMEImage(top_img_data, 'jpeg')
    top_img.add_header('Content-Id', '<top_banner>')
    top_img.add_header("Content-Disposition", "inline", filename="top_banner")
    message.attach(top_img)

    bottom_img = MIMEImage(bottom_img_data, 'jpeg')
    bottom_img.add_header('Content-Id', '<bottom_banner>')
    bottom_img.add_header("Content-Disposition", "inline", filename="bottom_banner")
    message.attach(bottom_img)

    message['to'] = to
    message['subject'] = "Re: " + subject
    message['In-Reply-To'] = message_id
    message['References'] = message_id
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    body = {'raw': raw_message, 'threadId': thread_id}
    
    try:
        with gmail_lock:
            service.users().messages().send(userId='me', body=body).execute()
            print(f"Replying to '{message_id}' <> '{thread_id}'")
    except Exception as error:
        print(f'A error happened: {error}')

    reply_end_time = time.perf_counter()
    print(f"Reply building and sending took {reply_end_time - reply_start_time:.2f} seconds.")