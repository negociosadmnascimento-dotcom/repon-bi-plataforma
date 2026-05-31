import os
import hashlib
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_from_directory
from werkzeug.utils import secure_filename
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func, distinct, or_
from models import get_engine, User, Client, SellOutRow, SellInRow, SubscriptionPayment, UploadHistory, init_db
from data_parser import parse_excel_and_import

# Inicializar Banco de dados
init_db()

app = Flask(__name__)
app.secret_key = "lpl_repon_analytics_super_secret_key"

# Pasta de upload compatível com caminhos relativos em ambientes serverless (Vercel)
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(app.root_path, 'uploads'))
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Helper para obter sessão do banco de dados por requisição
def get_db():
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()

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
                theme_data['logo'] = "/static/img/default_logo.png"
                theme_data['primary_color'] = "#6366f1"
                theme_data['secondary_color'] = "#f97316"
                theme_data['client_name'] = "Administração LPL"
            elif user.client:
                theme_data['enabled_services'] = [s.strip() for s in user.client.enabled_services.split(",") if s.strip()]
                theme_data['logo'] = user.client.logo_path or "/static/img/default_logo.png"
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
    
    query = db.query(Model).filter_by(client_id=client_id)
    
    # Aplicar filtros
    if filters.get('industria') and filters['industria'] != 'Todas':
        query = query.filter(Model.industria == filters['industria'])
    if filters.get('distribuidor') and filters['distribuidor'] != 'Todos':
        query = query.filter(Model.distribuidor == filters['distribuidor'])
    if filters.get('supervisor') and filters['supervisor'] != 'Todos':
        query = query.filter(Model.supervisor == filters['supervisor'])
    if filters.get('vendedor') and filters['vendedor'] != 'Todos':
        query = query.filter(Model.vendedor == filters['vendedor'])
    if filters.get('cliente') and filters['cliente'] != 'Todos':
        query = query.filter(Model.cliente == filters['cliente'])
    if filters.get('uf') and filters['uf'] != 'Todas':
        query = query.filter(Model.uf == filters['uf'])
    if filters.get('ano') and filters['ano'] != 'Todos':
        query = query.filter(Model.ano == int(filters['ano']))
    if filters.get('mes') and filters['mes'] != 'Todos':
        query = query.filter(Model.mes == filters['mes'])
    if filters.get('produto') and filters['produto'] != 'Todos':
        query = query.filter(Model.material_desc == filters['produto'])
        
    rows = query.all()
    
    # Calcular KPIs Gerais
    total_fat = sum(r.valor_fat for r in rows)
    total_unidades = sum(r.unid_faturada for r in rows)
    ticket_medio = total_fat / total_unidades if total_unidades > 0 else 0.0
    cnpjs_positivados = len(set(r.cnpj for r in rows if r.cnpj))
    
    # Faturamento por Mês
    months_ordered = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    month_fat = {m: 0.0 for m in months_ordered}
    month_unid = {m: 0.0 for m in months_ordered}
    month_cnpjs = {m: set() for m in months_ordered}
    
    # Detalhado por cliente para Aba Clientes
    # CNPJ -> {razao, uf, fat, unidades, skus: set(), meses: set()}
    client_map = {}
    
    # Detalhado por produto para Aba Produtos
    # EAN -> {desc, industria, fat, unidades, cnpjs: set()}
    product_map = {}
    
    # Detalhado por distribuidor
    distrib_fat = {}
    distrib_cnpjs = {}
    
    # Detalhado por supervisor
    supervisor_map = {} # nome -> {distrib, fat, unidades, cnpjs: set(), skus: set()}
    
    # Detalhado por vendedor
    vendedor_map = {} # nome -> {fat, unidades, cnpjs: set(), skus: set()}
    
    for r in rows:
        m = r.mes
        if m in month_fat:
            month_fat[m] += r.valor_fat
            month_unid[m] += r.unid_faturada
            if r.cnpj:
                month_cnpjs[m].add(r.cnpj)
                
        # Cliente mapping
        c_key = r.cnpj or r.razao_social or "Sem CNPJ"
        if c_key not in client_map:
            client_map[c_key] = {
                "cnpj": r.cnpj or "Sem CNPJ",
                "razao_social": r.razao_social or "Desconhecido",
                "uf": r.uf or "--",
                "faturamento": 0.0,
                "unidades": 0.0,
                "skus": set(),
                "meses": set()
            }
        client_map[c_key]["faturamento"] += r.valor_fat
        client_map[c_key]["unidades"] += r.unid_faturada
        if r.ean:
            client_map[c_key]["skus"].add(r.ean)
        if r.mes:
            client_map[c_key]["meses"].add(r.mes)
            
        # Produto mapping
        p_key = r.ean or r.material_desc or "Sem EAN"
        if p_key not in product_map:
            product_map[p_key] = {
                "ean": r.ean or "Sem EAN",
                "material_desc": r.material_desc or "Sem Descrição",
                "industria": r.industria or "--",
                "faturamento": 0.0,
                "unidades": 0.0,
                "cnpjs": set()
            }
        product_map[p_key]["faturamento"] += r.valor_fat
        product_map[p_key]["unidades"] += r.unid_faturada
        if r.cnpj:
            product_map[p_key]["cnpjs"].add(r.cnpj)
            
        # Distribuidor mapping
        d_key = r.distribuidor or "Outros"
        distrib_fat[d_key] = distrib_fat.get(d_key, 0.0) + r.valor_fat
        if d_key not in distrib_cnpjs:
            distrib_cnpjs[d_key] = set()
        if r.cnpj:
            distrib_cnpjs[d_key].add(r.cnpj)
            
        # Supervisor mapping
        s_key = r.supervisor or "Sem Supervisor"
        if s_key not in supervisor_map:
            supervisor_map[s_key] = {
                "supervisor": s_key,
                "distribuidor": r.distribuidor or "--",
                "faturamento": 0.0,
                "unidades": 0.0,
                "cnpjs": set(),
                "skus": set()
            }
        supervisor_map[s_key]["faturamento"] += r.valor_fat
        supervisor_map[s_key]["unidades"] += r.unid_faturada
        if r.cnpj:
            supervisor_map[s_key]["cnpjs"].add(r.cnpj)
        if r.ean:
            supervisor_map[s_key]["skus"].add(r.ean)
            
        # Vendedor mapping
        v_key = r.vendedor or "Sem Vendedor"
        if v_key not in vendedor_map:
            vendedor_map[v_key] = {
                "vendedor": v_key,
                "faturamento": 0.0,
                "unidades": 0.0,
                "cnpjs": set(),
                "skus": set()
            }
        vendedor_map[v_key]["faturamento"] += r.valor_fat
        vendedor_map[v_key]["unidades"] += r.unid_faturada
        if r.cnpj:
            vendedor_map[v_key]["cnpjs"].add(r.cnpj)
        if r.ean:
            vendedor_map[v_key]["skus"].add(r.ean)
            
    # Formatar dados de meses (remover meses sem faturamento ou manter ordem)
    chart_months = [m for m in months_ordered if month_fat[m] > 0]
    chart_month_values = [month_fat[m] for m in chart_months]
    chart_month_units = [month_unid[m] for m in chart_months]
    chart_month_cnpjs = [len(month_cnpjs[m]) for m in chart_months]
    chart_month_tickets = [month_fat[m] / month_unid[m] if month_unid[m] > 0 else 0.0 for m in chart_months]
    
    # Ranking Clientes
    sorted_clients = sorted(client_map.values(), key=lambda x: x["faturamento"], reverse=True)
    top_clients_labels = [c["razao_social"] for c in sorted_clients[:10]]
    top_clients_values = [c["faturamento"] for c in sorted_clients[:10]]
    
    # Formatação do Ranking detalhado de Clientes
    detailed_clients = []
    for i, c in enumerate(sorted_clients):
        detailed_clients.append({
            "rank": i + 1,
            "cnpj": c["cnpj"],
            "razao_social": c["razao_social"],
            "uf": c["uf"],
            "faturamento": f"R$ {c['faturamento']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "unidades": int(c["unidades"]),
            "mix": len(c["skus"]),
            "frequencia": len(c["meses"]),
            "ticket_medio": f"R$ {c['faturamento']/c['unidades']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if c["unidades"] > 0 else "R$ 0,00",
            "share": f"{(c['faturamento'] / total_fat * 100):.2f}%" if total_fat > 0 else "0.00%"
        })
        
    # Faturamento Top 50 (Soma dos 50 primeiros)
    fat_top50 = sum(c["faturamento"] for c in sorted_clients[:50])
    
    # Total de SKUs distintos faturados
    total_skus_distinct = len(product_map)
    
    # Ranking Produtos
    sorted_products = sorted(product_map.values(), key=lambda x: x["faturamento"], reverse=True)
    top_products_labels = [p["material_desc"] for p in sorted_products[:10]]
    top_products_values = [p["faturamento"] for p in sorted_products[:10]]
    
    detailed_products = []
    for i, p in enumerate(sorted_products):
        detailed_products.append({
            "rank": i + 1,
            "ean": p["ean"],
            "material_desc": p["material_desc"],
            "industria": p["industria"],
            "faturamento": f"R$ {p['faturamento']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "unidades": int(p["unidades"]),
            "cnpjs": len(p["cnpjs"]),
            "ticket_medio": f"R$ {p['faturamento']/p['unidades']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if p["unidades"] > 0 else "R$ 0,00",
            "share": f"{(p['faturamento'] / total_fat * 100):.2f}%" if total_fat > 0 else "0.00%"
        })
        
    # Faturamento Top 20 SKUs
    fat_top20_skus = sum(p["faturamento"] for p in sorted_products[:20])
    
    # Formatadores do Distribuidor
    distrib_list = []
    for d, f in distrib_fat.items():
        distrib_list.append({
            "distribuidor": d,
            "faturamento": f,
            "faturamento_str": f"R$ {f:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "cnpjs": len(distrib_cnpjs.get(d, set())),
            "share": f"{(f / total_fat * 100):.2f}%" if total_fat > 0 else "0.00%"
        })
    distrib_list = sorted(distrib_list, key=lambda x: x["faturamento"], reverse=True)
    
    # Formatadores de Supervisor
    sorted_supervisors = sorted(supervisor_map.values(), key=lambda x: x["faturamento"], reverse=True)
    detailed_supervisors = []
    for i, s in enumerate(sorted_supervisors):
        detailed_supervisors.append({
            "rank": i + 1,
            "supervisor": s["supervisor"],
            "distribuidor": s["distribuidor"],
            "faturamento": f"R$ {s['faturamento']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "unidades": int(s["unidades"]),
            "ticket_medio": f"R$ {s['faturamento']/s['unidades']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if s["unidades"] > 0 else "R$ 0,00",
            "cnpjs": len(s["cnpjs"]),
            "skus": len(s["skus"]),
            "share": f"{(s['faturamento'] / total_fat * 100):.2f}%" if total_fat > 0 else "0.00%"
        })
        
    # Formatadores de Vendedores
    sorted_vendedores = sorted(vendedor_map.values(), key=lambda x: x["faturamento"], reverse=True)
    detailed_vendedores = []
    for i, v in enumerate(sorted_vendedores):
        detailed_vendedores.append({
            "rank": i + 1,
            "vendedor": v["vendedor"],
            "faturamento": f"R$ {v['faturamento']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "unidades": int(v["unidades"]),
            "ticket_medio": f"R$ {v['faturamento']/v['unidades']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if v["unidades"] > 0 else "R$ 0,00",
            "cnpjs": len(v["cnpjs"]),
            "skus": len(v["skus"]),
            "share": f"{(v['faturamento'] / total_fat * 100):.2f}%" if total_fat > 0 else "0.00%"
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
            "cnpjs": cnpjs_positivados,
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
            logo_path = os.path.join('static/uploads', filename)
            os.makedirs(os.path.join(app.root_path, 'static/uploads'), exist_ok=True)
            logo_file.save(os.path.join(app.root_path, logo_path))
            client.logo_path = f"/{logo_path}"
            
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
    db.close()
    return render_template('admin/upload.html', clients=clients)

@app.route('/admin/upload/process', methods=['POST'])
@admin_required
def admin_upload_process():
    import uuid
    import threading
    
    client_id = int(request.form.get('client_id'))
    data_type = request.form.get('data_type')
    file = request.files.get('file')
    
    if not file or not file.filename:
        return jsonify({"success": False, "error": "Nenhum arquivo enviado."}), 400
        
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    
    # Criar ID único para rastrear o progresso do upload
    upload_id = str(uuid.uuid4())
    UPLOAD_PROGRESS[upload_id] = {
        "status": "Iniciando",
        "progress": 0,
        "current_row": 0,
        "total_rows": 0,
        "error": None
    }
    
    # Executar o processador em uma thread paralela para não travar a requisição HTTP (evitando timeout/locks)
    def run_async_import(uid, cid, path, dtype, orig_name):
        try:
            # 1. Carregar arquivo e calcular tamanho total
            ext = orig_name.lower().split('.')[-1]
            UPLOAD_PROGRESS[uid]["status"] = "Lendo arquivo..."
            UPLOAD_PROGRESS[uid]["progress"] = 10
            
            if ext == 'csv':
                try:
                    df = pd.read_csv(path, sep=';', encoding='utf-8')
                except UnicodeDecodeError:
                    df = pd.read_csv(path, sep=';', encoding='latin1')
            else:
                df = pd.read_excel(path, engine='openpyxl')
                
            total = len(df)
            UPLOAD_PROGRESS[uid]["total_rows"] = total
            UPLOAD_PROGRESS[uid]["status"] = "Validando colunas..."
            UPLOAD_PROGRESS[uid]["progress"] = 20
            
            # Normalizar colunas
            df.columns = [str(col).strip().upper() for col in df.columns]
            
            # Colunas obrigatórias
            required_cols = ["INDUSTRIA", "DATA", "CNPJ", "RAZAO SOCIAL", "UF", "VALOR FAT.", "UNID. FATURADA", "DISTRIBUIDOR"]
            missing_cols = [c for c in required_cols if c not in df.columns]
            if missing_cols:
                raise ValueError(f"Colunas obrigatórias ausentes no arquivo: {', '.join(missing_cols)}")
            
            # 2. Deletar registros antigos do cliente
            UPLOAD_PROGRESS[uid]["status"] = "Limpando registros anteriores..."
            UPLOAD_PROGRESS[uid]["progress"] = 30
            
            # Criar conexão separada para a thread
            engine = get_engine()
            Session = sessionmaker(bind=engine)
            session = Session()
            
            try:
                if dtype == "Sell Out":
                    session.query(SellOutRow).filter_by(client_id=cid).delete()
                else:
                    session.query(SellInRow).filter_by(client_id=cid).delete()
                session.commit()
            except Exception as dberr:
                session.rollback()
                raise dberr
                
            # 3. Iterar e salvar em lotes
            UPLOAD_PROGRESS[uid]["status"] = "Importando registros para o Banco..."
            rows_to_insert = []
            count = 0
            
            for idx, row in df.iterrows():
                def val(col_name, default=None, is_num=False):
                    if col_name not in df.columns:
                        return default
                    val_raw = row[col_name]
                    if pd.isna(val_raw):
                        return default
                    if is_num:
                        try:
                            # Tratar string numérica com formato brasileiro (ex: 1.250,45 ou R$ 10,00)
                            val_str = str(val_raw).replace("R$", "").replace(" ", "").strip()
                            if "," in val_str and "." in val_str:
                                val_str = val_str.replace(".", "").replace(",", ".")
                            elif "," in val_str:
                                val_str = val_str.replace(",", ".")
                            return float(val_str)
                        except ValueError:
                            return default
                    return str(val_raw).strip()
                
                val_fat = val("VALOR FAT.", 0.0, is_num=True)
                unid_fat = val("UNID. FATURADA", 0.0, is_num=True)
                share = val("SHARE %", 0.0, is_num=True)
                val_ol = val("VALOR OL", 0.0, is_num=True)
                ano_val = val("ANO", None, is_num=True)
                if ano_val is not None:
                    ano_val = int(ano_val)
                
                row_data = {
                    "client_id": cid,
                    "industria": val("INDUSTRIA"),
                    "data": val("DATA"),
                    "cnpj": val("CNPJ"),
                    "razao_social": val("RAZAO SOCIAL"),
                    "id_supervisor": val("ID SUPERVISOR"),
                    "supervisor": val("SUPERVISOR"),
                    "id_vendedor": val("ID VENDEDOR"),
                    "vendedor": val("VENDEDOR"),
                    "uf": val("UF"),
                    "ean": val("EAN"),
                    "material_desc": val("MATERIAL/DESC"),
                    "unid_faturada": unid_fat,
                    "valor_fat": val_fat,
                    "distribuidor": val("DISTRIBUIDOR"),
                    "ano": ano_val,
                    "rede": val("REDE"),
                    "cliente": val("CLIENTE"),
                    "status_ol": val("STATUS OL"),
                    "status_manual": val("STATUS MANUAL"),
                    "valor_ol": val_ol,
                    "share_percent": share,
                    "mes": val("MES")
                }
                
                if dtype == "Sell Out":
                    db_row = SellOutRow(**row_data)
                else:
                    db_row = SellInRow(**row_data)
                    
                rows_to_insert.append(db_row)
                count += 1
                
                # Batch commits de 1000 em 1000
                if len(rows_to_insert) >= 1000:
                    session.bulk_save_objects(rows_to_insert)
                    session.commit()
                    rows_to_insert = []
                    
                    # Atualizar progresso dinâmico (escala entre 30% e 95%)
                    current_prog = 30 + int((count / total) * 65)
                    UPLOAD_PROGRESS[uid]["progress"] = current_prog
                    UPLOAD_PROGRESS[uid]["current_row"] = count
            
            if rows_to_insert:
                session.bulk_save_objects(rows_to_insert)
                session.commit()
                
            # Adicionar histórico de upload concluído
            history = UploadHistory(
                client_id=cid,
                filename=orig_name,
                data_type=dtype,
                num_rows=count,
                status="Concluído"
            )
            session.add(history)
            session.commit()
            
            UPLOAD_PROGRESS[uid]["status"] = "Concluído"
            UPLOAD_PROGRESS[uid]["progress"] = 100
            UPLOAD_PROGRESS[uid]["current_row"] = count
            session.close()
            
        except Exception as err:
            UPLOAD_PROGRESS[uid]["status"] = "Erro"
            UPLOAD_PROGRESS[uid]["error"] = str(err)
            
            # Gravar falha no banco de dados
            try:
                engine = get_engine()
                Session = sessionmaker(bind=engine)
                session = Session()
                history = UploadHistory(
                    client_id=cid,
                    filename=orig_name,
                    data_type=dtype,
                    num_rows=0,
                    status="Erro"
                )
                session.add(history)
                session.commit()
                session.close()
            except:
                pass
                
    # Iniciar a execução assíncrona do parser
    import pandas as pd # certificar de que pandas esteja disponível na thread
    threading.Thread(target=run_async_import, args=(upload_id, client_id, filepath, data_type, file.filename)).start()
    
    return jsonify({"success": True, "upload_id": upload_id})

@app.route('/admin/upload/status/<upload_id>')
@admin_required
def admin_upload_status(upload_id):
    progress = UPLOAD_PROGRESS.get(upload_id)
    if not progress:
        return jsonify({"error": "Identificador de upload não encontrado."}), 404
    return jsonify(progress)


if __name__ == '__main__':
    app.run(debug=True, port=5000)
