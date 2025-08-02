from flask import Flask, request, jsonify, render_template
import requests
import time
import os
from datetime import datetime

app = Flask(__name__)

# CONFIG: variáveis de ambiente
INSTANCE = os.environ.get("INSTANCE")
TOKEN = os.environ.get("TOKEN")
SECURITY_TOKEN = os.environ.get("SECURITY_TOKEN")

URL_TEXT = f"https://api.z-api.io/instances/{INSTANCE}/token/{TOKEN}/send-text"
URL_AUDIO = f"https://api.z-api.io/instances/{INSTANCE}/token/{TOKEN}/send-audio"

HEADERS = {
    'client-token': SECURITY_TOKEN,
    'Content-Type': 'application/json'
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/enviar', methods=['POST'])
def enviar():
    data = request.json
    tipo = data['tipo']
    textos = data['textos']
    audios = data['audios']
    numeros = data['numeros']
    intervalo = int(data['intervalo'])

    for numero in numeros:
        if tipo in ['texto', 'ambos']:
            for texto in textos:
                payload = {"phone": numero, "message": texto}
                r = requests.post(URL_TEXT, json=payload, headers=HEADERS)
                log(f"💬 Texto para {numero}: {r.status_code}")
                time.sleep(intervalo)
        if tipo in ['audio', 'ambos']:
            for audio in audios:
                payload = {"phone": numero, "audio": audio}
                r = requests.post(URL_AUDIO, json=payload, headers=HEADERS)
                log(f"🎧 Áudio para {numero}: {r.status_code}")
                time.sleep(intervalo)

    return jsonify({'status': 'ok', 'mensagem': 'Mensagens enviadas com sucesso.'})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
