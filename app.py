import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime

# --- CONFIGURAÇÃO DE ACESSO ---
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

def conectar():
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    client = gspread.authorize(creds)
    return client.open("ListaPresenca").sheet1

# --- TÍTULO ---
st.markdown("<h1 style='text-align: center;'>🚌 ROTA NOVA IGUAÇU</h1>", unsafe_allow_html=True)

try:
    sheet = conectar()
    
    # --- FORMULÁRIO ---
    with st.form("meu_formulario", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            qg_opcoes = st.selectbox("Destino:", ["QG", "RMCF", "OUTROS"])
            # LISTA EXATA CONFORME SUA DEFINIÇÃO
            graduacao = st.selectbox("Graduação:", [
                "TCEL", "MAJ", "CAP", "1º TEN", "2º TEN", 
                "SUBTEN", "1º SGT", "2º SGT", "3º SGT", "CB", "SD", "FC COM", "FC TER"
            ])
        
        with col2:
            nome = st.text_input("Nome de Escala:")
            lotacao = st.text_input("Lotação (Unidade):")
            
        submit = st.form_submit_button("SALVAR PRESENÇA")
        
        if submit:
            if nome and lotacao:
                agora = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                # Salva os dados na planilha
                sheet.append_row([agora, qg_opcoes, graduacao, nome, lotacao])
                st.success(f"Presença de {nome} registrada!")
                st.rerun()
            else:
                st.error("Por favor, preencha o Nome e a Lotação.")

    # --- MOSTRAR TABELA ---
    st.subheader("Pessoas Presentes")
    dados = sheet.get_all_values()
    if len(dados) > 1:
        df = pd.DataFrame(dados[1:], columns=dados[0])
        st.table(df)
    else:
        st.info("Nenhuma presença registrada ainda.")

except Exception as e:
    st.error(f"Erro: {e}")
