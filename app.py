import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, time, timedelta
import pytz
from fpdf import FPDF

# --- CONFIGURAÇÃO DE ACESSO ---
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

def conectar():
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    client = gspread.authorize(creds)
    return client.open("ListaPresenca").sheet1

# --- LÓGICA DE HORÁRIO E LIMPEZA ---
def verificar_status():
    fuso_br = pytz.timezone('America/Sao_Paulo')
    agora = datetime.now(fuso_br)
    dia_semana = agora.weekday()
    hora_atual = agora.time()

    aberto = False
    # Janelas de abertura para limpeza (10 min antes)
    # Turno 07:00 -> Limpa entre 06:50 e 06:59
    # Turno 19:00 -> Limpa entre 18:50 e 18:59
    precisa_limpar = (time(6, 50) <= hora_atual <= time(6, 59)) or (time(18, 50) <= hora_atual <= time(18, 59))

    # Regras de Horário
    if dia_semana == 6: # Dom
        if hora_atual >= time(19, 0): aberto = True
    elif dia_semana in [0, 1, 2, 3]: # Seg a Qui
        if hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0) or hora_atual >= time(19, 0):
            aberto = True
    elif dia_semana == 4: # Sex
        if hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0):
            aberto = True
    elif dia_semana == 5: # Sab
        if hora_atual <= time(5, 0): aberto = True

    return aberto, precisa_limpar

# --- FUNÇÃO DE ORDENAÇÃO ---
def ordenar_dados(df):
    # Ordem de Destino
    ordem_destino = {"QG": 0, "RMCF": 1, "OUTROS": 2}
    
    # Ordem de Graduação (FCs ficam por último na hierarquia)
    ordem_grad = {
        "TCEL": 0, "MAJ": 1, "CAP": 2, "1º TEN": 3, "2º TEN": 4, 
        "SUBTEN": 5, "1º SGT": 6, "2º SGT": 7, "3º SGT": 8, "CB": 9, "SD": 10,
        "FC COM": 11, "FC TER": 12
    }
    
    # Criar colunas temporárias para ordenar
    df['peso_destino'] = df['DESTINO'].map(ordem_destino).fillna(3)
    df['peso_grad'] = df['GRAD.'].map(ordem_grad).fillna(13)
    # Converter data/hora para permitir ordenação cronológica
    df['dt_temp'] = pd.to_datetime(df['DATA/HORA'], dayfirst=True)
    
    # Ordenar: 1º Destino, 2º Graduação, 3º Data/Hora
    df = df.sort_values(by=['peso_destino', 'peso_grad', 'dt_temp']).reset_index(drop=True)
    
    return df.drop(columns=['peso_destino', 'peso_grad', 'dt_temp'])

# --- TÍTULO ---
st.markdown("<h1 style='text-align: center;'>🚌 ROTA NOVA IGUAÇU</h1>", unsafe_allow_html=True)

try:
    sheet = conectar()
    esta_aberto, deve_limpar = verificar_status()

    # Executa limpeza se estiver no horário (06:50 ou 18:50)
    if deve_limpar:
        # Pega todos os dados; se tiver mais que o cabeçalho, apaga.
        if len(sheet.get_all_values()) > 1:
            sheet.resize(rows=1)
            sheet.resize(rows=100) # Mantém espaço para novos dados
            st.info("🧹 Sistema em manutenção: Limpando lista para o novo turno...")

    if esta_aberto:
        with st.form("meu_formulario", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                qg_opcoes = st.selectbox("Destino:", ["QG", "RMCF", "OUTROS"])
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
                    fuso_br = pytz.timezone('America/Sao_Paulo')
                    agora_str = datetime.now(fuso_br).strftime('%d/%m/%Y %H:%M:%S')
                    sheet.append_row([agora_str, qg_opcoes, graduacao, nome, lotacao])
                    st.success(f"Presença de {nome} registrada!")
                    st.rerun()
                else:
                    st.error("Por favor, preencha o Nome e a Lotação.")
    else:
        st.warning("⚠️ O formulário está fechado. Apenas consulta disponível.")

    # --- TABELA E PDF ---
    st.subheader("Pessoas Presentes")
    dados = sheet.get_all_values()
    if len(dados) > 1:
        df = pd.DataFrame(dados[1:], columns=dados[0])
        # Aplicar a ordenação solicitada
        df_ordenado = ordenar_dados(df)
        st.table(df_ordenado)
        
        # Função para PDF (Interna para garantir dados ordenados)
        def gerar_pdf_ordenado(df_pdf):
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", "B", 14)
            pdf.cell(190, 10, "LISTA DE PRESENÇA - ROTA NOVA IGUAÇU", ln=True, align="C")
            pdf.ln(5)
            pdf.set_font("Arial", "B", 8)
            col_w = [35, 20, 20, 70, 45]
            headers = ["DATA/HORA", "DESTINO", "GRAD.", "NOME", "LOTAÇÃO"]
            for i, h in enumerate(headers): pdf.cell(col_w[i], 8, h, border=1, align="C")
            pdf.ln()
            pdf.set_font("Arial", "", 8)
            for _, row in df_pdf.iterrows():
                for i in range(5): pdf.cell(col_w[i], 8, str(row[i]), border=1)
                pdf.ln()
            return pdf.output(dest="S").encode("latin-1")

        pdf_bytes = gerar_pdf_ordenado(df_ordenado)
        st.download_button("📄 BAIXAR LISTA EM PDF", pdf_bytes, f"presenca_{datetime.now().strftime('%d_%m_%Hh')}.pdf", "application/pdf")
    else:
        st.info("Nenhuma presença registrada ainda.")

except Exception as e:
    st.error(f"Erro: {e}")
