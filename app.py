import os
import hashlib
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_from_directory, g
from werkzeug.utils import secure_filename
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func, distinct, or_
from models import get_engine, User, Client, SellOutRow, SellInRow, SubscriptionPayment, UploadHistory, init_db
from data_parser import parse_excel_and_import

app = Flask(__name__)
app.secret_key = "lpl_repon_analytics_super_secret_key"

# Inicializar Banco de dados apenas no primeiro request para evitar travar o carregamento do módulo serverless na Vercel
@app.before_request
def initialize_database():
    # Remove o gancho para não rodar a cada requisição
    app.before_request_funcs[None].remove(initialize_database)
    try:
        init_db()
    except Exception as e:
        print("Erro ao inicializar banco de dados:", str(e))

# Pasta de upload compatível com caminhos relativos em ambientes serverless (Vercel)
if os.environ.get('VERCEL') == '1':
    UPLOAD_FOLDER = "/tmp"
else:
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Helper para obter sessão do banco de dados por requisição (compartilhada e auto-fechada no final da request)
def get_db():
    if 'db' not in g:
        engine = get_engine()
        Session = sessionmaker(bind=engine)
        g.db = Session()
    return g.db

@app.teardown_appcontext
def teardown_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# Injetor de Tema no Contexto das Páginas
@app.context_processor
def inject_theme():
    if 'user_id' in session:
        db = get_db()
        user = db.query(User).filter_by(id=session['user_id']).first()
        theme_data = {}
        if user:
            theme_data['username'] = user.username
            theme_data['email'] = user.email
            theme_data['is_admin'] = user.permission == "ADMINISTRADOR" or user.is_system_admin
            theme_data['enabled_services'] = []
            
            if user.is_system_admin:
                theme_data['enabled_services'] = ["Sell Out", "Sell In", "OL", "Campanhas"]
                theme_data['logo'] = "/static/uploads/repon_logo.jpg"
                theme_data['primary_color'] = "#6366f1"
                theme_data['secondary_color'] = "#f97316"
                theme_data['client_name'] = "Administração LPL"
            elif user.client:
                theme_data['enabled_services'] = [s.strip() for s in user.client.enabled_services.split(",") if s.strip()]
                theme_data['logo'] = user.client.logo_path or "/static/uploads/repon_logo.jpg"
                theme_data['primary_color'] = user.client.primary_color or "#6366f1"
                theme_data['secondary_color'] = user.client.secondary_color or "#f97316"
                theme_data['client_name'] = user.client.name
                theme_data['client_slug'] = user.client.slug
                
        db.close()
        return dict(theme=theme_data)
    return dict(theme={})

# Middleware de Autenticação
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        db = get_db()
        user = db.query(User).filter_by(id=session['user_id']).first()
        is_adm = user and (user.is_system_admin or user.permission == "ADMINISTRADOR")
        db.close()
        if not is_adm:
            flash("Acesso restrito a administradores.", "error")
            return redirect(url_for('dashboard_home'))
        return f(*args, **kwargs)
    return decorated_function


# ---- ROTAS DE AUTENTICAÇÃO ----

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard_home'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username_or_email = request.form.get('username')
        password = request.form.get('password')
        
        db = get_db()
        # Verificar admin global ou usuário do cliente
        user = db.query(User).filter(
            or_(User.username == username_or_email, User.email == username_or_email)
        ).first()
        
        if user:
            hashed = hashlib.sha256(password.encode()).hexdigest()
            if user.password_hash == hashed:
                if user.status == "Inativo":
                    flash("Sua conta está inativa. Entre em contato com o suporte.", "error")
                    db.close()
                    return render_template('login.html')
                
                session['user_id'] = user.id
                session['username'] = user.username
                session['is_admin'] = user.is_system_admin or user.permission == "ADMINISTRADOR"
                session['client_id'] = user.client_id
                
                db.close()
                if user.is_system_admin:
                    return redirect(url_for('admin_dashboard'))
                return redirect(url_for('hall_page'))
                
        flash("Usuário ou senha incorretos.", "error")
        db.close()
        
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/hall')
@login_required
def hall_page():
    db = get_db()
    user = db.query(User).filter_by(id=session['user_id']).first()
    if user.is_system_admin:
        db.close()
        return redirect(url_for('admin_dashboard'))
    
    # Carregar serviços habilitados
    services = [s.strip() for s in user.client.enabled_services.split(",") if s.strip()]
    db.close()
    return render_template('hall.html', enabled_services=services)

# ---- ROTAS DO DASHBOARD DO USUÁRIO ----

@app.route('/dashboard')
@login_required
def dashboard_home():
    db = get_db()
    user = db.query(User).filter_by(id=session['user_id']).first()
    
    if user.is_system_admin:
        db.close()
        return redirect(url_for('admin_dashboard'))
        
    # Carregar serviços habilitados
    services = [s.strip() for s in user.client.enabled_services.split(",") if s.strip()]
    db.close()
    
    # Redirecionar para o primeiro serviço disponível
    if "Sell Out" in services:
        return redirect(url_for('dashboard_page', service="sell_out"))
    elif "Sell In" in services:
        return redirect(url_for('dashboard_page', service="sell_in"))
    else:
        return render_template('no_services.html')

@app.route('/dashboard/<service>')
@login_required
def dashboard_page(service):
    if service not in ["sell_out", "sell_in"]:
        return redirect(url_for('dashboard_home'))
        
    db = get_db()
    user = db.query(User).filter_by(id=session['user_id']).first()
    enabled = [s.strip().lower().replace(" ", "_") for s in user.client.enabled_services.split(",")]
    
    if service not in enabled:
        flash("Este serviço não está ativado para o seu perfil.", "error")
        db.close()
        return redirect(url_for('dashboard_home'))
        
    db.close()
    return render_template('dashboard.html', service=service)


# ---- ENDPOINT DE KEEP-ALIVE PARA CRON JOBS ----
@app.route('/api/cron-ping')
def cron_ping():
    db = get_db()
    try:
        db.execute("SELECT 1")
        db.close()
        return jsonify({"status": "success", "message": "Database pinged successfully"}), 200
    except Exception as e:
        try:
            db.close()
        except:
            pass
        return jsonify({"status": "error", "message": str(e)}), 500


# ---- ENDPOINTS DE API DO DASHBOARD (COM ISOLAMENTO DE CLIENTE) ----

@app.route('/api/filters/<service>')
@login_required
def api_filters(service):
    client_id = session.get('client_id')
    if not client_id:
        return jsonify({"error": "Admin global não possui dados de cliente associados."}), 400
        
    db = get_db()
    Model = SellOutRow if service == "sell_out" else SellInRow
    
    # Obter filtros distintos baseados estritamente no client_id
    query = db.query(Model).filter_by(client_id=client_id)
    
    filters = {
        "industrias": [r[0] for r in query.with_entities(distinct(Model.industria)).all() if r[0]],
        "distribuidores": [r[0] for r in query.with_entities(distinct(Model.distribuidor)).all() if r[0]],
        "supervisores": [r[0] for r in query.with_entities(distinct(Model.supervisor)).all() if r[0]],
        "vendedores": [r[0] for r in query.with_entities(distinct(Model.vendedor)).all() if r[0]],
        "clientes": [r[0] for r in query.with_entities(distinct(Model.cliente)).all() if r[0]],
        "ufs": [r[0] for r in query.with_entities(distinct(Model.uf)).all() if r[0]],
        "anos": [r[0] for r in query.with_entities(distinct(Model.ano)).all() if r[0]],
        "meses": [r[0] for r in query.with_entities(distinct(Model.mes)).all() if r[0]],
        "produtos": [r[0] for r in query.with_entities(distinct(Model.material_desc)).all() if r[0]]
    }
    
    db.close()
    return jsonify(filters)

@app.route('/api/data/<service>', methods=['POST'])
@login_required
def api_data(service):
    client_id = session.get('client_id')
    if not client_id:
        return jsonify({"error": "Sem dados de cliente."}), 400
        
    filters = request.json or {}
    db = get_db()
    Model = SellOutRow if service == "sell_out" else SellInRow
    
    # Função auxiliar para aplicar os filtros comuns
    def apply_filters(q):
        if filters.get('industria') and filters['industria'] != 'Todas':
            q = q.filter(Model.industria == filters['industria'])
        if filters.get('distribuidor') and filters['distribuidor'] != 'Todos':
            q = q.filter(Model.distribuidor == filters['distribuidor'])
        if filters.get('supervisor') and filters['supervisor'] != 'Todos':
            q = q.filter(Model.supervisor == filters['supervisor'])
        if filters.get('vendedor') and filters['vendedor'] != 'Todos':
            q = q.filter(Model.vendedor == filters['vendedor'])
        if filters.get('cliente') and filters['cliente'] != 'Todos':
            q = q.filter(Model.cliente == filters['cliente'])
        if filters.get('uf') and filters['uf'] != 'Todas':
            q = q.filter(Model.uf == filters['uf'])
        if filters.get('ano') and filters['ano'] != 'Todos':
            q = q.filter(Model.ano == int(filters['ano']))
        if filters.get('mes') and filters['mes'] != 'Todos':
            q = q.filter(Model.mes == filters['mes'])
        if filters.get('produto') and filters['produto'] != 'Todos':
            q = q.filter(Model.material_desc == filters['produto'])
        return q

    # 1. KPIs Gerais
    kpis_query = db.query(
        func.sum(Model.valor_fat).label('total_fat'),
        func.sum(Model.unid_faturada).label('total_unidades'),
        func.count(distinct(Model.cnpj)).label('total_cnpjs'),
        func.count(distinct(Model.ean)).label('total_skus')
    ).filter(Model.client_id == client_id)
    kpis_query = apply_filters(kpis_query)
    total_fat, total_unidades, cnpjs_positivados, total_skus_distinct = kpis_query.first()
    
    total_fat = total_fat or 0.0
    total_unidades = total_unidades or 0.0
    cnpjs_positivados = cnpjs_positivados or 0
    total_skus_distinct = total_skus_distinct or 0
    ticket_medio = total_fat / cnpjs_positivados if cnpjs_positivados > 0 else 0.0

    # 2. Histórico de Faturamento por Mês
    monthly_query = db.query(
        Model.mes,
        func.sum(Model.valor_fat).label('fat'),
        func.sum(Model.unid_faturada).label('unid'),
        func.count(distinct(Model.cnpj)).label('cnpjs')
    ).filter(Model.client_id == client_id)
    monthly_query = apply_filters(monthly_query).group_by(Model.mes)
    monthly_rows = monthly_query.all()
    
    months_ordered = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    month_fat = {m: 0.0 for m in months_ordered}
    month_unid = {m: 0.0 for m in months_ordered}
    month_cnpjs = {m: 0 for m in months_ordered}
    
    m_map = {
        "jan": "Janeiro", "fev": "Fevereiro", "mar": "Março", "abr": "Abril", "mai": "Maio", "jun": "Junho",
        "jul": "Julho", "ago": "Agosto", "set": "Setembro", "out": "Outubro", "nov": "Novembro", "dez": "Dezembro",
        "janeiro": "Janeiro", "fevereiro": "Fevereiro", "março": "Março", "abril": "Abril", "maio": "Maio",
        "junho": "Junho", "julho": "Julho", "agosto": "Agosto", "setembro": "Setembro", "outubro": "Outubro",
        "novembro": "Novembro", "dezembro": "Dezembro"
    }
    
    for r in monthly_rows:
        if r[0]:
            m_key = str(r[0]).strip().lower()
            mapped_m = m_map.get(m_key)
            if mapped_m:
                month_fat[mapped_m] = r[1] or 0.0
                month_unid[mapped_m] = r[2] or 0.0
                month_cnpjs[mapped_m] = r[3] or 0
                
    chart_months = [m for m in months_ordered if month_fat[m] > 0]
    chart_month_values = [month_fat[m] for m in chart_months]
    chart_month_units = [month_unid[m] for m in chart_months]
    chart_month_cnpjs = [month_cnpjs[m] for m in chart_months]
    chart_month_tickets = [month_fat[m] / month_unid[m] if month_unid[m] > 0 else 0.0 for m in chart_months]

    # 3. Ranking de Clientes
    client_query = db.query(
        Model.cnpj,
        Model.razao_social,
        Model.uf,
        func.sum(Model.valor_fat).label('fat'),
        func.sum(Model.unid_faturada).label('unid'),
        func.count(distinct(Model.ean)).label('mix'),
        func.count(distinct(Model.mes)).label('frequencia')
    ).filter(Model.client_id == client_id)
    client_query = apply_filters(client_query).group_by(Model.cnpj, Model.razao_social, Model.uf).order_by(func.sum(Model.valor_fat).desc())
    client_rows = client_query.all()
    
    top_clients_labels = [r[1] or "Desconhecido" for r in client_rows[:10]]
    top_clients_values = [r[3] or 0.0 for r in client_rows[:10]]
    
    detailed_clients = []
    for i, r in enumerate(client_rows):
        fat_val = r[3] or 0.0
        unid_val = r[4] or 0.0
        detailed_clients.append({
            "rank": i + 1,
            "cnpj": r[0] or "Sem CNPJ",
            "razao_social": r[1] or "Desconhecido",
            "uf": r[2] or "--",
            "faturamento": f"R$ {fat_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "unidades": int(unid_val),
            "mix": r[5] or 0,
            "frequencia": r[6] or 0,
            "ticket_medio": f"R$ {fat_val/unid_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if unid_val > 0 else "R$ 0,00",
            "share": f"{(fat_val / total_fat * 100):.2f}%" if total_fat > 0 else "0.00%"
        })
    fat_top50 = sum(r[3] or 0.0 for r in client_rows[:50])

    # 4. Ranking de Produtos
    product_query = db.query(
        Model.ean,
        Model.material_desc,
        Model.industria,
        func.sum(Model.valor_fat).label('fat'),
        func.sum(Model.unid_faturada).label('unid'),
        func.count(distinct(Model.cnpj)).label('cnpjs')
    ).filter(Model.client_id == client_id)
    product_query = apply_filters(product_query).group_by(Model.ean, Model.material_desc, Model.industria).order_by(func.sum(Model.valor_fat).desc())
    product_rows = product_query.all()
    
    top_products_labels = [r[1] or "Sem Descrição" for r in product_rows[:10]]
    top_products_values = [r[3] or 0.0 for r in product_rows[:10]]
    
    detailed_products = []
    for i, r in enumerate(product_rows):
        fat_val = r[3] or 0.0
        unid_val = r[4] or 0.0
        detailed_products.append({
            "rank": i + 1,
            "ean": r[0] or "Sem EAN",
            "material_desc": r[1] or "Sem Descrição",
            "industria": r[2] or "--",
            "faturamento": f"R$ {fat_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "unidades": int(unid_val),
            "cnpjs": r[5] or 0,
            "ticket_medio": f"R$ {fat_val/unid_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if unid_val > 0 else "R$ 0,00",
            "share": f"{(fat_val / total_fat * 100):.2f}%" if total_fat > 0 else "0.00%"
        })
    fat_top20_skus = sum(r[3] or 0.0 for r in product_rows[:20])

    # 5. Distribuidores
    distrib_query = db.query(
        Model.distribuidor,
        func.sum(Model.valor_fat).label('fat'),
        func.count(distinct(Model.cnpj)).label('cnpjs')
    ).filter(Model.client_id == client_id)
    distrib_query = apply_filters(distrib_query).group_by(Model.distribuidor).order_by(func.sum(Model.valor_fat).desc())
    distrib_rows = distrib_query.all()
    
    distrib_list = []
    for r in distrib_rows:
        fat_val = r[1] or 0.0
        distrib_list.append({
            "distribuidor": r[0] or "Outros",
            "faturamento": fat_val,
            "faturamento_str": f"R$ {fat_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "cnpjs": r[2] or 0,
            "share": f"{(fat_val / total_fat * 100):.2f}%" if total_fat > 0 else "0.00%"
        })

    # 6. Supervisores
    supervisor_query = db.query(
        Model.supervisor,
        Model.distribuidor,
        func.sum(Model.valor_fat).label('fat'),
        func.sum(Model.unid_faturada).label('unid'),
        func.count(distinct(Model.cnpj)).label('cnpjs'),
        func.count(distinct(Model.ean)).label('skus')
    ).filter(Model.client_id == client_id)
    supervisor_query = apply_filters(supervisor_query).group_by(Model.supervisor, Model.distribuidor).order_by(func.sum(Model.valor_fat).desc())
    supervisor_rows = supervisor_query.all()
    
    detailed_supervisors = []
    for i, r in enumerate(supervisor_rows):
        fat_val = r[2] or 0.0
        unid_val = r[3] or 0.0
        detailed_supervisors.append({
            "rank": i + 1,
            "supervisor": r[0] or "Sem Supervisor",
            "distribuidor": r[1] or "--",
            "faturamento": f"R$ {fat_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "unidades": int(unid_val),
            "ticket_medio": f"R$ {fat_val/unid_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if unid_val > 0 else "R$ 0,00",
            "cnpjs": r[4] or 0,
            "skus": r[5] or 0,
            "share": f"{(fat_val / total_fat * 100):.2f}%" if total_fat > 0 else "0.00%"
        })

    # 7. Vendedores
    vendedor_query = db.query(
        Model.vendedor,
        func.sum(Model.valor_fat).label('fat'),
        func.sum(Model.unid_faturada).label('unid'),
        func.count(distinct(Model.cnpj)).label('cnpjs'),
        func.count(distinct(Model.ean)).label('skus')
    ).filter(Model.client_id == client_id)
    vendedor_query = apply_filters(vendedor_query).group_by(Model.vendedor).order_by(func.sum(Model.valor_fat).desc())
    vendedor_rows = vendedor_query.all()
    
    detailed_vendedores = []
    for i, r in enumerate(vendedor_rows):
        fat_val = r[1] or 0.0
        unid_val = r[2] or 0.0
        detailed_vendedores.append({
            "rank": i + 1,
            "vendedor": r[0] or "Sem Vendedor",
            "faturamento": f"R$ {fat_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "unidades": int(unid_val),
            "ticket_medio": f"R$ {fat_val/unid_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if unid_val > 0 else "R$ 0,00",
            "cnpjs": r[3] or 0,
            "skus": r[4] or 0,
            "share": f"{(fat_val / total_fat * 100):.2f}%" if total_fat > 0 else "0.00%"
        })
        
    db.close()
    
    return jsonify({
        "kpis": {
            "faturamento": f"R$ {total_fat:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "faturamento_top50": f"R$ {fat_top50:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "faturamento_top20_skus": f"R$ {fat_top20_skus:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "faturamento_raw": total_fat,
            "unidades": f"{int(total_unidades):,}".replace(",", "."),
            "ticket_medio": f"R$ {ticket_medio:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "cnpjs": f"{int(cnpjs_positivados):,}".replace(",", "."),
            "skus_distinct": total_skus_distinct
        },
        "charts": {
            "top_clients_labels": top_clients_labels,
            "top_clients_values": top_clients_values,
            "months_labels": chart_months,
            "months_values": chart_month_values,
            "months_units": chart_month_units,
            "months_cnpjs": chart_month_cnpjs,
            "months_tickets": chart_month_tickets,
            "top_products_labels": top_products_labels,
            "top_products_values": top_products_values,
            "distrib_labels": [d["distribuidor"] for d in distrib_list],
            "distrib_values": [d["faturamento"] for d in distrib_list]
        },
        "tables": {
            "clients": detailed_clients,
            "products": detailed_products,
            "distributors": distrib_list,
            "supervisors": detailed_supervisors,
            "vendedores": detailed_vendedores
        }
    })

# ---- ENDPOINT DE CRUZAMENTO DE BASES (DECISÃO COMERCIAL) ----

@app.route('/api/cruzamento/<service>', methods=['POST'])
@login_required
def api_cruzamento(service):
    client_id = session.get('client_id')
    if not client_id:
        return jsonify({"error": "Sem dados de cliente."}), 400
        
    params = request.json or {}
    base_filters = params.get('base', {})
    anal_filters = params.get('analise', {})
    
    db = get_db()
    Model = SellOutRow if service == "sell_out" else SellInRow
    
    # Helper para aplicar os filtros a uma query (multi-seleção via IN)
    def apply_query_filters(q, filters):
        if filters.get('industria') and 'Todas' not in filters['industria'] and len(filters['industria']) > 0:
            q = q.filter(Model.industria.in_(filters['industria']))
            
        if filters.get('distribuidor') and 'Todos' not in filters['distribuidor'] and len(filters['distribuidor']) > 0:
            q = q.filter(Model.distribuidor.in_(filters['distribuidor']))
            
        if filters.get('supervisor') and 'Todos' not in filters['supervisor'] and len(filters['supervisor']) > 0:
            q = q.filter(Model.supervisor.in_(filters['supervisor']))
            
        if filters.get('vendedor') and 'Todos' not in filters['vendedor'] and len(filters['vendedor']) > 0:
            q = q.filter(Model.vendedor.in_(filters['vendedor']))
            
        if filters.get('cliente') and 'Todos' not in filters['cliente'] and len(filters['cliente']) > 0:
            q = q.filter(Model.razao_social.in_(filters['cliente']))
            
        if filters.get('produto') and 'Todos' not in filters['produto'] and len(filters['produto']) > 0:
            q = q.filter(Model.material_desc.in_(filters['produto']))
            
        if filters.get('ano') and 'Todos' not in filters['ano'] and len(filters['ano']) > 0:
            anos = []
            for a in filters['ano']:
                try:
                    anos.append(int(a))
                except:
                    pass
            if anos:
                q = q.filter(Model.ano.in_(anos))
                
        if filters.get('mes') and 'Todos' not in filters['mes'] and len(filters['mes']) > 0:
            q = q.filter(Model.mes.in_(filters['mes']))
            
        return q

    # 1. Base Padrão: CNPJ, Razão Social, faturamento, unidades e mix
    base_q = db.query(
        Model.cnpj.label('cnpj'),
        func.max(Model.razao_social).label('cliente'),
        func.sum(Model.valor_fat).label('base_val'),
        func.sum(Model.unid_faturada).label('base_unid'),
        func.count(distinct(Model.ean)).label('base_mix')
    ).filter(Model.client_id == client_id)
    base_q = apply_query_filters(base_q, base_filters)
    base_rows = base_q.group_by(Model.cnpj).all()
    
    # 2. Base Análise: CNPJ, faturamento e unidades
    anal_q = db.query(
        Model.cnpj.label('cnpj'),
        func.sum(Model.valor_fat).label('anal_val'),
        func.sum(Model.unid_faturada).label('anal_unid')
    ).filter(Model.client_id == client_id)
    anal_q = apply_query_filters(anal_q, anal_filters)
    anal_rows = anal_q.group_by(Model.cnpj).all()
    
    db.close()
    
    # Mapear Base Análise por CNPJ para junção rápida em memória
    anal_map = {}
    for r in anal_rows:
        if r.cnpj:
            anal_map[r.cnpj] = {
                "anal_val": r.anal_val or 0.0,
                "anal_unid": r.anal_unid or 0.0
            }
            
    # Realizar junção LEFT JOIN e acumular KPIs
    rows = []
    base_total = 0.0
    base_count = 0
    anal_total = 0.0
    anal_count = 0
    
    for r in base_rows:
        if not r.cnpj:
            continue
        b_val = r.base_val or 0.0
        b_unid = r.base_unid or 0.0
        b_mix = r.base_mix or 0
        
        base_total += b_val
        base_count += 1
        
        a_data = anal_map.get(r.cnpj, {"anal_val": 0.0, "anal_unid": 0.0})
        a_val = a_data["anal_val"]
        a_unid = a_data["anal_unid"]
        
        if a_val > 0:
            anal_total += a_val
            anal_count += 1
            
        rows.append({
            "cnpj": r.cnpj,
            "cliente": r.cliente or "Desconhecido",
            "base_val": b_val,
            "base_unid": b_unid,
            "base_mix": b_mix,
            "anal_val": a_val,
            "anal_unid": a_unid
        })
        
    return jsonify({
        "base_count": base_count,
        "base_total": base_total,
        "anal_count": anal_count,
        "anal_total": anal_total,
        "rows": rows
    })


# ---- PAINEL ADMINISTRATIVO (ADMIN_ROUTES) ----

@app.route('/admin')
@admin_required
def admin_dashboard():
    db = get_db()
    clients_count = db.query(func.count(Client.id)).filter_by(status="Ativo").scalar()
    users_count = db.query(func.count(User.id)).scalar()
    uploads_count = db.query(func.count(UploadHistory.id)).scalar()
    
    # Uploads hoje
    today = datetime.utcnow().date()
    uploads_today = db.query(func.count(UploadHistory.id)).filter(
        func.date(UploadHistory.upload_date) == today
    ).scalar()
    
    # Listagem de clientes
    clients = db.query(Client).all()
    client_list = []
    for c in clients:
        u_count = db.query(func.count(User.id)).filter_by(client_id=c.id).scalar()
        up_count = db.query(func.count(UploadHistory.id)).filter_by(client_id=c.id).scalar()
        client_list.append({
            "id": c.id,
            "name": c.name,
            "slug": c.slug,
            "status": c.status,
            "users": u_count,
            "uploads": up_count
        })
        
    # Uploads Recentes
    recent_uploads = db.query(UploadHistory).order_by(UploadHistory.upload_date.desc()).limit(5).all()
    upload_list = []
    for up in recent_uploads:
        c = db.query(Client).filter_by(id=up.client_id).first()
        upload_list.append({
            "filename": up.filename,
            "client_name": c.name if c else "Desconhecido",
            "date": up.upload_date.strftime("%d/%m/%Y %H:%M"),
            "status": up.status,
            "rows": up.num_rows
        })
        
    db.close()
    return render_template('admin/dashboard.html', 
                           clients_count=clients_count,
                           users_count=users_count,
                           uploads_count=uploads_count,
                           uploads_today=uploads_today,
                           clients=client_list,
                           recent_uploads=upload_list)

@app.route('/admin/clients')
@admin_required
def admin_clients():
    db = get_db()
    clients = db.query(Client).all()
    client_list = []
    for c in clients:
        client_list.append({
            "id": c.id,
            "name": c.name,
            "slug": c.slug,
            "status": c.status,
            "primary_color": c.primary_color,
            "secondary_color": c.secondary_color
        })
    db.close()
    return render_template('admin/clients.html', clients=client_list)

@app.route('/admin/clients/new', methods=['POST'])
@admin_required
def admin_new_client():
    name = request.form.get('name')
    slug = request.form.get('slug')
    primary_color = request.form.get('primary_color', '#6366f1')
    secondary_color = request.form.get('secondary_color', '#f97316')
    services = request.form.getlist('services')
    
    db = get_db()
    
    # Criar cliente
    client = Client(
        name=name,
        slug=slug,
        primary_color=primary_color,
        secondary_color=secondary_color,
        enabled_services=",".join(services),
        status="Ativo"
    )
    db.add(client)
    db.commit()
    db.close()
    
    flash("Cliente criado com sucesso!", "success")
    return redirect(url_for('admin_clients'))

@app.route('/admin/clients/<int:client_id>/manage')
@admin_required
def admin_manage_client(client_id):
    db = get_db()
    client = db.query(Client).filter_by(id=client_id).first()
    if not client:
        db.close()
        return redirect(url_for('admin_clients'))
        
    users = db.query(User).filter_by(client_id=client.id).all()
    payments = db.query(SubscriptionPayment).filter_by(client_id=client.id).all()
    
    db.close()
    return render_template('admin/manage_client.html', client=client, users=users, payments=payments)

@app.route('/admin/clients/<int:client_id>/users/new', methods=['POST'])
@admin_required
def admin_new_client_user(client_id):
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    permission = request.form.get('permission', 'VISUALIZADOR')
    
    db = get_db()
    hashed = hashlib.sha256(password.encode()).hexdigest()
    
    new_user = User(
        client_id=client_id,
        username=username,
        email=email,
        password_hash=hashed,
        permission=permission,
        status="Ativo"
    )
    db.add(new_user)
    db.commit()
    db.close()
    
    flash("Usuário de acesso cadastrado!", "success")
    return redirect(url_for('admin_manage_client', client_id=client_id))

@app.route('/admin/clients/<int:client_id>/update_identity', methods=['POST'])
@admin_required
def admin_update_identity(client_id):
    db = get_db()
    client = db.query(Client).filter_by(id=client_id).first()
    
    if client:
        client.primary_color = request.form.get('primary_color')
        client.secondary_color = request.form.get('secondary_color')
        
        # Upload de Logo
        logo_file = request.files.get('logo')
        if logo_file and logo_file.filename:
            filename = secure_filename(f"logo_{client.slug}_{logo_file.filename}")
            static_upload_dir = os.path.join(app.root_path, 'static', 'uploads')
            os.makedirs(static_upload_dir, exist_ok=True)
            logo_file.save(os.path.join(static_upload_dir, filename))
            # Always use forward slashes for URL path (Linux/Vercel compatible)
            client.logo_path = f"/static/uploads/{filename}"
            
        db.commit()
    db.close()
    flash("Configurações visuais atualizadas!", "success")
    return redirect(url_for('admin_manage_client', client_id=client_id))

@app.route('/admin/clients/<int:client_id>/update_billing', methods=['POST'])
@admin_required
def admin_update_billing(client_id):
    db = get_db()
    client = db.query(Client).filter_by(id=client_id).first()
    if client:
        client.subscription_value = float(request.form.get('subscription_value', 0.0))
        client.subscription_due_day = int(request.form.get('subscription_due_day', 5))
        client.subscription_status = request.form.get('subscription_status', 'Ativo')
        db.commit()
    db.close()
    flash("Dados de assinatura salvos!", "success")
    return redirect(url_for('admin_manage_client', client_id=client_id))


# ---- PAINEL FINANCEIRO (MENSALIDADES) ----

@app.route('/admin/finance')
@admin_required
def admin_finance():
    db = get_db()
    clients = db.query(Client).all()
    # Coletar pagamentos recentes
    payments = db.query(SubscriptionPayment).order_by(SubscriptionPayment.reference_month.desc()).all()
    db.close()
    return render_template('admin/finance.html', clients=clients, payments=payments)

@app.route('/admin/finance/payment/new', methods=['POST'])
@admin_required
def admin_register_payment():
    client_id = int(request.form.get('client_id'))
    ref_month = request.form.get('reference_month')
    amount = float(request.form.get('amount'))
    status = request.form.get('status')
    
    db = get_db()
    payment = SubscriptionPayment(
        client_id=client_id,
        reference_month=ref_month,
        amount=amount,
        status=status,
        payment_date=datetime.utcnow() if status == "Pago" else None
    )
    db.add(payment)
    db.commit()
    db.close()
    flash("Mensalidade cadastrada!", "success")
    return redirect(url_for('admin_finance'))


# ---- TELA DE UPLOAD & AGENT PROGRESS BAR ----

# Dicionário em memória para guardar progresso do upload
# Em ambiente de produção usaria Redis/Celery, mas para SQLite/Flask local isso funciona perfeitamente.
UPLOAD_PROGRESS = {}

@app.route('/admin/upload', methods=['GET'])
@admin_required
def admin_upload_page():
    db = get_db()
    clients = db.query(Client).filter_by(status="Ativo").all()
    
    # Buscar histórico completo de uploads
    history = db.query(UploadHistory).order_by(UploadHistory.upload_date.desc()).all()
    history_list = []
    for h in history:
        c = db.query(Client).filter_by(id=h.client_id).first()
        history_list.append({
            "id": h.id,
            "filename": h.filename,
            "client_name": c.name if c else "Desconhecido",
            "date": h.upload_date.strftime("%d/%m/%Y, %H:%M"),
            "data_type": h.data_type,
            "rows": h.num_rows,
            "status": h.status
        })
        
    db.close()
    return render_template('admin/upload.html', clients=clients, history=history_list)

@app.route('/admin/upload/delete/<int:history_id>', methods=['POST'])
@admin_required
def admin_delete_upload(history_id):
    db = get_db()
    history = db.query(UploadHistory).filter_by(id=history_id).first()
    if history:
        # Se for deletar o upload do histórico, deletamos também os registros da base correspondentes
        # Mapeado por client_id e data_type
        if history.data_type == "Sell Out":
            db.query(SellOutRow).filter_by(client_id=history.client_id).delete()
        else:
            db.query(SellInRow).filter_by(client_id=history.client_id).delete()
            
        db.delete(history)
        db.commit()
        flash("Upload e registros associados deletados com sucesso!", "success")
    db.close()
    return redirect(url_for('admin_upload_page'))

@app.route('/admin/upload/start', methods=['POST'])
@admin_required
def admin_upload_start():
    client_id = int(request.form.get('client_id'))
    data_type = request.form.get('data_type')
    
    db = get_db()
    try:
        if data_type == "Sell Out":
            db.query(SellOutRow).filter_by(client_id=client_id).delete()
        else:
            db.query(SellInRow).filter_by(client_id=client_id).delete()
        db.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/admin/upload/batch', methods=['POST'])
@admin_required
def admin_upload_batch():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Dados inválidos."}), 400
        
    client_id = int(data.get('client_id'))
    data_type = data.get('data_type')
    rows = data.get('rows', [])
    
    if not rows:
        return jsonify({"success": True, "inserted": 0})
        
    db = get_db()
    try:
        if data_type == "Sell Out":
            db.bulk_insert_mappings(SellOutRow, rows)
        else:
            db.bulk_insert_mappings(SellInRow, rows)
        db.commit()
        return jsonify({"success": True, "inserted": len(rows)})
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/admin/upload/finalize', methods=['POST'])
@admin_required
def admin_upload_finalize():
    client_id = int(request.form.get('client_id'))
    data_type = request.form.get('data_type')
    filename = secure_filename(request.form.get('filename'))
    total_rows = int(request.form.get('total_rows', 0))
    
    db = get_db()
    try:
        history = UploadHistory(
            client_id=client_id,
            filename=filename,
            data_type=data_type,
            num_rows=total_rows,
            status="Concluído"
        )
        db.add(history)
        db.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
