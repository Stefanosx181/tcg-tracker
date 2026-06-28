"""
app.py - Anteprima LOCALE della dashboard, senza dover pushare su Cloudflare.

Serve ESATTAMENTE gli stessi file statici che Cloudflare pubblica
(dashboard/index.html + data/ + images/), così l'anteprima in locale è
IDENTICA al sito. Cloudflare resta la fonte di verità per la UI: qui non c'è
un secondo template, si serve la stessa griglia di `index.html`.

Avvio:
  pip install flask
  python app.py
  -> apri http://127.0.0.1:5000

Note:
- Il vero POST /api/trigger ("Aggiorna ora") esiste solo sul Worker Cloudflare
  (worker.js, secret GH_TOKEN). In locale qui risponde con un messaggio esplicito.
- Alternativa a massima fedeltà (stesso worker.js + asset): `npx wrangler dev`
  dalla root del progetto.
"""
import os
from flask import Flask, jsonify, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
# static_folder = la cartella dashboard stessa -> /data/*.json e /images/*.webp
# vengono serviti tali e quali, come fa il binding ASSETS di Cloudflare.
app = Flask(__name__, static_folder=HERE, static_url_path="")


@app.route("/")
def index():
    return send_from_directory(HERE, "index.html")


@app.route("/api/trigger", methods=["POST"])
def trigger():
    # Lo scraping si avvia solo dal Worker Cloudflare; in locale è un no-op chiaro.
    return jsonify(ok=False,
                   error="Disponibile solo sul sito pubblicato (Cloudflare)."), 501


if __name__ == "__main__":
    app.run(debug=True)
