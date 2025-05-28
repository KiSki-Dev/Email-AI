import markdown
import ftfy
import codecs

md_text = '''Hallo! Gerne erkläre ich dir kurz, was Tokens bei KI-Modellen (insbesondere bei Sprachmodellen) sind:\n\n**Was sind Tokens?**\n\n*   **Grundbausteine:** Tokens sind die kleinsten Einheiten, in die ein KI-Modell Text zerlegt, bevor es ihn verarbeitet. Du kannst sie dir als die "Wörter" oder "Wortteile" vorstellen, die das Modell versteht und mit denen es arbeitet.\n\n*   **Keine reinen Wörter:** Ein Token muss nicht unbedingt ein ganzes Wort sein. Es kann auch ein Teil eines Wortes, ein Satzzeichen oder ein Leerzeichen sein.\n\n*   **Beispiele:**\n    *   Der Satz: "Hallo, wie geht es dir?" könnte in folgende Tokens zerlegt werden: `["Hallo", ",", " wie", " geht", " es", " dir", "?"]`\n    *   Das Wort "unverständlich" könnte in Tokens wie `["un", "ver", "ständ", "lich"]` zerlegt werden.\n\n**Wie funktionieren Tokens bei KI-Modellen?**\n\n1.  **Tokenisierung:** Der erste Schritt ist die **Tokenisierung**. Dabei wird der Eingabetext (z.B. deine Frage) in eine Sequenz von Tokens zerlegt. Dieser Prozess wird von einem speziellen Programm, dem **Tokenizer**, durchgeführt.\n\n2.  **Numerische Darstellung:** Jedes Token wird dann einer eindeutigen **Zahl** zugeordnet. Das KI-Modell arbeitet intern mit diesen Zahlen, nicht mit den Text-Tokens selbst.  Eine Tabelle (Vokabular), die jedes Token mit einer Zahl verknüpft, ist die Grundlage dafür.\n\n3.  **Verarbeitung:** Das KI-Modell verarbeitet diese Zahlenfolge, um den Kontext zu verstehen und eine Antwort zu generieren.\n\n4.  **Generierung:** Bei der Generierung von Text wandelt das Modell ebenfalls Zahlen in Tokens um. Diese Tokens werden dann wieder zu lesbarem Text zusammengesetzt.\n\n**Warum werden Tokens verwendet?**\n\n*   **Effizienz:** Die Verarbeitung von Zahlen ist für Computer effizienter als die Verarbeitung von Text.\n*   **Vokabularbegrenzung:** KI-Modelle haben ein begrenztes Vokabular (die Menge der Tokens, die sie kennen). Durch die Zerlegung in Tokens kann ein Modell auch mit Wörtern umgehen, die nicht direkt in seinem Vokabular enthalten sind.\n*   **Bessere Kontextanalyse:** Die Tokenisierung hilft dem Modell, den Kontext von Wörtern besser zu verstehen. Z. B. kann es "Bank" als "Sitzgelegenheit" oder "Finanzinstitut" erkennen, je nachdem, welche Tokens drumherum stehen.\n\n**Zusammenfassend:** Tokens sind die kleinen Einheiten, in die Text zerlegt wird, damit KI-Modelle ihn verstehen und verarbeiten können. Sie sind wichtig für die Effizienz, die Kontextanalyse und die Fähigkeit der Modelle, mit unbekannten Wörtern umzugehen.\n\nIch hoffe, das hilft dir weiter! Lass es mich wissen, wenn du noch Fragen hast.\n'''

def markdown_to_html(md_text: str) -> str:
    """Wandelt Markdown in HTML um."""
    fixed = ftfy.fix_text(md_text)
    return ftfy.fix_text(markdown.markdown(fixed, extensions=['extra', 'sane_lists']))

def build_html_email(
    banner_top_url: str,
    title: str,
    modell: str,
    plan: str,
    cost: str,
    left_token: str,
    body_md: str,
    message_id: str,
    links: dict,
    banner_bottom_url: str
) -> str:
    body_html = markdown_to_html(body_md)
    links_html = ' '.join(
        f'<a href="{url}" style="margin:0 10px; text-decoration:none; color:#8ED1FC; font-weight:bold;">{text}</a>'
        for text, url in links.items()
    )

    return ftfy.fix_text(f"""\
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <style>
    body {{ margin:0; padding:0; background-color:#1E1E1E; color:#D4D4D4; font-family:'Segoe UI', Tahoma, sans-serif; }}
    a {{ color:#8ED1FC; }}
    .banner {{ text-align:center; padding:20px 0; }}
    .banner img {{ max-width:600px; width:90%; height:auto; border-radius:8px; }}
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
    <img src="{banner_top_url}" alt="Banner oben">
  </div>

  <!-- Titel -->
  <h1>{title}</h1>

  <!-- Nutzer-Infos -->
  <div class="info-row">
    <span><strong>Modell:</strong> {modell}</span>
    <span><strong>Plan:</strong> {plan}</span>
  </div>

  <!-- Token-Infos -->
  <div class="info-row" style="margin-bottom:30px;">
    <span><strong>Token-Kosten:</strong> {cost}</span>
    <span><strong>Übrige Token:</strong> {left_token}</span>
  </div>

  <!-- Markdown-Body -->
  <div class="body-container">
    {body_html}
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
    <img src="{banner_bottom_url}" alt="Banner unten">
  </div>

</body>
</html>
""")

def send_markdown_reply(
    banner_top_url: str,
    title: str,
    modell: str,
    plan: str,
    cost: str,
    left_token: str,
    body_md: str,
    message_id: str,
    links: dict,
    banner_bottom_url: str,
):
    """Erzeugt und schreibt die HTML-Datei mit UTF-8-Encoding."""
    html = build_html_email(
        banner_top_url, title, modell, plan,
        cost, left_token, body_md,
        message_id, links, banner_bottom_url
    )
    with codecs.open("test.html", "w", "utf-8-sig") as f:
        f.write(html)
    print("HTML-Datei 'test.html' erzeugt.")

# Beispielaufruf:
links = {
    "Webseite": "https://example.com",
    "Dashboard": "https://example.com/dashboard",
    "Discord": "https://discord.gg/example"
}

send_markdown_reply(
    banner_top_url="https://via.placeholder.com/600x100/333333/8ED1FC?text=Top+Banner",
    title="Dein persönlicher Bericht",
    modell="GPT-4 Turbo",
    plan="Pro",
    cost="1234",
    left_token="4321",
    body_md=md_text,
    message_id="1234567890abcdef",
    links=links,
    banner_bottom_url="https://via.placeholder.com/600x50/333333/8ED1FC?text=Bottom+Banner"
)
