import os
import hashlib
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

Base = declarative_base()

class Client(Base):
    __tablename__ = 'clients'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    status = Column(String(20), default="Ativo") # Ativo, Inativo
    
    # Identidade & Dashboard
    logo_path = Column(String(255), default="/static/img/default_logo.png")
    primary_color = Column(String(7), default="#1e1b4b")   # Cores padrão do tema
    secondary_color = Column(String(7), default="#f97316")
    
    # Serviços habilitados (separados por vírgula: "Sell Out,Sell In,OL,Campanhas")
    enabled_services = Column(String(255), default="Sell Out")
    
    # Assinatura
    subscription_value = Column(Float, default=0.0)
    subscription_due_day = Column(Integer, default=5)
    subscription_status = Column(String(20), default="Ativo") # Ativo, Suspenso
    
    # Relacionamentos
    users = relationship("User", back_populates="client", cascade="all, delete-orphan")
    payments = relationship("SubscriptionPayment", back_populates="client", cascade="all, delete-orphan")
    sell_out_data = relationship("SellOutRow", back_populates="client", cascade="all, delete-orphan")
    sell_in_data = relationship("SellInRow", back_populates="client", cascade="all, delete-orphan")
    uploads = relationship("UploadHistory", back_populates="client", cascade="all, delete-orphan")

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=True) # Null se for admin do sistema
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    permission = Column(String(20), default="VISUALIZADOR") # ADMINISTRADOR, VISUALIZADOR
    status = Column(String(20), default="Ativo") # Ativo, Inativo
    is_system_admin = Column(Boolean, default=False)
    
    client = relationship("Client", back_populates="users")

class SubscriptionPayment(Base):
    __tablename__ = 'subscription_payments'
    
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=False)
    reference_month = Column(String(7), nullable=False)  # Ex: "2026-05"
    amount = Column(Float, nullable=False)
    status = Column(String(20), default="Pendente")  # Pago, Pendente, Atrasado
    payment_date = Column(DateTime, nullable=True)
    
    client = relationship("Client", back_populates="payments")

class UploadHistory(Base):
    __tablename__ = 'upload_history'
    
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=False)
    filename = Column(String(255), nullable=False)
    data_type = Column(String(20), nullable=False) # "Sell Out" ou "Sell In"
    upload_date = Column(DateTime, default=datetime.utcnow)
    num_rows = Column(Integer, default=0)
    status = Column(String(20), default="Concluído") # Concluído, Erro
    
    client = relationship("Client", back_populates="uploads")

# Colunas reais fornecidas pelo usuário para Sell Out / Sell In
class SellOutRow(Base):
    __tablename__ = 'sell_out_rows'
    
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=False)
    
    industria = Column(String(100))
    data = Column(String(20)) # Mantido como string para flexibilidade do Excel
    cnpj = Column(String(20))
    razao_social = Column(String(255))
    id_supervisor = Column(String(50))
    supervisor = Column(String(100))
    id_vendedor = Column(String(50))
    vendedor = Column(String(100))
    uf = Column(String(2))
    ean = Column(String(50))
    material_desc = Column(String(255))
    unid_faturada = Column(Float, default=0.0)
    valor_fat = Column(Float, default=0.0)
    distribuidor = Column(String(100))
    ano = Column(Integer)
    rede = Column(String(100))
    cliente = Column(String(255))
    status_ol = Column(String(50))
    status_manual = Column(String(50))
    valor_ol = Column(Float, default=0.0)
    share_percent = Column(Float, default=0.0)
    mes = Column(String(20))
    
    client = relationship("Client", back_populates="sell_out_data")

class SellInRow(Base):
    __tablename__ = 'sell_in_rows'
    
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=False)
    
    industria = Column(String(100))
    data = Column(String(20))
    cnpj = Column(String(20))
    razao_social = Column(String(255))
    id_supervisor = Column(String(50))
    supervisor = Column(String(100))
    id_vendedor = Column(String(50))
    vendedor = Column(String(100))
    uf = Column(String(2))
    ean = Column(String(50))
    material_desc = Column(String(255))
    unid_faturada = Column(Float, default=0.0)
    valor_fat = Column(Float, default=0.0)
    distribuidor = Column(String(100))
    ano = Column(Integer)
    rede = Column(String(100))
    cliente = Column(String(255))
    status_ol = Column(String(50))
    status_manual = Column(String(50))
    valor_ol = Column(Float, default=0.0)
    share_percent = Column(Float, default=0.0)
    mes = Column(String(20))
    
    client = relationship("Client", back_populates="sell_in_data")

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///C:/Users/negoc/.gemini/antigravity/scratch/powerbi_python/database.db")

if DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://"):
    import urllib.parse
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
    scheme, rest = DATABASE_URL.split("://", 1)
    if "@" in rest:
        creds, host_part = rest.rsplit("@", 1)
        user_part = creds.split(":", 1)[0] if ":" in creds else creds
        
        # Detectar hostname direto da Supabase (IPv6-only) e redirecionar para o Connection Pooler (IPv4)
        if ":" in creds:
            user, password = creds.split(":", 1)
            import re
            match = re.search(r"db\.([a-zA-Z0-9]+)\.supabase\.co", host_part)
            if match:
                project_ref = match.group(1)
                pooler_host = "aws-0-sa-east-1.pooler.supabase.com:6543"
                host_part = re.sub(r"db\.[a-zA-Z0-9]+\.supabase\.co(:\d+)?", pooler_host, host_part)
                if not user.endswith(f".{project_ref}"):
                    user = f"{user}.{project_ref}"
                user_part = user
            
            password_escaped = urllib.parse.quote_plus(password)
            DATABASE_URL = f"{scheme}://{user}:{password_escaped}@{host_part}"
            
        print(f"DEBUG DB: Connecting with scheme={scheme}, user={user_part}, host_part={host_part}")

def get_engine():
    if DATABASE_URL.startswith("sqlite"):
        os.makedirs(os.path.dirname(DATABASE_URL.replace("sqlite:///", "")), exist_ok=True)
        return create_engine(
            DATABASE_URL, 
            connect_args={"check_same_thread": False, "timeout": 60}
        )
    else:
        # Configurações ideais para PostgreSQL (Supabase) rodando em nuvem com pool de conexões robusto
        return create_engine(
            DATABASE_URL,
            pool_size=10,
            max_overflow=20,
            pool_recycle=300
        )

def init_db():
    engine = get_engine()
    Base.metadata.create_all(engine)
    
    # Criar sessão
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # Criar Admin do Sistema padrão se não existir
    admin = session.query(User).filter_by(username="admin").first()
    if not admin:
        hashed = hashlib.sha256("admin123".encode()).hexdigest()
        new_admin = User(
            username="admin",
            email="admin@lplmult.com.br",
            password_hash=hashed,
            permission="ADMINISTRADOR",
            is_system_admin=True,
            status="Ativo"
        )
        session.add(new_admin)
        session.commit()
    
    # Criar um Cliente de Teste "Amostra" para demonstração imediata
    amostra = session.query(Client).filter_by(slug="amostra").first()
    if not amostra:
        new_client = Client(
            name="Amostra",
            slug="amostra",
            status="Ativo",
            primary_color="#6366f1", # Violeta
            secondary_color="#f97316", # Laranja
            enabled_services="Sell Out,Sell In,OL,Campanhas",
            subscription_value=1500.0,
            subscription_due_day=10
        )
        session.add(new_client)
        session.commit()
        
        # Adicionar o usuário "Modelo" ao cliente "Amostra"
        hashed_modelo = hashlib.sha256("modelo123".encode()).hexdigest()
        new_user = User(
            client_id=new_client.id,
            username="Modelo",
            email="portalrepon@gmail.com",
            password_hash=hashed_modelo,
            permission="VISUALIZADOR",
            status="Ativo",
            is_system_admin=False
        )
        session.add(new_user)
        session.commit()
        
    session.close()

if __name__ == "__main__":
    init_db()
    print("Banco de dados reinicializado com esquema completo!")
