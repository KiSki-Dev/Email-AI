import base64
import re
import threading #* Needed for gmail_lock
from locker import gmail_lock

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


def extract_details_from_subject(subject, default_model, models):
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