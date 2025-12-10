"""
app.py - Interface Web para Extrator de Notas Fiscais
=====================================================

USO:
    streamlit run app.py

REQUISITOS:
    pip install streamlit
"""

import streamlit as st
import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import os
import tempfile

import google.generativeai as genai
import PIL.Image

# Tentar importar suporte a PDF
try:
    from pdf2image import convert_from_path
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# Carregar variáveis de ambiente
load_dotenv()

# ============================================================================
# CONFIGURAÇÕES
# ============================================================================

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
MODEL_ID = "gemini-2.5-pro"

# Pastas de saída
OUTPUT_DIR = Path("invoices_json")
CSV_FILE = Path("invoices_data.csv")

# Extensões suportadas
IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']
PDF_EXTENSIONS = ['pdf'] if PDF_SUPPORT else []
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS + PDF_EXTENSIONS

# Prompt para extração
EXTRACTION_PROMPT = """Analise a imagem desta nota fiscal/cupom. 
Extraia os dados e retorne APENAS um objeto JSON válido seguindo esta estrutura, sem markdown e sem ```json```:

{
  "emitente": {
    "razao_social": "string",
    "cnpj": "string",
    "endereco": "string"
  },
  "data_emissao": "DD/MM/AAAA",
  "numero_nota": "string",
  "itens": [
    {
      "descricao": "string",
      "quantidade": float,
      "valor_unitario": float,
      "valor_total": float
    }
  ],
  "valor_total_nota": float,
  "impostos": {
    "icms": float,
    "iss": float
  }
}

REGRAS IMPORTANTES:
- Retorne APENAS o JSON, sem nenhum texto antes ou depois
- Se um campo estiver ilegível ou não existir, retorne null
- Não invente valores
- Use ponto como separador decimal (ex: 10.50)
- Mantenha a estrutura exata do JSON acima"""

# ============================================================================
# FUNÇÕES
# ============================================================================

@st.cache_resource
def setup_gemini():
    """Configura e retorna o modelo Gemini (cached)"""
    if not GEMINI_API_KEY:
        return None
    genai.configure(api_key=GEMINI_API_KEY)
    return genai.GenerativeModel(MODEL_ID)


def load_file(uploaded_file):
    """Carrega arquivo e retorna lista de imagens"""
    
    file_extension = uploaded_file.name.split('.')[-1].lower()
    
    # Se for imagem
    if file_extension in IMAGE_EXTENSIONS:
        img = PIL.Image.open(uploaded_file)
        return [img]
    
    # Se for PDF
    if file_extension in PDF_EXTENSIONS:
        # Salvar temporariamente para pdf2image processar
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name
        
        images = convert_from_path(tmp_path)
        os.unlink(tmp_path)  # Deletar arquivo temporário
        return images
    
    return None


def safe_get(data, *keys, default=""):
    """Acessa dados aninhados de forma segura"""
    value = data
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return default
        if value is None:
            return default
    return value if value is not None else default


def clean_value(value):
    """Limpa valor antes de salvar"""
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return value
    value = str(value).strip()
    value = value.replace("\n", " ").replace("\r", " ")
    while "  " in value:
        value = value.replace("  ", " ")
    return value


def extract_invoice_data(model, uploaded_file):
    """Extrai dados da nota fiscal"""
    
    images = load_file(uploaded_file)
    
    if images is None or len(images) == 0:
        return None, "Não foi possível carregar o arquivo"
    
    try:
        content = [EXTRACTION_PROMPT] + images
        response = model.generate_content(content)
        
        if not response.text:
            return None, "Resposta vazia do modelo"
        
        # Limpar resposta
        json_text = response.text.strip()
        json_text = json_text.replace("```json", "").replace("```", "").strip()
        
        # Parsear JSON
        invoice_data = json.loads(json_text)
        
        # Adicionar metadados
        file_extension = uploaded_file.name.split('.')[-1].lower()
        invoice_data["_metadata"] = {
            "arquivo_origem": uploaded_file.name,
            "tipo_arquivo": f".{file_extension}",
            "paginas": len(images),
            "data_extracao": datetime.now().isoformat(),
            "modelo": MODEL_ID
        }
        
        return invoice_data, None
        
    except json.JSONDecodeError as e:
        return None, f"Erro ao parsear JSON: {e}"
    except Exception as e:
        return None, f"Erro: {e}"


def save_json(invoice_data, file_name):
    """Salva JSON individual"""
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = Path(file_name).stem
    json_filename = OUTPUT_DIR / f"{base_name}_{timestamp}.json"
    
    with open(json_filename, 'w', encoding='utf-8') as f:
        json.dump(invoice_data, f, ensure_ascii=False, indent=2)
    
    return json_filename


def append_to_csv(invoice_data):
    """Acrescenta dados ao CSV"""
    
    file_exists = CSV_FILE.exists()
    
    fieldnames = [
        "data_extracao", "arquivo_origem", "tipo_arquivo",
        "razao_social", "cnpj", "endereco", "data_emissao",
        "numero_nota", "qtd_itens", "valor_total_nota", "icms", "iss"
    ]
    
    metadata = invoice_data.get("_metadata", {}) or {}
    itens = invoice_data.get("itens", []) or []
    
    row = {
        "data_extracao": clean_value(safe_get(metadata, "data_extracao")),
        "arquivo_origem": clean_value(safe_get(metadata, "arquivo_origem")),
        "tipo_arquivo": clean_value(safe_get(metadata, "tipo_arquivo")),
        "razao_social": clean_value(safe_get(invoice_data, "emitente", "razao_social")),
        "cnpj": clean_value(safe_get(invoice_data, "emitente", "cnpj")),
        "endereco": clean_value(safe_get(invoice_data, "emitente", "endereco")),
        "data_emissao": clean_value(safe_get(invoice_data, "data_emissao")),
        "numero_nota": clean_value(safe_get(invoice_data, "numero_nota")),
        "qtd_itens": len(itens),
        "valor_total_nota": clean_value(safe_get(invoice_data, "valor_total_nota")),
        "icms": clean_value(safe_get(invoice_data, "impostos", "icms")),
        "iss": clean_value(safe_get(invoice_data, "impostos", "iss"))
    }
    
    # Escrever no CSV
    import csv
    with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
    
    return row


# ============================================================================
# INTERFACE STREAMLIT
# ============================================================================

def main():
    # Configuração da página
    st.set_page_config(
        page_title="Extrator de Notas Fiscais",
        page_icon="🧾",
        layout="wide"
    )
    
    # Título
    st.title("🧾 Extrator de Notas Fiscais")
    st.markdown("*Powered by Gemini 2.5 Pro*")
    
    # Verificar API Key
    if not GEMINI_API_KEY:
        st.error("❌ GEMINI_API_KEY não encontrada no arquivo .env")
        st.stop()
    
    # Carregar modelo
    model = setup_gemini()
    if model is None:
        st.error("❌ Erro ao conectar com Gemini")
        st.stop()
    
    st.success("✅ Conectado ao Gemini 2.5 Pro")
    
    # Aviso sobre PDF
    if not PDF_SUPPORT:
        st.warning("⚠️ Suporte a PDF não disponível. Instale: `pip install pdf2image` e `brew install poppler`")
    
    st.divider()
    
    # Upload de arquivo
    st.subheader("📤 Upload da Nota Fiscal")
    
    uploaded_file = st.file_uploader(
        "Arraste sua nota fiscal aqui ou clique para selecionar",
        type=SUPPORTED_EXTENSIONS,
        help=f"Formatos suportados: {', '.join(SUPPORTED_EXTENSIONS)}"
    )
    
    # Processar arquivo
    if uploaded_file is not None:
        
        # Mostrar preview
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.subheader("📄 Arquivo")
            st.write(f"**Nome:** {uploaded_file.name}")
            st.write(f"**Tamanho:** {uploaded_file.size / 1024:.1f} KB")
            
            # Preview da imagem (se for imagem)
            if uploaded_file.name.split('.')[-1].lower() in IMAGE_EXTENSIONS:
                st.image(uploaded_file, width=300)
        
        with col2:
            st.subheader("⚙️ Processamento")
            
            if st.button("🚀 Extrair Dados", type="primary", use_container_width=True):
                
                with st.spinner("⏳ Processando com Gemini 2.5 Pro..."):
                    invoice_data, error = extract_invoice_data(model, uploaded_file)
                
                if error:
                    st.error(f"❌ {error}")
                else:
                    st.success("✅ Dados extraídos com sucesso!")
                    
                    # Salvar arquivos
                    json_path = save_json(invoice_data, uploaded_file.name)
                    csv_row = append_to_csv(invoice_data)
                    
                    # Guardar no session_state para mostrar abaixo
                    st.session_state['invoice_data'] = invoice_data
                    st.session_state['json_path'] = json_path
    
    # Mostrar resultados
    if 'invoice_data' in st.session_state:
        invoice_data = st.session_state['invoice_data']
        
        st.divider()
        st.subheader("📊 Dados Extraídos")
        
        # Cards com informações principais
        col1, col2, col3 = st.columns(3)
        
        emitente = invoice_data.get("emitente", {}) or {}
        
        with col1:
            st.metric("🏢 Empresa", emitente.get("razao_social", "N/A"))
        
        with col2:
            st.metric("📅 Data", invoice_data.get("data_emissao", "N/A"))
        
        with col3:
            valor = invoice_data.get("valor_total_nota", 0)
            st.metric("💰 Valor Total", f"R$ {valor}" if valor else "N/A")
        
        # Informações detalhadas
        with st.expander("📍 Dados do Emitente", expanded=True):
            st.write(f"**Razão Social:** {emitente.get('razao_social', 'N/A')}")
            st.write(f"**CNPJ:** {emitente.get('cnpj', 'N/A')}")
            st.write(f"**Endereço:** {emitente.get('endereco', 'N/A')}")
        
        # Tabela de itens
        itens = invoice_data.get("itens", []) or []
        if itens:
            with st.expander("📦 Itens da Nota", expanded=True):
                df_itens = pd.DataFrame(itens)
                st.dataframe(df_itens, use_container_width=True)
        
        # Impostos
        impostos = invoice_data.get("impostos", {}) or {}
        with st.expander("📋 Impostos"):
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**ICMS:** {impostos.get('icms', 'N/A')}")
            with col2:
                st.write(f"**ISS:** {impostos.get('iss', 'N/A')}")
        
        st.divider()
        
        # Botões de download
        st.subheader("📥 Downloads")
        
        col1, col2 = st.columns(2)
        
        with col1:
            json_str = json.dumps(invoice_data, ensure_ascii=False, indent=2)
            st.download_button(
                label="⬇️ Baixar JSON",
                data=json_str,
                file_name=f"nota_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                use_container_width=True
            )
        
        with col2:
            if CSV_FILE.exists():
                with open(CSV_FILE, 'r', encoding='utf-8') as f:
                    csv_data = f.read()
                st.download_button(
                    label="⬇️ Baixar CSV Consolidado",
                    data=csv_data,
                    file_name="invoices_data.csv",
                    mime="text/csv",
                    use_container_width=True
                )
    
    # Sidebar com histórico
    with st.sidebar:
        st.header("📚 Histórico")
        
        if CSV_FILE.exists():
            df = pd.read_csv(CSV_FILE)
            st.write(f"**Total de notas:** {len(df)}")
            
            if len(df) > 0:
                st.write(f"**Última extração:** {df['data_extracao'].iloc[-1][:10]}")
                
                # Mostrar últimas notas
                st.subheader("Últimas 5 notas")
                df_recent = df[['arquivo_origem', 'valor_total_nota']].tail(5)
                st.dataframe(df_recent, use_container_width=True)
        else:
            st.write("Nenhuma nota processada ainda.")
        
        st.divider()
        st.markdown("**Formatos suportados:**")
        st.markdown(f"`{', '.join(SUPPORTED_EXTENSIONS)}`")


# ============================================================================
# EXECUÇÃO
# ============================================================================

if __name__ == "__main__":
    main()