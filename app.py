import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, time, timedelta
import pytz
from fpdf import FPDF
import urllib.parse

# --- CONFIGURAÇÃO DE ACESSO COM CACHE DE ALTA PERFORMANCE ---
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

@st.cache_resource
def conectar_gsheets():
    info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=scope)
    return gspread.authorize(creds)

@st.cache_data(ttl=60) # Cache de 1 minuto para usuários
def buscar_usuarios_cadastrados():
    try:
        client = conectar_gsheets()
        sheet_u = client.open("ListaPresenca").worksheet("Usuarios")
        return sheet_u.get_all_records()
    except:
        return []

@st.cache_data(ttl=15) # Cache de 15 segundos para a lista de presença
def buscar_presenca_atualizada():
    try:
        client = conectar_gsheets()
        sheet_p = client.open("ListaPresenca").sheet1
        return sheet_p.get_all_values()
    except:
        return None

def conectar_escrita_direta():
    return conectar_gsheets().open("ListaPresenca")

def verificar_status_e_limpar(sheet_p, dados_p):
    fuso_br = pytz.timezone('America/Sao_Paulo')
    agora = datetime.now(fuso_br)
    hora_atual, dia_semana = agora.time(), agora.weekday()

    if hora_atual >= time(18, 50): marco = agora.replace(hour=18, minute=50, second=0, microsecond=0)
    elif hora_atual >= time(6, 50): marco = agora.replace(hour=6, minute=50, second=0, microsecond=0)
    else: marco = (agora - timedelta(days=1)).replace(hour=18, minute=50, second=0, microsecond=0)

    if dados_p and len(dados_p) > 1:
        try:
            ultima_str = dados_p[-1][0]
            ultima_dt = fuso_br.localize(datetime.strptime(ultima_str, '%d/%m/%Y %H:%M:%S'))
            if ultima_dt < marco:
                sheet_p.resize(rows=1)
                sheet_p.resize(rows=100)
                st.cache_data.clear()
                st.rerun()
        except: pass
    
    return (dia_semana == 6 and hora_atual >= time(19, 0)) or \
           (dia_semana in [0, 1, 2, 3] and (hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0) or hora_atual >= time(19, 0))) or \
           (dia_semana == 4 and time(7, 0) <= hora_atual <= time(17, 0))

def aplicar_ordenacao(df):
    if 'EMAIL' not in df.columns: df['EMAIL'] = "N/A"
    p_orig = {"QG": 1, "RMCF": 2, "OUTROS": 3}
    p_grad = {"TCEL": 1, "MAJ": 2, "CAP": 3, "1º TEN": 4, "2º TEN": 5, "SUBTEN": 6, 
              "1º SGT": 7, "2º SGT": 8, "3º SGT": 9, "CB": 10, "SD": 11, "FC COM": 101, "FC TER": 102}
    
    df['is_fc'] = df['GRADUAÇÃO'].apply(lambda x: 1 if "FC" in str(x) else 0)
    df['p_o'] = df['QG_RMCF_OUTROS'].map(p_orig).fillna(99)
    df['p_g'] = df['GRADUAÇÃO'].map(p_grad).fillna(999)
    df['dt'] = pd.to_datetime(df['DATA_HORA'], dayfirst=True, errors='coerce')
    
    df = df.sort_values(by=['is_fc', 'p_o', 'p_g', 'dt']).reset_index(drop=True)
    df.insert(0, 'Nº', [str(i+1) if i < 38 else f"Exc-{i-37:02d}" for i in range(len(df))])
    
    df_v = df.copy()
    for i, r in df_v.iterrows():
        if "Exc-" in str(r['Nº']):
            for c in df_v.columns: df_v.at[i, c] = f"<span style='color:#d32f2f; font-weight:bold;'>{r[c]}</span>"
    
    return df.drop(columns=['is_fc', 'p_o', 'p_g', 'dt']), df_v.drop(columns=['is_fc', 'p_o', 'p_g', 'dt'])

# --- INTERFACE ---
st.set_page_config(page_title="Rota Nova Iguaçu", layout="centered")

st.markdown("""<style>
    .titulo-container { text-align: center; width: 100%; }
    .titulo-responsivo { font-size: clamp(1.2rem, 5vw, 2.2rem); font-weight: bold; margin-bottom: 20px; }
    .stCheckbox { background-color: #f8f9fa; padding: 5px; border-radius: 4px; border: 1px solid #eee; }
    .footer { text-align: center; font-size: 11px; color: #888; margin-top: 40px; padding: 10px; border-top: 1px solid #eee; }
</style>""", unsafe_allow_html=True)

st.markdown('<div class="titulo-container"><div class="titulo-responsivo">🚌 ROTA NOVA IGUAÇU</div></div>', unsafe_allow_html=True)

if 'usuario_logado' not in st.session_state: st.session_state.usuario_logado = None
if 'conf_ativa' not in st.session_state: st.session_state.conf_ativa = False

try:
    records_u = buscar_usuarios_cadastrados()
    dados_p = buscar_presenca_atualizada()
    
    doc_escrita = conectar_escrita_direta()
    sheet_p_escrita = doc_escrita.sheet1

    if st.session_state.usuario_logado is None:
        t1, t2, t3 = st.tabs(["Login", "Cadastro", "Esqueci a Senha"])
        with t1:
            with st.form("form_login"):
                l_e = st.text_input("E-mail:")
                l_s = st.text_input("Senha:", type="password")
                if st.form_submit_button("ENTRAR", use_container_width=True):
                    u_a = next((u for u in records_u if str(u.get('Email','')).strip().lower() == l_e.strip().lower() and str(u.get('Senha','')) == str(l_s)), None)
                    if u_a: st.session_state.usuario_logado = u_a; st.rerun()
                    else: st.error("E-mail ou senha incorretos.")
        with t2:
            with st.form("form_novo_cadastro"):
                n_nome = st.text_input("Nome de Escala:")
                n_email = st.text_input("E-mail (Será seu Login):")
                n_grad = st.selectbox("Graduação:", ["TCEL", "MAJ", "CAP", "1º TEN", "2º TEN", "SUBTEN", "1º SGT", "2º SGT", "3º SGT", "CB", "SD", "FC COM", "FC TER"])
                n_lot = st.text_input("Lotação:")
                n_orig = st.selectbox("Origem Padrão:", ["QG", "RMCF", "OUTROS"])
                n_pass = st.text_input("Crie uma Senha:", type="password")
                if st.form_submit_button("FINALIZAR CADASTRO", use_container_width=True):
                    if any(str(u.get('Email','')).strip().lower() == n_email.strip().lower() for u in records_u):
                        st.error("E-mail já cadastrado.")
                    else:
                        doc_escrita.worksheet("Usuarios").append_row([n_nome, n_grad, n_lot, n_pass, n_orig, n_email])
                        st.cache_data.clear()
                        st.success("Cadastro realizado! Use a aba Login.")
        with t3:
            e_recup = st.text_input("Digite o e-mail cadastrado:")
            if st.button("RECUPERAR MEUS DADOS", use_container_width=True):
                u_r = next((u for u in records_u if str(u.get('Email', '')).strip().lower() == e_recup.strip().lower()), None)
                if u_r: st.info(f"Usuário: {u_r.get('Nome')} | Senha: {u_r.get('Senha')}")
                else: st.error("E-mail não encontrado.")
    else:
        u = st.session_state.usuario_logado
        st.sidebar.info(f"Conectado: {u.get('Graduação')} {u.get('Nome')}")
        if st.sidebar.button("Sair", use_container_width=True): st.session_state.usuario_logado = None; st.rerun()
        st.sidebar.markdown("---")
        st.sidebar.write("**MAJ ANDRÉ AGUIAR - CAES**")

        aberto = verificar_status_e_limpar(sheet_p_escrita, dados_p)
        df_o, df_v = pd.DataFrame(), pd.DataFrame()
        ja, pos = False, 999
        
        if dados_p and len(dados_p) > 1:
            df_o, df_v = aplicar_ordenacao(pd.DataFrame(dados_p[1:], columns=dados_p[0]))
            email_logado = str(u.get('Email')).strip().lower()
            ja = any(email_logado == str(row.get('EMAIL','')).strip().lower() for _, row in df_o.iterrows())
            if ja:
                try: pos = df_o.index[df_o['EMAIL'].str.lower() == email_logado].tolist()[0] + 1
                except: pass

        if aberto:
            if not ja:
                orig = u.get('ORIGEM') or u.get('QG_RMCF_OUTROS') or "QG"
                if st.button("🚀 SALVAR MINHA PRESENÇA", use_container_width=True):
                    agora = datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M:%S')
                    sheet_p_escrita.append_row([agora, orig, u.get('Graduação'), u.get('Nome'), u.get('Lotação'), u.get('Email')])
                    st.cache_data.clear(); st.rerun()
            else:
                st.success(f"✅ Presença registrada na posição: {pos}º")
                if st.button("❌ EXCLUIR MINHA ASSINATURA", use_container_width=True):
                    for idx, r in enumerate(dados_p):
                        if len(r) >= 6 and str(r[5]).strip().lower() == email_logado:
                            sheet_p_escrita.delete_rows(idx + 1)
                            st.cache_data.clear(); st.rerun()
        else: st.info("⌛ Lista fechada.")

        # Checklist de Embarque liberado para os TRÊS PRIMEIROS da lista
        if ja and pos <= 3:
            st.divider(); st.subheader("📋 CONFERÊNCIA DE EMBARQUE")
            if st.button("📝 ABRIR / FECHAR PAINEL", use_container_width=True):
                st.session_state.conf_ativa = not st.session_state.conf_ativa
            if st.session_state.conf_ativa:
                for i, row in df_o.iterrows():
                    st.checkbox(f"{row['Nº']} - {row.get('GRADUAÇÃO')} {row.get('NOME')}", key=f"chk_{i}_{row.get('EMAIL')}")
            st.divider()

        if dados_p and len(dados_p) > 1:
            st.subheader(f"Presentes ({len(df_o)})")
            if st.button("🔄 ATUALIZAR LISTA", use_container_width=True): st.cache_data.clear(); st.rerun()
            st.write(f'<div class="tabela-responsiva">{df_v.drop(columns=["EMAIL"]).to_html(index=False, justify="center", border=0, escape=False)}</div>', unsafe_allow_html=True)
            
            c1, c2 = st.columns(2)
            with c1:
                pdf = FPDF()
                pdf.add_page(); pdf.set_font("Arial", "B", 12)
                pdf.cell(190, 10, "LISTA DE PRESENÇA", ln=True, align="C")
                pdf.set_font("Arial", "B", 8)
                for h in ["Nº", "GRADUAÇÃO", "NOME", "LOTAÇÃO"]: pdf.cell(45, 8, h, border=1)
                st.download_button("📄 PDF", pdf.output(dest="S").encode("latin-1"), "lista.pdf", use_container_width=True)
            with c2:
                txt_w = f"*🚌 LISTA DE PRESENÇA*\n\n"
                for _, r in df_o.iterrows(): txt_w += f"{r['Nº']}. {r['GRADUAÇÃO']} {r['NOME']}\n"
                st.markdown(f'<a href="https://wa.me/?text={urllib.parse.quote(txt_w)}" target="_blank"><button style="width:100%; height:38px; background-color:#25D366; color:white; border:none; border-radius:4px; font-weight:bold;">🟢 WHATSAPP</button></a>', unsafe_allow_html=True)

    st.markdown(f'<div class="footer">Desenvolvido por: <b>MAJ ANDRÉ AGUIAR - CAES</b></div>', unsafe_allow_html=True)

except Exception as e:
    st.error(f"⚠️ Erro de conexão com o servidor. Aguarde 10 segundos. Detalhe: {e}")
