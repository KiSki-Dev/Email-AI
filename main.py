import os.path
import threading
import time
import json
import os
import sys
from dotenv import load_dotenv

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from google import genai

import pymongo

# Local imports
import extracter
import sender
from locker import gmail_lock
import crypto_utils

load_dotenv()

ACTIVE_THREADS = set()

LABELS = {
    "broken": {
        "add": ["Label_55889426924201303"],
        "remove": ["Label_5310290292504501863", "UNREAD"]
    },
    "unregistered": {
        "add": ["Label_6688557498746066945"],
        "remove": ["Label_5310290292504501863"]
    },
    "progressing": {
        "add": ["Label_5310290292504501863"],
        "remove": ['UNREAD']
    },
    "answered": {
        "add": ["Label_1030359169377715795"],
        "remove": ["Label_5310290292504501863"]
    }
}

no_messages_count = 0

DEFAULT_MODEL = "gemini-2.0-flash"
DEFAULT_BACKUP_MODEL = "gemini-1.5-flash" #* When default model is not available

client = genai.Client(api_key=os.getenv('gemini_API_key'))
aesgcm = crypto_utils.load_aes_key()

def authenticate_gmail():
    scopes = ['https://www.googleapis.com/auth/gmail.modify']
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', scopes)

    #! When no Local Credentials are available, we need to re-authenticate
    if not creds or not creds.valid:
        try:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', scopes)
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
    uri = f"mongodb://emailAI_convo:{os.getenv('convoDBPass')}@localhost:27017/?authSource=convoDB"
    client = pymongo.MongoClient(uri)
    try:
        client.server_info() #* Check if the connection is successful
    except Exception as e:
        sys.exit(f"Error connecting to MongoDB: {e}")

    print("Connected to MongoDB successfully.")
    return client["convoDB"]["conversations"]

def get_unread_messages(service):
    with gmail_lock:
        results = service.users().messages().list(userId='me', labelIds=['INBOX', 'UNREAD'], maxResults=5).execute()
    messages = results.get('messages', [])
    return messages

#? Useless? Unsure? Just keep it for now
def count_tokens(content, model): 
    total_tokens = client.models.count_tokens(model=model, contents=content)
    return total_tokens

def mark_label(service, msg_id, label):
    with gmail_lock:
        service.users().messages().modify(userId='me', id=msg_id, body={'addLabelIds': label["add"], 'removeLabelIds': label["remove"]}).execute()

def handle_message(service, db, message):
    thread_start_time = time.perf_counter()
    msg_id = message['id']
    try:
        mark_label(service, msg_id, LABELS["progressing"])

        subject, to, body, message_id, thread_id, attachments = extracter.get_message_details(service, msg_id)
        to = to.split('<')[1].split('>')[0]

        #ToDo Implement User Database
        users = json.load(open("users.json", "r", encoding="utf-8"))
        user = next((u for u in users if u["email"] == to), None)
        if not user:
            default_model = DEFAULT_MODEL
        else:
            default_model = user["model"]
        
        with open('models.json') as f:
            models = json.load(f)

        model, use_reasoning = extracter.extract_details_from_subject(to, default_model, models)

        if models[model]["active"] == False:
            print(f"Model '{model}' is deactivated.")
            return
        if models[model]["perm_level_required"] != 0:
            if not user:
                print(f"Error: User '{to}' is not registered and cant use this Model.")
                mark_label(service, msg_id, LABELS["unregistered"])
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
                mark_label(service, msg_id, LABELS["broken"])
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
        answer = sender.ask_AI(client, model, body, attachments, db, thread_id, user["user_id"] if user else 0)
        if answer == "OVERLOADED":
            print(f"Model '{model}' is currently overloaded. Asking again using backup Model.")
            model = DEFAULT_BACKUP_MODEL
            answer = sender.ask_AI(client, model, body, attachments, db, thread_id, user["user_id"] if user else 0)

        if not answer:
            print(f"Error: No answer generated for message {msg_id}.")
            mark_label(service, msg_id, LABELS["broken"])
            return
        print(f"Costed {str(answer.usage_metadata.total_token_count)} Tokens using '{model}' model.")
        ai_end_time = time.perf_counter()
        print(f"AI processing took {ai_end_time - ai_start_time:.2f} seconds.")

        #* Send AI-generated reply
        sender.send_reply(service, to, subject, thread_id, message_id, answer.text, model, plan, str(answer.usage_metadata.total_token_count), tokens)
        mark_label(service, msg_id, LABELS["answered"])

    except Exception as e:
        print(f"A error appeared inside handle_message(). {e}")
        mark_label(service, msg_id, LABELS["answered"])

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
            if message['threadId'] in ACTIVE_THREADS: #* Prevent multiple Answers from one email thread
                print(f"Thread {message['threadId']} is already being processed. Skipping.")
                mark_label(service, message['id'], LABELS["broken"])

            else:
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

        #print(service.users().labels().list(userId='me').execute()) #! List all existing labels; Use for finding label IDs

        while True:
            try:
                main(service, db)
            except Exception as e:
                print(f"[{time.ctime()}] Fehler in main(): {e}", file=sys.stderr)
            time.sleep(10)
                
    except KeyboardInterrupt:
        print(f"\n{"="*70}\nProgram terminated by user.")