import pandas as pd
import random

# Lista de colunas obrigatórias
columns = [
    "INDUSTRIA", "DATA", "CNPJ", "RAZAO SOCIAL", "ID SUPERVISOR", "SUPERVISOR", 
    "ID VENDEDOR", "VENDEDOR", "UF", "EAN", "MATERIAL/DESC", "UNID. FATURADA", 
    "VALOR FAT.", "DISTRIBUIDOR", "ANO", "REDE", "CLIENTE", "STATUS OL", 
    "STATUS MANUAL", "VALOR OL", "SHARE %", "MES"
]

# Amostras de dados
industrias = ["Nestlé", "Unilever", "P&G", "Ambev"]
supervisores = ["Carlos Alberto", "Mariana Silva", "Roberto Souza"]
vendedores = ["João Lucas", "Fernanda Santos", "Pedro Rocha", "Aline Pereira"]
ufs = ["SP", "RJ", "MG", "PR", "SC", "RS"]
distribuidores = ["D1 Distribuidora", "Norte Sul Log", "Sul Vendas", "LPL Mult Distribuidor"]
meses = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio"]
produtos = [
    ("EAN001", "Chocolate Nestlé Classic 100g"),
    ("EAN002", "Detergente Omo Lavagem Perfeita 1L"),
    ("EAN003", "Shampoo Pantene Restauração 400ml"),
    ("EAN004", "Cerveja Corona Extra LN 355ml"),
    ("EAN005", "Biscoito Passatempo Recheado 130g"),
    ("EAN006", "Sabão em Pó Ariel 800g")
]
redes = ["Pão de Açúcar", "Carrefour", "Assaí", "Independente"]

data_rows = []

# Gerar 100 linhas de vendas teste
for i in range(150):
    prod_ean, prod_desc = random.choice(produtos)
    unid = random.randint(10, 500)
    val_unit = round(random.uniform(5.0, 45.0), 2)
    val_fat = round(unid * val_unit, 2)
    
    cnpj_random = f"{random.randint(10, 99)}.{random.randint(100, 999)}.{random.randint(100, 999)}/0001-{random.randint(10, 99)}"
    client_name = f"Supermercado {random.choice(['Estrela', 'União', 'Progresso', 'Barato'])}"
    
    row = {
        "INDUSTRIA": random.choice(industrias),
        "DATA": f"{random.randint(1, 28)}/05/2026",
        "CNPJ": cnpj_random,
        "RAZAO SOCIAL": f"{client_name} Ltda",
        "ID SUPERVISOR": f"SUP{random.randint(100, 199)}",
        "SUPERVISOR": random.choice(supervisores),
        "ID VENDEDOR": f"VEN{random.randint(100, 199)}",
        "VENDEDOR": random.choice(vendedores),
        "UF": random.choice(ufs),
        "EAN": prod_ean,
        "MATERIAL/DESC": prod_desc,
        "UNID. FATURADA": unid,
        "VALOR FAT.": val_fat,
        "DISTRIBUIDOR": random.choice(distribuidores),
        "ANO": 2026,
        "REDE": random.choice(redes),
        "CLIENTE": client_name,
        "STATUS OL": random.choice(["Faturado", "Pendente", "Cancelado"]),
        "STATUS MANUAL": "OK",
        "VALOR OL": round(val_fat * 0.95, 2),
        "SHARE %": round(random.uniform(1.5, 12.0), 2),
        "MES": random.choice(meses)
    }
    data_rows.append(row)

df = pd.DataFrame(data_rows)
df.to_excel("C:/Users/negoc/.gemini/antigravity/scratch/powerbi_python/test_sellout.xlsx", index=False)
print("Planilha teste 'test_sellout.xlsx' gerada com sucesso para testes de importação!")
