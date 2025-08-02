from flask import Flask, request, jsonify, render_template
import requests
import time
import os
from datetime import datetime, timedelta
import threading
import base64
import re
import json
import sqlite3
from contextlib import contextmanager

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

# Inicializar banco de dados
def init_db():
    """Inicializa o banco de dados SQLite"""
    with sqlite3.connect('whatsapp_dispatcher.db') as conn:
        cursor = conn.cursor()
        
        # Tabela de campanhas
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS campanhas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT,
                data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_numeros INTEGER,
                total_mensagens INTEGER,
                status TEXT DEFAULT 'ativa',
                data_finalizacao TIMESTAMP
            )
        ''')
        
        # Tabela de envios
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS envios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campanha_id INTEGER,
                numero TEXT,
                tipo TEXT,
                conteudo TEXT,
                status TEXT DEFAULT 'pendente',
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tempo_resposta REAL,
                codigo_resposta INTEGER,
                erro TEXT,
                FOREIGN KEY (campanha_id) REFERENCES campanhas (id)
            )
        ''')
        
        # Tabela de métricas diárias
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS metricas_diarias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data DATE UNIQUE,
                total_envios INTEGER DEFAULT 0,
                envios_sucesso INTEGER DEFAULT 0,
                envios_erro INTEGER DEFAULT 0,
                tempo_medio REAL DEFAULT 0,
                numeros_unicos INTEGER DEFAULT 0
            )
        ''')
        
        conn.commit()

@contextmanager
def get_db():
    """Context manager para conexão com banco de dados"""
    conn = sqlite3.connect('whatsapp_dispatcher.db')
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def salvar_campanha(sequencia, numeros):
    """Salva uma nova campanha no banco de dados"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO campanhas (nome, total_numeros, total_mensagens)
            VALUES (?, ?, ?)
        ''', (
            f"Campanha_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            len(numeros),
            len(sequencia)
        ))
        return cursor.lastrowid

def salvar_envio(campanha_id, numero, tipo, conteudo, status, tempo_resposta=None, codigo_resposta=None, erro=None):
    """Salva um envio no banco de dados"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO envios (campanha_id, numero, tipo, conteudo, status, tempo_resposta, codigo_resposta, erro)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (campanha_id, numero, tipo, conteudo[:500], status, tempo_resposta, codigo_resposta, erro))
        conn.commit()

def atualizar_metricas_diarias():
    """Atualiza as métricas diárias"""
    hoje = datetime.now().date()
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Buscar dados do dia
        cursor.execute('''
            SELECT 
                COUNT(*) as total_envios,
                SUM(CASE WHEN status = 'sucesso' THEN 1 ELSE 0 END) as envios_sucesso,
                SUM(CASE WHEN status = 'erro' THEN 1 ELSE 0 END) as envios_erro,
                AVG(tempo_resposta) as tempo_medio,
                COUNT(DISTINCT numero) as numeros_unicos
            FROM envios 
            WHERE DATE(timestamp) = ?
        ''', (hoje,))
        
        dados = cursor.fetchone()
        
        # Inserir ou atualizar métricas
        cursor.execute('''
            INSERT OR REPLACE INTO metricas_diarias 
            (data, total_envios, envios_sucesso, envios_erro, tempo_medio, numeros_unicos)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            hoje,
            dados['total_envios'] or 0,
            dados['envios_sucesso'] or 0,
            dados['envios_erro'] or 0,
            dados['tempo_medio'] or 0,
            dados['numeros_unicos'] or 0
        ))
        
        conn.commit()

def is_base64(s):
    """Verifica se a string é um base64 válido"""
    try:
        if isinstance(s, str):
            if s.startswith('data:audio'):
                return True
            base64.b64decode(s, validate=True)
            return True
    except Exception:
        return False
    return False

def is_url(s):
    """Verifica se a string é uma URL válida"""
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return url_pattern.match(s) is not None

def enviar_mensagem_texto(numero, texto, campanha_id=None):
    """Envia uma mensagem de texto"""
    start_time = time.time()
    try:
        payload = {"phone": numero, "message": texto}
        response = requests.post(URL_TEXT, json=payload, headers=HEADERS)
        tempo_resposta = time.time() - start_time
        
        status = 'sucesso' if response.status_code == 200 else 'erro'
        log(f"💬 Texto para {numero}: {response.status_code}")
        
        # Salvar no banco
        if campanha_id:
            salvar_envio(
                campanha_id, numero, 'texto', texto, 
                status, tempo_resposta, response.status_code,
                response.text if response.status_code != 200 else None
            )
        
        return response.status_code == 200
    except Exception as e:
        tempo_resposta = time.time() - start_time
        log(f"❌ Erro ao enviar texto para {numero}: {str(e)}")
        
        if campanha_id:
            salvar_envio(
                campanha_id, numero, 'texto', texto, 
                'erro', tempo_resposta, None, str(e)
            )
        
        return False

def enviar_mensagem_audio(numero, audio_content, campanha_id=None):
    """Envia uma mensagem de áudio (URL ou base64)"""
    start_time = time.time()
    try:
        payload = {"phone": numero}
        
        if is_base64(audio_content):
            log(f"🎧 Enviando áudio base64 para {numero}")
            payload["audio"] = audio_content
        elif is_url(audio_content):
            log(f"🎧 Enviando áudio URL para {numero}")
            payload["audio"] = audio_content
        else:
            log(f"❌ Formato de áudio inválido para {numero}")
            if campanha_id:
                salvar_envio(
                    campanha_id, numero, 'audio', audio_content[:100], 
                    'erro', 0, None, 'Formato de áudio inválido'
                )
            return False
        
        response = requests.post(URL_AUDIO, json=payload, headers=HEADERS)
        tempo_resposta = time.time() - start_time
        
        status = 'sucesso' if response.status_code == 200 else 'erro'
        log(f"🎧 Áudio para {numero}: {response.status_code}")
        
        if response.status_code != 200:
            log(f"❌ Resposta da API: {response.text}")
        
        # Salvar no banco
        if campanha_id:
            salvar_envio(
                campanha_id, numero, 'audio', audio_content[:100], 
                status, tempo_resposta, response.status_code,
                response.text if response.status_code != 200 else None
            )
        
        return response.status_code == 200
    except Exception as e:
        tempo_resposta = time.time() - start_time
        log(f"❌ Erro ao enviar áudio para {numero}: {str(e)}")
        
        if campanha_id:
            salvar_envio(
                campanha_id, numero, 'audio', audio_content[:100], 
                'erro', tempo_resposta, None, str(e)
            )
        
        return False

def processar_sequencia_para_numero(numero, sequencia, campanha_id):
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
                sucesso = enviar_mensagem_texto(numero, conteudo, campanha_id)
            elif tipo == 'audio':
                sucesso = enviar_mensagem_audio(numero, conteudo, campanha_id)
            
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

def executar_disparo_sequencial(numeros, sequencia, campanha_id):
    """Executa o disparo sequencial para todos os números"""
    log(f"🚀 Iniciando disparo sequencial para {len(numeros)} números")
    log(f"📋 Sequência: {len(sequencia)} mensagens por número")
    
    threads = []
    
    for numero in numeros:
        thread = threading.Thread(
            target=processar_sequencia_para_numero, 
            args=(numero, sequencia, campanha_id)
        )
        threads.append(thread)
        thread.start()
        time.sleep(2)
    
    # Aguardar todas as threads terminarem
    for thread in threads:
        thread.join()
    
    # Finalizar campanha
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE campanhas 
            SET status = 'finalizada', data_finalizacao = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (campanha_id,))
        conn.commit()
    
    # Atualizar métricas
    atualizar_metricas_diarias()
    
    log("🎉 Disparo sequencial finalizado para todos os números!")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/dashboard', methods=['GET'])
def get_dashboard_data():
    """Retorna dados do dashboard"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Métricas gerais
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_envios,
                    SUM(CASE WHEN status = 'sucesso' THEN 1 ELSE 0 END) as envios_sucesso,
                    COUNT(DISTINCT numero) as numeros_unicos
                FROM envios
            ''')
            metricas_gerais = cursor.fetchone()
            
            # Campanhas ativas
            cursor.execute('SELECT COUNT(*) as ativas FROM campanhas WHERE status = "ativa"')
            campanhas_ativas = cursor.fetchone()['ativas']
            
            # Métricas de hoje
            hoje = datetime.now().date()
            cursor.execute('''
                SELECT * FROM metricas_diarias WHERE data = ?
            ''', (hoje,))
            metricas_hoje = cursor.fetchone()
            
            # Métricas da semana
            semana_atras = hoje - timedelta(days=7)
            cursor.execute('''
                SELECT SUM(total_envios) as envios_semana
                FROM metricas_diarias 
                WHERE data >= ?
            ''', (semana_atras,))
            envios_semana = cursor.fetchone()['envios_semana'] or 0
            
            # Taxa de sucesso
            taxa_sucesso = 0
            if metricas_gerais['total_envios'] > 0:
                taxa_sucesso = round((metricas_gerais['envios_sucesso'] / metricas_gerais['total_envios']) * 100, 1)
            
            # Maior campanha
            cursor.execute('''
                SELECT MAX(total_numeros * total_mensagens) as maior_campanha
                FROM campanhas
            ''')
            maior_campanha = cursor.fetchone()['maior_campanha'] or 0
            
            # Tempo médio
            cursor.execute('SELECT AVG(tempo_resposta) as tempo_medio FROM envios WHERE tempo_resposta IS NOT NULL')
            tempo_medio = cursor.fetchone()['tempo_medio'] or 0
            
            return jsonify({
                'status': 'ok',
                'data': {
                    'total_envios': metricas_gerais['total_envios'],
                    'taxa_sucesso': taxa_sucesso,
                    'campanhas_ativas': campanhas_ativas,
                    'numeros_unicos': metricas_gerais['numeros_unicos'],
                    'envios_hoje': metricas_hoje['total_envios'] if metricas_hoje else 0,
                    'envios_semana': envios_semana,
                    'tempo_medio': round(tempo_medio, 2),
                    'maior_campanha': maior_campanha
                }
            })
            
    except Exception as e:
        log(f"❌ Erro ao buscar dados do dashboard: {str(e)}")
        return jsonify({'status': 'error', 'mensagem': str(e)})

@app.route('/api/reports', methods=['GET'])
def get_reports():
    """Retorna dados de relatórios"""
    try:
        data_inicio = request.args.get('data_inicio')
        data_fim = request.args.get('data_fim')
        status_filter = request.args.get('status')
        tipo_filter = request.args.get('tipo')
        
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Construir query com filtros
            query = '''
                SELECT 
                    e.timestamp,
                    e.numero,
                    e.tipo,
                    e.status,
                    e.conteudo,
                    c.nome as campanha
                FROM envios e
                LEFT JOIN campanhas c ON e.campanha_id = c.id
                WHERE 1=1
            '''
            params = []
            
            if data_inicio:
                query += ' AND DATE(e.timestamp) >= ?'
                params.append(data_inicio)
            
            if data_fim:
                query += ' AND DATE(e.timestamp) <= ?'
                params.append(data_fim)
            
            if status_filter:
                query += ' AND e.status = ?'
                params.append(status_filter)
            
            if tipo_filter:
                query += ' AND e.tipo = ?'
                params.append(tipo_filter)
            
            query += ' ORDER BY e.timestamp DESC LIMIT 1000'
            
            cursor.execute(query, params)
            envios = cursor.fetchall()
            
            # Converter para lista de dicionários
            resultado = []
            for envio in envios:
                resultado.append({
                    'timestamp': envio['timestamp'],
                    'numero': envio['numero'],
                    'tipo': envio['tipo'],
                    'status': envio['status'],
                    'conteudo': envio['conteudo'],
                    'campanha': envio['campanha']
                })
            
            return jsonify({
                'status': 'ok',
                'data': resultado
            })
            
    except Exception as e:
        log(f"❌ Erro ao buscar relatórios: {str(e)}")
        return jsonify({'status': 'error', 'mensagem': str(e)})

@app.route('/api/export-csv', methods=['GET'])
def export_csv():
    """Exporta relatórios em CSV"""
    try:
        data_inicio = request.args.get('data_inicio')
        data_fim = request.args.get('data_fim')
        status_filter = request.args.get('status')
        tipo_filter = request.args.get('tipo')
        
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Mesma query do relatório
            query = '''
                SELECT 
                    e.timestamp,
                    e.numero,
                    e.tipo,
                    e.status,
                    e.conteudo,
                    c.nome as campanha
                FROM envios e
                LEFT JOIN campanhas c ON e.campanha_id = c.id
                WHERE 1=1
            '''
            params = []
            
            if data_inicio:
                query += ' AND DATE(e.timestamp) >= ?'
                params.append(data_inicio)
            
            if data_fim:
                query += ' AND DATE(e.timestamp) <= ?'
                params.append(data_fim)
            
            if status_filter:
                query += ' AND e.status = ?'
                params.append(status_filter)
            
            if tipo_filter:
                query += ' AND e.tipo = ?'
                params.append(tipo_filter)
            
            query += ' ORDER BY e.timestamp DESC'
            
            cursor.execute(query, params)
            envios = cursor.fetchall()
            
            # Gerar CSV
            import csv
            from io import StringIO
            
            output = StringIO()
            writer = csv.writer(output)
            
            # Cabeçalho
            writer.writerow(['Data/Hora', 'Número', 'Tipo', 'Status', 'Mensagem', 'Campanha'])
            
            # Dados
            for envio in envios:
                writer.writerow([
                    envio['timestamp'],
                    envio['numero'],
                    envio['tipo'],
                    envio['status'],
                    envio['conteudo'][:100] + '...' if len(envio['conteudo']) > 100 else envio['conteudo'],
                    envio['campanha'] or 'N/A'
                ])
            
            csv_content = output.getvalue()
            output.close()
            
            from flask import Response
            return Response(
                csv_content,
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment; filename=relatorio_whatsapp_{datetime.now().strftime("%Y%m%d")}.csv'}
            )
            
    except Exception as e:
        log(f"❌ Erro ao exportar CSV: {str(e)}")
        return jsonify({'status': 'error', 'mensagem': str(e)})

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
        
        # Salvar campanha
        campanha_id = salvar_campanha(sequencia, numeros)
        
        # Log da sequência para debug
        for msg in sequencia:
            if msg['tipo'] == 'audio':
                content_type = 'base64' if is_base64(msg['conteudo']) else 'url'
                log(f"📋 Áudio {msg['ordem']}: {content_type}")
        
        # Iniciar disparo em thread separada
        thread = threading.Thread(
            target=executar_disparo_sequencial, 
            args=(numeros, sequencia, campanha_id)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'status': 'ok', 
            'mensagem': 'Disparo sequencial iniciado com sucesso',
            'campanha_id': campanha_id,
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
    # Inicializar banco de dados
    init_db()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
