import os.path
import base64
import email
import threading
import time
import sys
import json
import markdown
import os
from dotenv import load_dotenv

from email.mime.text import MIMEText
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from google import genai

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
LABEL_ANSWERED = 'Label_1030359169377715795'
LABEL_PROGRESSING = 'Label_5310290292504501863'
LABEL_BROKEN = 'Label_55889426924201303'
LABEL_NOT_REGISTERED = 'Label_6688557498746066945'

client = genai.Client(api_key=os.getenv('gemini_API_key'))

def authenticate_gmail():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    # When no Local Credentials are available, we need to re-authenticate
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    
    # Create the Gmail service
    service = build('gmail', 'v1', credentials=creds)
    return service

def get_unread_messages(service):
    results = service.users().messages().list(userId='me', labelIds=['INBOX', 'UNREAD'], maxResults=10).execute()
    messages = results.get('messages', [])
    return messages

def get_message_details(service, msg_id):
    msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    payload = msg.get('payload', {})
    headers = payload.get('headers', [])
    subject = ''
    sender = ''
    message_id = ''
    for header in headers:
        if header['name'] == 'Subject':
            subject = header['value']
        if header['name'] == 'From':
            sender = header['value']
        if header['name'] == 'Message-ID':
            message_id = header['value']
    parts = payload.get('parts', [])
    body = ''
    if parts:
        for part in parts:
            if part['mimeType'] == 'text/plain':
                data = part['body']['data']
                body = base64.urlsafe_b64decode(data).decode()
                break
    else:
        data = payload.get('body', {}).get('data')
        if data:
            body = base64.urlsafe_b64decode(data).decode()
    thread_id = msg.get('threadId')
    return subject, sender, body, message_id, thread_id

def count_tokens(content, model):
    total_tokens = client.models.count_tokens(model=model, contents=content)
    return total_tokens

def create_email_body(answer_md, model, plan, cost, remaining_tokens, message_id):
    title = "AI Answer"
    top_banner_url = "https://placehold.co/600x100"
    bottom_banner_url = "https://placehold.co/600x50"
    links = {
        "GitHub": "https://github.com/KiSki-Dev",
        "Dashboard": "https://example.com/dashboard",
        "Discord": "https://discord.gg/cYqpx7dqsn"
    }

    answer_html = markdown.markdown(answer_md, extensions=['extra', 'sane_lists'])
    links_html = ' '.join(
        f'<a href="{url}" style="margin:0 10px; text-decoration:none; color:#8ED1FC; font-weight:bold;">{text}</a>'
        for text, url in links.items()
    )

    x = f"""\
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>{title} - Email-AI</title>
  <style>
    body {{ margin:0; padding:0; background-color:#1E1E1E; color:#D4D4D4; font-family:'Segoe UI', Tahoma, sans-serif; }}
    a {{ color:#8ED1FC; }}
    .banner {{ text-align:center; }}
    .banner img {{ width:100%; height:100%; max-height: calc(100vw - 50px); border-radius:3px; }}
    h1 {{ font-size:32px; color:#8ED1FC; text-align:center; margin:30px 0 10px; }}
    .info-row {{ font-size:18px; text-align:center; margin:5px 0; }}
    .info-row span {{ margin:0 20px; color:#C0C0C0; }}
    .body-container {{ 
      background-color:#2A2A2A; 
      margin:0 20px 30px 20px; 
      padding:25px; 
      border-radius:8px; 
      box-shadow:0 3px 6px rgba(0,0,0,0.5); 
      font-size:13px; 
      line-height:1.6; 
      color:#E0E0E0; 
    }}
    .message-id {{ font-size:12px; color:#777; text-align:right; margin:0 20px 20px 20px; }}
    .links-row {{ text-align:center; margin-bottom:30px; }}
  </style>
</head>
<body>

  <!-- Top-Banner -->
  <div class="banner" style="background:#111111;">
    <img src="{top_banner_url}" alt="top banner">
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
  <div class="banner" style="background:#111111;">
    <img src="{bottom_banner_url}" alt="bottom banner">
  </div>

</body>
</html>
"""
    return x
    

def ask_AI(model, content):
    try:
        response = client.models.generate_content(
            model=model, contents=content
        )
        if response.text:
            return response
        else:
            print("No answer received from AI.")
            return None
    except Exception as e:
        print(f"Error generating AI content: {e}")
        return None

def send_reply(service, to, subject, thread_id, message_id, message_text, model, plan, cost, remaining_tokens):
    html_content = create_email_body(message_text, model, plan, cost, remaining_tokens, message_id)
    print(html_content)
    if not html_content:
        print("Error: HTML content is empty. Cannot send reply.")
        mark_as_broken(service, message_id)
        return

    message = MIMEText(html_content, "html")
    message['to'] = to
    message['subject'] = subject
    message['In-Reply-To'] = message_id
    message['References'] = message_id
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    body = {'raw': raw_message, 'threadId': thread_id}
    
    try:
        sent_message = service.users().messages().send(userId='me', body=body).execute()
        print(f'Send Answer: {sent_message["id"]}')

    except Exception as error:
        print(f'A error happened: {error}')

def mark_as_broken(service, msg_id):
    service.users().messages().modify(userId='me', id=msg_id, body={'addLabelIds': [LABEL_BROKEN], 'removeLabelIds': [LABEL_PROGRESSING]}).execute()

def mark_as_not_registered(service, msg_id):
    service.users().messages().modify(userId='me', id=msg_id, body={'addLabelIds': [LABEL_NOT_REGISTERED], 'removeLabelIds': [LABEL_PROGRESSING]}).execute()

def mark_as_progressing(service, msg_id):
    service.users().messages().modify(userId='me', id=msg_id, body={'addLabelIds': [LABEL_PROGRESSING], 'removeLabelIds': ['UNREAD']}).execute()

def mark_as_answered(service, msg_id):
    service.users().messages().modify(userId='me', id=msg_id, body={'addLabelIds': [LABEL_ANSWERED], 'removeLabelIds': [LABEL_PROGRESSING]}).execute()

def handle_message(service, message):
    msg_id = message['id']
    try:
        mark_as_progressing(service, msg_id)

        subject, sender, body, message_id, thread_id = get_message_details(service, msg_id)
        sender = sender.split('<')[1].split('>')[0]
        print(f"Email recieved: {msg_id} - {sender} - {subject}")

        users = json.load(open("users.json", "r", encoding="utf-8"))
        user = next((u for u in users if u["email"] == sender), None)
        if not user:
            print(f"Error: No registered user with '{sender}' found in database.")
            mark_as_not_registered(service, msg_id)
            return

        print(user)
        print("Body: " + body)

        model = user["model"]

        tokens = count_tokens(body, model)
        

        answer = ask_AI(model, body)
        if not answer:
            print(f"Error: No answer generated for message {msg_id}.")
            mark_as_broken(service, msg_id)
            return
        print("Total Tokens: " + str(answer.usage_metadata.total_token_count))

        # Send AI-generated reply
        send_reply(service, sender, subject, thread_id, message_id, answer.text, model, user["plan"], str(answer.usage_metadata.total_token_count), user["tokens"])
        mark_as_answered(service, msg_id)

    except Exception as e:
        print(f"A error happened. {msg_id}: {e}")
        mark_as_broken(service, msg_id)

def main():
    service = authenticate_gmail()
    messages = get_unread_messages(service)
    # print(service.users().labels().list(userId='me').execute()) # List all labels
    if not messages:
        print('=== no new messages ===')
    else:
        for message in messages:
            t = threading.Thread(target=handle_message, name=f'Reply+{message['id']}', args=(service, message), daemon=True)
            t.start()


if __name__ == '__main__':
    while True:
        main()
        time.sleep(1)

        print("Running threads:", end=' ')
        for thread in threading.enumerate():
            print(thread.name, end=', ')
        print()
        time.sleep(9)