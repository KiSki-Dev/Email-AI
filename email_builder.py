import markdown

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

    body = (f"""\
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

    return body