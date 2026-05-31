import pandas as pd
import math
from models import get_engine, SellOutRow, SellInRow, UploadHistory
from sqlalchemy.orm import sessionmaker

def parse_excel_and_import(client_id, filepath, data_type, original_filename):
    """
    Importa um arquivo Excel para o banco de dados para um determinado cliente.
    Exclui dados antigos do mesmo tipo para este cliente antes de inserir para evitar misturas.
    """
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # Detectar tipo de arquivo e ler adequadamente
        ext = original_filename.lower().split('.')[-1]
        if ext == 'csv':
            try:
                df = pd.read_csv(filepath, sep=';', encoding='utf-8')
            except UnicodeDecodeError:
                df = pd.read_csv(filepath, sep=';', encoding='latin1')
        else:
            df = pd.read_excel(filepath, engine='openpyxl')
        
        # Normalizar colunas do dataframe para caixa alta para corresponder com o anexo 1
        df.columns = [str(col).strip().upper() for col in df.columns]
        
        # Mapeamento de colunas com base no Anexo 1
        # Colunas esperadas: INDUSTRIA, DATA, CNPJ, RAZAO SOCIAL, ID SUPERVISOR, SUPERVISOR, 
        # ID VENDEDOR, VENDEDOR, UF, EAN, MATERIAL/DESC, UNID. FATURADA, VALOR FAT., DISTRIBUIDOR, 
        # ANO, REDE, CLIENTE, STATUS OL, STATUS MANUAL, VALOR OL, SHARE %, MES
        
        # Limpar registros antigos deste cliente para evitar duplicidade ou mistura
        if data_type == "Sell Out":
            session.query(SellOutRow).filter_by(client_id=client_id).delete()
        else:
            session.query(SellInRow).filter_by(client_id=client_id).delete()
            
        rows_to_insert = []
        count = 0
        
        for idx, row in df.iterrows():
            # Função auxiliar para pegar valor com segurança prevenindo NaN/NaT
            def val(col_name, default=None, is_num=False):
                if col_name not in df.columns:
                    return default
                val_raw = row[col_name]
                if pd.isna(val_raw):
                    return default
                if is_num:
                    try:
                        return float(val_raw) if '.' in str(val_raw) or 'e' in str(val_raw).lower() else int(val_raw)
                    except ValueError:
                        return default
                return str(val_raw).strip()
            
            # Formatação de campos específicos
            val_fat = val("VALOR FAT.", 0.0, is_num=True)
            unid_fat = val("UNID. FATURADA", 0.0, is_num=True)
            
            # Se for zero ou vazio faturamento, recalcular ticket médio se houver
            ticket = 0.0
            if val_fat and unid_fat and unid_fat > 0:
                ticket = val_fat / unid_fat
                
            share = val("SHARE %", 0.0, is_num=True)
            val_ol = val("VALOR OL", 0.0, is_num=True)
            ano_val = val("ANO", None, is_num=True)
            if ano_val is not None:
                ano_val = int(ano_val)
                
            row_data = {
                "client_id": client_id,
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
            
            if data_type == "Sell Out":
                db_row = SellOutRow(**row_data)
            else:
                db_row = SellInRow(**row_data)
                
            rows_to_insert.append(db_row)
            count += 1
            
            # Batch inserts a cada 5000 linhas para performance
            if len(rows_to_insert) >= 5000:
                session.bulk_save_objects(rows_to_insert)
                rows_to_insert = []
                
        if rows_to_insert:
            session.bulk_save_objects(rows_to_insert)
            
        # Registrar o histórico do upload
        history = UploadHistory(
            client_id=client_id,
            filename=original_filename,
            data_type=data_type,
            num_rows=count,
            status="Concluído"
        )
        session.add(history)
        session.commit()
        return True, count
    except Exception as e:
        session.rollback()
        # Registrar falha no histórico se possível
        try:
            history = UploadHistory(
                client_id=client_id,
                filename=original_filename,
                data_type=data_type,
                num_rows=0,
                status="Erro"
            )
            session.add(history)
            session.commit()
        except:
            pass
        return False, str(e)
    finally:
        session.close()
