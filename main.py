import os.path
import base64
import threading
import time
import json
import markdown
import os
import sys
from dotenv import load_dotenv
import requests
import re
from datetime import datetime, timedelta

from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from google import genai
from google.genai import types

import pymongo

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

ACTIVE_THREADS = set() #! Prevent multiple Answers from one message

ALLOWED_FILE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/heic", "image/heif", 
                      "application/pdf", "application/x-javascript", "text/javascript", "application/x-python", "text/x-python", "text/plain", "text/html", "text/css", "text/md", "text/csv", "text/xml", "text/rtf",
                      "audio/wav", "audio/mp3", "audio/aiff", "audio/aac", "audio/ogg", "audio/flac"]


models = {
    "gemini-2.0-flash": {
        "active": True,
        "name": "Google Gemini 2.0 Flash",
        "perm_level_required": 0,
        "context_per_hour": 1000000,
        "search_per_hour": 500
    },
    "gemini-2.5-flash-preview-05-20": {
        "active": True,
        "name": "Google Gemini 2.5 Flash Preview",
        "perm_level_required": 1,
        "context_per_hour": 0,
        "search_per_hour": 500
    },
    "gemini-2.5-pro-preview-05-06": {
        "active": False,
        "name": "Google Gemini 2.5 Pro Preview",
        "perm_level_required": 2,
        "context_per_hour": 0,
        "search_per_hour": 0
    },
    "gemini-1.5-flash": {
        "active": True,
        "name": "Google Gemini 1.5 Flash",
        "perm_level_required": 0,
        "context_per_hour": 1000000,
        "search_per_hour": 0
    },
    "gemini-1.5-pro": {
        "active": True,
        "name": "Google Gemini 1.5 Pro",
        "perm_level_required": 0,
        "context_per_hour": 0,
        "search_per_hour": 0
    }
}

no_messages_count = 0

client = genai.Client(api_key=os.getenv('gemini_API_key'))

gmail_lock = threading.Lock()

def authenticate_gmail():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    #! When no Local Credentials are available, we need to re-authenticate
    if not creds or not creds.valid:
        try:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)

            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        except Exception as e:
            print(f"Error during authentication: {e}\nDeleting token.json to re-authenticate. (Debug)")
            os.remove("token.json")
            x = authenticate_gmail()
            return x
    
    with gmail_lock:
        service = build('gmail', 'v1', credentials=creds) #* Create the Gmail service
    if not service:
        sys.exit("Failed to create Gmail service. Please check your credentials and try again.")
    print(f"Gmail service authenticated successfully.")
    return service

def connect_to_mongodb():
    try:
        mongo = pymongo.MongoClient("mongodb://localhost:27017/")
        db = mongo["convoDB"]
        table = db["conversations"]
        mongo.server_info()
        print("Connected to MongoDB successfully.")

    except Exception as e:
        print(f"Error connecting to MongoDB: {e}")
        sys.exit("Failed to connect to MongoDB.")
    
    return table

def get_unread_messages(service):
    with gmail_lock:
        results = service.users().messages().list(userId='me', labelIds=['INBOX', 'UNREAD'], maxResults=5).execute()
    messages = results.get('messages', [])
    return messages

def get_message_details(service, msg_id):
    with gmail_lock:
        msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    payload = msg.get('payload', {})
    headers = payload.get('headers', [])
    subject = ''
    sender = ''
    to_email = ''
    message_id = ''
    for header in headers:
        if header['name'] == 'Subject':
            subject = header['value']
        if header['name'] == 'From':
            sender = header['value']
        if header['name'] == 'To':
            to_email = header['value']
        if header['name'] == 'Message-ID':
            message_id = header['value']
    parts = payload.get('parts', [])
    body = ''
    attachments = []

    if parts:
        for part in parts:
            if part['mimeType'] == 'text/plain':
                data = part['body']['data']
                body = base64.urlsafe_b64decode(data).decode()

            elif part['mimeType'] == 'multipart/alternative': #* When email is a reply and it has the default gmail reply format
                try:
                    subparts = part.get('parts', [])
                    if subparts:
                        for subpart in subparts:
                            if subpart['mimeType'] == 'text/plain':
                                data = subpart['body']['data']
                                body = base64.urlsafe_b64decode(data).decode()
                                body = re.sub(r'<\s*([^\n\r<>]+?)\s*>', lambda m: f"<{m.group(1).strip()}>", body) #* Remove whitespace inside angle brackets
        
                                from_email_with_arrows = f"<{sender.split('<')[1].split('>')[0]}>"
                                to_email_with_arrows = f"<{to_email}>"

                                is_email_with_history = (sender.split('<')[1].split('>')[0] and from_email_with_arrows in body) or (to_email and to_email_with_arrows in body)

                                if is_email_with_history:
                                    history_email_with_arrows = find_first_substring(from_email_with_arrows, to_email_with_arrows, body)
                                    body = body[:body.index(history_email_with_arrows) + len(history_email_with_arrows)]
                                    from_regexp = re.compile(rf'^.*{re.escape(history_email_with_arrows)}.*$', re.MULTILINE)
                                    body = from_regexp.sub('', body)
                                else:
                                    body = base64.urlsafe_b64decode(data).decode()

                except Exception as e:
                    print(f"Error processing multipart/alternative: {e}")
                    data = part["body"]["data"]
                    body = base64.urlsafe_b64decode(data).decode()

            elif part['filename']:
                if 'data' in part['body']:
                    data = part['body']['data']
                else:
                    if part["body"]["size"] < 19900000: #* If the attachment is smaller than 19,90 MB
                        att_id = part['body']['attachmentId']
                        with gmail_lock:
                            att = service.users().messages().attachments().get(userId="me", messageId=msg_id,id=att_id).execute()
                        data = att['data']
                    else:
                        #ToDo: Implement Files API
                        break

                file_data = base64.urlsafe_b64decode(data.encode('UTF-8'))

                attachment = {
                    "name": part['filename'],
                    "size": part['body']['size'],
                    "mimeType": part['mimeType'],
                    "data": file_data
                }
                attachments.append(attachment)

    else:
        data = payload.get('body', {}).get('data')
        if data:
            body = base64.urlsafe_b64decode(data).decode()

    thread_id = msg.get('threadId')
    return subject, sender, body, message_id, thread_id, attachments

def find_first_substring(a, b, s):
    index_a = s.find(a)
    index_b = s.find(b)

    if index_a == -1:
        return b
    if index_b == -1:
        return a

    return a if index_a < index_b else b


def extract_details_from_subject(subject, default_model):
    s = subject.lower()

    for sep in [",", ";", "_", "/"]: #* Replace common separators with a space
        s = s.replace(sep, " ")

    sorted_models = sorted(list(models.keys()), key=lambda m: len(m), reverse=True) #* Sort models by length to match longer names first

    found_model = None
    for modell in sorted_models:
        if modell in s:
            found_model = modell
            break

    if not found_model:
        found_model = default_model #* If no model found, set to default

    #* Check for Parameters in subject
    has_reasoning = bool(re.search(r"\breasoning\b", s))

    #* Check for ID in subject.
    #ToDo: Implement IDs/Context Chache
    # match_id = re.search(r"\bid-(\d+)\b", s)
    # extracted_id = match_id.group(1) if match_id else None

    #? Maybe implement? only for debugging
    # temp = s.replace(found_model, " ")
    # if match_id:
    #     temp = temp.replace(match_id.group(0), " ")
    # temp = re.sub(r"\breasoning\b", " ", temp)
    # temp = re.sub(r"\s+", " ", temp).strip()
    # rest_tokens = temp.split() if temp else []

    return found_model, has_reasoning

def count_tokens(content, model):
    """
    Counts the number of tokens of the Input. Not the output!
    Might be useless later?
    """
    total_tokens = client.models.count_tokens(model=model, contents=content)
    return total_tokens

def mark_as_broken(service, msg_id):
    with gmail_lock:
        service.users().messages().modify(userId='me', id=msg_id, body={'addLabelIds': ["Label_55889426924201303"], 'removeLabelIds': ["Label_5310290292504501863", "UNREAD"]}).execute()

def mark_as_not_registered(service, msg_id):
    with gmail_lock:
        service.users().messages().modify(userId='me', id=msg_id, body={'addLabelIds': ["Label_6688557498746066945"], 'removeLabelIds': ["Label_5310290292504501863"]}).execute()

def mark_as_progressing(service, msg_id):
    with gmail_lock:
        service.users().messages().modify(userId='me', id=msg_id, body={'addLabelIds': ["Label_5310290292504501863"], 'removeLabelIds': ['UNREAD']}).execute()

def mark_as_answered(service, msg_id):
    with gmail_lock:
        service.users().messages().modify(userId='me', id=msg_id, body={'addLabelIds': ["Label_1030359169377715795"], 'removeLabelIds': ["Label_5310290292504501863"]}).execute()

def ask_AI(model, question, attachments, db, thread_id, user_id):
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
                    message = {"user": question, "model": response.text} 
                    history.append(message)

                    newConvo = { "threadID": thread_id, "user_id": user_id, "history": history, "expireAt": datetime.now() + timedelta(days=7)}
                    db.insert_one(newConvo)

                    return response
                else:
                    print("No answer received from AI.2.2")

        elif result != None: #* Previous conversation found (but ignore attachments)
            chat_history = []
            for message in result["history"]:
                x = types.Content(role="user", parts=[types.Part(text=message["user"])])
                y = types.Content(role="model", parts=[types.Part(text=message["model"])])
                chat_history.append(x)
                chat_history.append(y)

            chat = client.chats.create(model=model, history=chat_history)
            response = chat.send_message(question)
            # print(chat.get_history())
            if response.text:
                history = result["history"]
                message = {"user": question, "model": response.text}
                history.append(message)

                newValues = { "$set": { "history": history, "expireAt": datetime.now() + timedelta(days=7)}}
                db.update_one({"threadID": thread_id}, newValues)

                return response
            else:
                print("No answer received from AI.3")

        # print("--"*20)
        # chat = client.chats.create(model=model)
        # print(f"--\n{chat.__dict__}\n--")

        # response = chat.send_message(content)
        # print(f"-- AI Response --\n{response.text}\n--")
        # response = chat.send_message(message="Kannst du das nochmal in 1-2 Sätzen erklären?")
        # print(f"-- AI Response 2 --\n{response.text}\n--")

        # print(f"-- Chat History \n{chat.get_history()}\n--")
        # for message in chat.get_history():
        #     print(f'role - {message.role}',end=": ")
        #     print(message.parts[0].text)

        # print(f"--\n{chat.__dict__}\n--")
        # print("--"*20)
        # return response

        # response = client.models.generate_content(
        #     model=model, contents=content
        # )
        # if response.text:
        #     return response
        # else:
        #     print("No answer received from AI.")

    except Exception as e:
        print(f"Error generating AI content: {e}")

def create_email_body(answer_md, model, plan, cost, remaining_tokens, message_id):
    title = "AI Answer"
    links = {
        "GitHub": "https://github.com/KiSki-Dev",
        "Dashboard": "https://example.com/dashboard",
        "Discord": "https://discord.gg/cYqpx7dqsn"
    }

    answer_html = markdown.markdown(answer_md, extensions=['extra', 'sane_lists'])
    links_html = ' '.join(
        f'<a href="{url}" style="margin:0 10px; text-decoration:none; color:#38b0fa; font-weight:bold;">{text}</a>'
        for text, url in links.items()
    )

    return (f"""\
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>{title} - Email-AI</title>
  <style>
    body {{ margin:0; padding:0; background-color:#f0f9ff; color:#D4D4D4; font-family:'Segoe UI', Tahoma, sans-serif; }}
    a {{ color:#8ED1FC; }}
    .banner {{ text-align:center; }}
    .banner img {{ width:100%; height:100%; max-height: calc(100vw - 50px); border-radius:3px; }}
    h1 {{ font-size:32px; color:#74c7fb; text-align:center; margin:30px 0 10px; }}
    .info-row {{ font-size:18px; text-align:center; margin:5px 0; }}
    .info-row span {{ margin:0 20px; color:#46494a; }}
    .body-container {{ 
      background-color:#ebf7fe; 
      margin:0 20px 15px 20px; 
      padding:25px; 
      border-radius:8px; 
      box-shadow:0 3px 6px rgba(0,0,0,0.5); 
      font-size:13px; 
      line-height:1.6; 
      color:#080808; 
    }}
    .message-id {{ font-size:12px; color:#777; text-align:left; margin:0 20px 20px 20px; }}
    .links-row {{ text-align:center; margin-bottom:30px; }}
  </style>
</head>
<body>

  <!-- Top-Banner -->
  <div class="banner" style="background:#b4e1fd;">
    <img src="cid:top_banner" alt="top banner"/>
  </div>

  <!-- Title -->
  <h1>{title}</h1>

  <!-- User-Details -->
  <div class="info-row">
    <span><strong>Model:</strong> {model}</span>
    <span><strong>Plan:</strong> {plan}</span>
  </div>

  <!-- Answer-Details -->
  <div class="info-row" style="margin-bottom:30px;">
    <span><strong>Cost of this Answer:</strong> {cost} Tokens</span>
    <span><strong>Remaining:</strong> {remaining_tokens} Tokens</span>
  </div>

  <!-- Answer-Body -->
  <div class="body-container">
    {answer_html}
  </div>

  <!-- Message-ID -->
  <div class="message-id">
    Message-ID: {message_id}
  </div>

  <!-- Links -->
  <div class="links-row">
    {links_html}
  </div>

  <!-- Bottom-Banner -->
  <div class="banner" style="background:#b4e1fd;">
    <img src="cid:bottom_banner" alt="bottom banner"/>
  </div>

</body>
</html>
""")

def send_reply(service, to, subject, thread_id, message_id, message_text, model, plan, cost, remaining_tokens):
    reply_start_time = time.perf_counter()

    html_content = create_email_body(message_text, model, plan, cost, remaining_tokens, thread_id)
    if not html_content:
        print("Error: HTML content is empty. Cannot send reply.")
        mark_as_broken(service, message_id)
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
    message['subject'] = "Re:" + subject
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

def handle_message(service, db, message):
    thread_start_time = time.perf_counter()
    msg_id = message['id']
    try:
        mark_as_progressing(service, msg_id)

        subject, sender, body, message_id, thread_id, attachments = get_message_details(service, msg_id)
        sender = sender.split('<')[1].split('>')[0]

        #ToDo Implement Database
        users = json.load(open("users.json", "r", encoding="utf-8"))
        user = next((u for u in users if u["email"] == sender), None)
        if not user:
            default_model = "gemini-2.0-flash"
        else:
            default_model = user["model"]
        
        model, use_reasoning = extract_details_from_subject(subject, default_model)

        if models[model]["active"] == False:
            print(f"Model '{model}' is deactivated.")
            return
        if models[model]["perm_level_required"] != 0:
            if not user:
                print(f"Error: User '{sender}' is not registered and cant use this Model.")
                mark_as_not_registered(service, msg_id)
                print("="*40)
                return
            
            if user["plan"] == "Premium": 
                perm_level = 1
            elif user["plan"] == "Developer":
                perm_level = 2
            else:
                perm_level = 0

            if models[model]["perm_level_required"] > perm_level:
                print(f"Error: Model '{model}' requires a higher permission level than the user has.")
                mark_as_broken(service, msg_id)
                print("="*40)
                return

        #! input_tokens = count_tokens(body, model)

        if not user:
            plan = "Unregistered"
            tokens = 420
        else:
            print(f'{user["plan"]} User "{user["email"]}" (ID: {user["user_id"]}) has {user["tokens"]} Tokens left.')
            plan = user["plan"]
            tokens = user["tokens"] 
        
        #* Give input to AI and receive answer
        ai_start_time = time.perf_counter()
        answer = ask_AI(model, body, attachments, db, thread_id, user["user_id"] if user else 0)
        if not answer:
            print(f"Error: No answer generated for message {msg_id}.")
            mark_as_broken(service, msg_id)
            return
        print(f"Costed {str(answer.usage_metadata.total_token_count)} Tokens using '{model}' model.")
        ai_end_time = time.perf_counter()
        print(f"AI processing took {ai_end_time - ai_start_time:.2f} seconds.")

        #* Send AI-generated reply
        send_reply(service, sender, subject, thread_id, message_id, answer.text, model, plan, str(answer.usage_metadata.total_token_count), tokens)
        mark_as_answered(service, msg_id)

    except Exception as e:
        print(f"A error appeared inside handle_message(). {e}")
        mark_as_broken(service, msg_id)

    ACTIVE_THREADS.remove(thread_id)

    thread_end_time = time.perf_counter()
    print(f"Thread {threading.current_thread().name} finished in {thread_end_time - thread_start_time:.2f} seconds.")
    print("="*40)


def main(service, db):
    messages = get_unread_messages(service)
    global no_messages_count
    if not messages:
        no_messages_count += 1
        sys.stdout.write(f"No new messages found. [{no_messages_count}]\r")
        sys.stdout.flush()

    else:
        for message in messages:
            if message['threadId'] in ACTIVE_THREADS:
                print(f"Thread {message['threadId']} is already being processed. Skipping.")
                mark_as_broken(service, message['id'])

            else:
                # print(message)
                no_messages_count = 0
                ACTIVE_THREADS.add(message['threadId'])
                t = threading.Thread(target=handle_message, name=f'Reply+{message['threadId']}', args=(service, db, message), daemon=True)
                t.start()
                print(f"Thread started: {t.name}. [{time.ctime()}]")

            time.sleep(0.5) #? Sleep to prevent SSL Error: [SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:997) when too many threads are started at once


if __name__ == '__main__':
    try:
        service = authenticate_gmail()
        db = connect_to_mongodb()
        # print(service.users().labels().list(userId='me').execute()) #! List all labels

        while True:
            try:
                main(service, db)
            except Exception as e:
                print(f"[{time.ctime()}] Fehler in main(): {e}", file=sys.stderr)
            time.sleep(10)
                
    except KeyboardInterrupt:
        print(f"\n{"="*70}\nProgram terminated by user.")