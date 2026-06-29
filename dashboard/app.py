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
- L'aggiornamento prezzi e' SOLO automatico (cron GitHub Actions): non c'e' alcun
  trigger on-demand ne' endpoint /api/trigger (bottone rimosso).
- Alternativa a massima fedeltà (stesso worker.js + asset): `npx wrangler dev`
  dalla root del progetto.
"""
import os
from flask import Flask, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
# static_folder = la cartella dashboard stessa -> /data/*.json e /images/*.webp
# vengono serviti tali e quali, come fa il binding ASSETS di Cloudflare.
app = Flask(__name__, static_folder=HERE, static_url_path="")


@app.route("/")
def index():
    return send_from_directory(HERE, "index.html")


if __name__ == "__main__":
    app.run(debug=True)
