from flask import Flask, request, jsonify, render_template
import requests
import time
import os
from datetime import datetime
import threading

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

def enviar_mensagem_texto(numero, texto):
    """Envia uma mensagem de texto"""
    try:
        payload = {"phone": numero, "message": texto}
        response = requests.post(URL_TEXT, json=payload, headers=HEADERS)
        log(f"💬 Texto para {numero}: {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        log(f"❌ Erro ao enviar texto para {numero}: {str(e)}")
        return False

def enviar_mensagem_audio(numero, audio_url):
    """Envia uma mensagem de áudio"""
    try:
        payload = {"phone": numero, "audio": audio_url}
        response = requests.post(URL_AUDIO, json=payload, headers=HEADERS)
        log(f"🎧 Áudio para {numero}: {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        log(f"❌ Erro ao enviar áudio para {numero}: {str(e)}")
        return False

def processar_sequencia_para_numero(numero, sequencia):
    """Processa toda a sequência de mensagens para um número específico"""
    log(f"🎯 Iniciando sequência para {numero}")
    
    for i, mensagem in enumerate(sequencia):
        try:
            tipo = mensagem['tipo']
            conteudo = mensagem['conteudo']
            intervalo = mensagem['intervalo']
            ordem = mensagem['ordem']
            
            log(f"📤 Enviando mensagem {ordem}/{len(sequencia)} para {numero}")
            
            # Enviar mensagem baseada no tipo
            sucesso = False
            if tipo == 'texto':
                sucesso = enviar_mensagem_texto(numero, conteudo)
            elif tipo == 'audio':
                sucesso = enviar_mensagem_audio(numero, conteudo)
            
            if sucesso:
                log(f"✅ Mensagem {ordem} enviada com sucesso para {numero}")
            else:
                log(f"❌ Falha ao enviar mensagem {ordem} para {numero}")
            
            # Aguardar intervalo antes da próxima mensagem (exceto na última)
            if i < len(sequencia) - 1:
                log(f"⏳ Aguardando {intervalo}s antes da próxima mensagem...")
                time.sleep(intervalo)
                
        except Exception as e:
            log(f"❌ Erro ao processar mensagem {ordem} para {numero}: {str(e)}")
    
    log(f"🏁 Sequência finalizada para {numero}")

def executar_disparo_sequencial(numeros, sequencia):
    """Executa o disparo sequencial para todos os números"""
    log(f"🚀 Iniciando disparo sequencial para {len(numeros)} números")
    log(f"📋 Sequência: {len(sequencia)} mensagens por número")
    
    threads = []
    
    for numero in numeros:
        # Criar uma thread para cada número para processamento paralelo
        thread = threading.Thread(
            target=processar_sequencia_para_numero, 
            args=(numero, sequencia)
        )
        threads.append(thread)
        thread.start()
        
        # Pequeno delay entre iniciar threads para evitar sobrecarga
        time.sleep(2)
    
    # Aguardar todas as threads terminarem
    for thread in threads:
        thread.join()
    
    log("🎉 Disparo sequencial finalizado para todos os números!")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/enviar-sequencia', methods=['POST'])
def enviar_sequencia():
    try:
        data = request.json
        sequencia = data.get('sequencia', [])
        numeros = data.get('numeros', [])
        
        # Validações
        if not sequencia:
            return jsonify({
                'status': 'error', 
                'mensagem': 'Nenhuma mensagem na sequência'
            })
        
        if not numeros:
            return jsonify({
                'status': 'error', 
                'mensagem': 'Nenhum número fornecido'
            })
        
        # Validar se as variáveis de ambiente estão configuradas
        if not all([INSTANCE, TOKEN, SECURITY_TOKEN]):
            return jsonify({
                'status': 'error', 
                'mensagem': 'Configurações da API não encontradas'
            })
        
        # Iniciar disparo em thread separada para não bloquear a resposta
        thread = threading.Thread(
            target=executar_disparo_sequencial, 
            args=(numeros, sequencia)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'status': 'ok', 
            'mensagem': 'Disparo sequencial iniciado com sucesso',
            'detalhes': {
                'numeros': len(numeros),
                'mensagens_por_numero': len(sequencia),
                'total_envios': len(numeros) * len(sequencia)
            }
        })
        
    except Exception as e:
        log(f"❌ Erro no endpoint /enviar-sequencia: {str(e)}")
        return jsonify({
            'status': 'error', 
            'mensagem': f'Erro interno: {str(e)}'
        })

# Manter o endpoint antigo para compatibilidade
@app.route('/enviar', methods=['POST'])
def enviar():
    try:
        data = request.json
        tipo = data['tipo']
        textos = data['textos']
        audios = data['audios']
        numeros = data['numeros']
        intervalo = int(data['intervalo'])
        
        def processar_envio_legado():
            for numero in numeros:
                if tipo in ['texto', 'ambos']:
                    for texto in textos:
                        enviar_mensagem_texto(numero, texto)
                        time.sleep(intervalo)
                
                if tipo in ['audio', 'ambos']:
                    for audio in audios:
                        enviar_mensagem_audio(numero, audio)
                        time.sleep(intervalo)
        
        thread = threading.Thread(target=processar_envio_legado)
        thread.daemon = True
        thread.start()
        
        return jsonify({'status': 'ok', 'mensagem': 'Mensagens enviadas com sucesso.'})
        
    except Exception as e:
        return jsonify({'status': 'error', 'mensagem': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
