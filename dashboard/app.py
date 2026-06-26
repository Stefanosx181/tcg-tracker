"""
app.py - Schermata dedicata (web) servita dal database.
Mostra la vista v_buylist con la stessa struttura del foglio 'BuyList Pokemon'.

Avvio:
  pip install flask
  python app.py
  -> apri http://127.0.0.1:5000
"""
import os
import sqlite3
from flask import Flask, jsonify, render_template

HERE = os.path.dirname(__file__)
DB = os.path.join(HERE, "..", "tcg_tracker.db")
app = Flask(__name__)


def query_buylist():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT * FROM v_buylist")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/buylist")
def api_buylist():
    return jsonify(query_buylist())


if __name__ == "__main__":
    app.run(debug=True)
