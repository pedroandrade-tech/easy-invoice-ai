"""
invoice_extractor.py - Extrator de Notas Fiscais com Gemini 2.5 Pro
===================================================================

O QUE FAZ:
- Recebe uma imagem OU PDF de nota fiscal/cupom
- Usa Gemini 2.5 Pro para extrair os dados
- Salva os dados em JSON individual
- Acrescenta os dados em um CSV consolidado

FORMATOS SUPORTADOS:
- Imagens: jpg, jpeg, png, webp
- Documentos: pdf

USO:
python invoice_extractor.py <caminho_do_arquivo>
python invoice_extractor.py nota1.jpg
python invoice_extractor.py nota_fiscal.pdf
python invoice_extractor.py /pasta/notas/*.pdf

SAÍDA:
- invoices_json/nota_<timestamp>.json  (dados individuais)
- invoices_data.csv                     (consolidado)
"""

import os
import sys
import json
import csv
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

import google.generativeai as genai
import PIL.Image

# ============================================================================
# MUDANÇA 1: Importar biblioteca para PDF
# ============================================================================
# pdf2image converte páginas do PDF em imagens
# Isso é necessário porque o Gemini recebe imagens, não PDFs diretamente

try:
    from pdf2image import convert_from_path
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    print("⚠️  pdf2image não instalado. PDFs não serão suportados.")
    print("   Instale com: pip install pdf2image")
    print("   No Mac, também precisa: brew install poppler\n")

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

# ============================================================================
# MUDANÇA 2: Lista de extensões suportadas
# ============================================================================
# Separamos imagens e PDFs para tratar cada um de forma diferente

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
PDF_EXTENSIONS = {'.pdf'}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | PDF_EXTENSIONS  # União dos dois sets

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

def setup_gemini():
    """Configura e retorna o modelo Gemini"""
    
    if not GEMINI_API_KEY:
        print("❌ ERRO: GEMINI_API_KEY não encontrada no .env")
        sys.exit(1)
    
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(MODEL_ID)
    
    return model


# ============================================================================
# MUDANÇA 3: Nova função para carregar arquivo (imagem OU PDF)
# ============================================================================
def load_file(file_path):
    """
    Carrega um arquivo e retorna como imagem(ns)
    
    PARÂMETROS:
    -----------
    file_path : Path
        Caminho para o arquivo (imagem ou PDF)
    
    RETORNA:
    --------
    list : Lista de imagens PIL (1 para imagem, N para PDF com N páginas)
    """
    
    file_path = Path(file_path)
    extension = file_path.suffix.lower()
    
    # Verificar se extensão é suportada
    if extension not in SUPPORTED_EXTENSIONS:
        print(f"❌ ERRO: Extensão '{extension}' não suportada")
        print(f"   Suportados: {', '.join(SUPPORTED_EXTENSIONS)}")
        return None
    
    # Se for imagem: carrega direto
    if extension in IMAGE_EXTENSIONS:
        img = PIL.Image.open(file_path)
        return [img]  # Retorna lista com 1 imagem
    
    # Se for PDF: converte para imagens
    if extension in PDF_EXTENSIONS:
        if not PDF_SUPPORT:
            print("❌ ERRO: pdf2image não instalado")
            return None
        
        print(f"📄 Convertendo PDF para imagem...")
        
        # convert_from_path retorna lista de imagens (1 por página)
        images = convert_from_path(file_path)
        
        print(f"   → {len(images)} página(s) encontrada(s)")
        
        return images
    
    return None


# ============================================================================
# MUDANÇA 4: Função extract_invoice_data modificada
# ============================================================================
def extract_invoice_data(model, file_path):
    """
    Extrai dados da nota fiscal usando Gemini
    
    PARÂMETROS:
    -----------
    model : GenerativeModel
        Modelo Gemini configurado
    file_path : str ou Path
        Caminho para o arquivo (imagem ou PDF)
    
    RETORNA:
    --------
    dict : Dados extraídos da nota fiscal
    """
    
    file_path = Path(file_path)
    
    if not file_path.exists():
        print(f"❌ ERRO: Arquivo não encontrado: {file_path}")
        return None
    
    print(f"\n📄 Processando: {file_path.name}")
    
    # MUDANÇA: Usar nova função para carregar
    images = load_file(file_path)
    
    if images is None or len(images) == 0:
        print("❌ ERRO: Não foi possível carregar o arquivo")
        return None
    
    print("⏳ Enviando para Gemini 2.5 Pro...")
    
    try:
        # MUDANÇA: Se tiver múltiplas páginas, envia todas
        # O Gemini aceita múltiplas imagens no mesmo request
        content = [EXTRACTION_PROMPT] + images
        
        response = model.generate_content(content)
        
        if not response.text:
            print("❌ ERRO: Resposta vazia do modelo")
            return None
        
        # Limpar resposta (remover possíveis marcadores markdown)
        json_text = response.text.strip()
        json_text = json_text.replace("```json", "").replace("```", "").strip()
        
        # Parsear JSON
        invoice_data = json.loads(json_text)
        
        # Adicionar metadados
        invoice_data["_metadata"] = {
            "arquivo_origem": file_path.name,
            "tipo_arquivo": file_path.suffix.lower(),  # MUDANÇA: Salvar tipo
            "paginas": len(images),  # MUDANÇA: Salvar qtd páginas
            "data_extracao": datetime.now().isoformat(),
            "modelo": MODEL_ID
        }
        
        print("✅ Dados extraídos com sucesso!")
        
        return invoice_data
        
    except json.JSONDecodeError as e:
        print(f"❌ ERRO: Falha ao parsear JSON: {e}")
        print(f"   Resposta recebida: {response.text[:200]}...")
        return None
    except Exception as e:
        print(f"❌ ERRO: {e}")
        return None


def save_json(invoice_data, file_name):
    """Salva os dados em arquivo JSON individual"""
    
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    # Nome do arquivo baseado no timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = Path(file_name).stem
    json_filename = OUTPUT_DIR / f"{base_name}_{timestamp}.json"
    
    with open(json_filename, 'w', encoding='utf-8') as f:
        json.dump(invoice_data, f, ensure_ascii=False, indent=2)
    
    print(f"💾 JSON salvo: {json_filename}")
    
    return json_filename


def append_to_csv(invoice_data):
    """Acrescenta os dados ao CSV consolidado"""
    
    # Verificar se CSV existe para saber se precisa de header
    file_exists = CSV_FILE.exists()
    
    # Extrair dados para o CSV (formato flat)
    emitente = invoice_data.get("emitente", {}) or {}
    impostos = invoice_data.get("impostos", {}) or {}
    metadata = invoice_data.get("_metadata", {})
    
    # Calcular total de itens
    itens = invoice_data.get("itens", []) or []
    qtd_itens = len(itens)
    
    # Linha do CSV
    row = {
        "data_extracao": metadata.get("data_extracao", ""),
        "arquivo_origem": metadata.get("arquivo_origem", ""),
        "tipo_arquivo": metadata.get("tipo_arquivo", ""),  # MUDANÇA: Nova coluna
        "razao_social": emitente.get("razao_social", ""),
        "cnpj": emitente.get("cnpj", ""),
        "endereco": emitente.get("endereco", ""),
        "data_emissao": invoice_data.get("data_emissao", ""),
        "numero_nota": invoice_data.get("numero_nota", ""),
        "qtd_itens": qtd_itens,
        "valor_total_nota": invoice_data.get("valor_total_nota", ""),
        "icms": impostos.get("icms", ""),
        "iss": impostos.get("iss", "")
    }
    
    # Escrever no CSV
    with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        
        if not file_exists:
            writer.writeheader()
        
        writer.writerow(row)
    
    print(f"📊 CSV atualizado: {CSV_FILE}")


def print_summary(invoice_data):
    """Exibe resumo dos dados extraídos"""
    
    print("\n" + "=" * 60)
    print(" " * 15 + "RESUMO DA NOTA FISCAL")
    print("=" * 60)
    
    emitente = invoice_data.get("emitente", {}) or {}
    metadata = invoice_data.get("_metadata", {})
    
    # MUDANÇA: Mostrar tipo de arquivo
    print(f"\n📁 ARQUIVO: {metadata.get('arquivo_origem', 'N/A')} ({metadata.get('tipo_arquivo', 'N/A')})")
    if metadata.get('paginas', 1) > 1:
        print(f"   Páginas processadas: {metadata.get('paginas')}")
    
    print(f"\n📍 EMITENTE:")
    print(f"   Razão Social: {emitente.get('razao_social', 'N/A')}")
    print(f"   CNPJ: {emitente.get('cnpj', 'N/A')}")
    
    print(f"\n📅 DATA: {invoice_data.get('data_emissao', 'N/A')}")
    print(f"🔢 NÚMERO: {invoice_data.get('numero_nota', 'N/A')}")
    
    itens = invoice_data.get("itens", []) or []
    print(f"\n📦 ITENS ({len(itens)}):")
    for i, item in enumerate(itens, 1):
        desc = item.get('descricao', 'N/A')
        qtd = item.get('quantidade', 0)
        total = item.get('valor_total', 0)
        print(f"   {i}. {desc} | Qtd: {qtd} | Total: R$ {total}")
    
    print(f"\n💰 VALOR TOTAL: R$ {invoice_data.get('valor_total_nota', 'N/A')}")
    
    impostos = invoice_data.get("impostos", {}) or {}
    print(f"\n📋 IMPOSTOS:")
    print(f"   ICMS: {impostos.get('icms', 'N/A')}")
    print(f"   ISS: {impostos.get('iss', 'N/A')}")
    
    print("\n" + "=" * 60)


def main():
    """Função principal"""
    
    print("\n" + "🧾 " * 20)
    print(" " * 10 + "EXTRATOR DE NOTAS FISCAIS")
    print(" " * 15 + "Gemini 2.5 Pro")
    print("🧾 " * 20)
    
    # MUDANÇA: Mostrar formatos suportados
    print(f"\n📁 Formatos suportados: {', '.join(SUPPORTED_EXTENSIONS)}")
    
    # Verificar argumentos
    if len(sys.argv) < 2:
        print("\n❌ USO: python invoice_extractor.py <caminho_do_arquivo>")
        print("\n   Exemplos:")
        print("   python invoice_extractor.py nota.jpg")
        print("   python invoice_extractor.py nota_fiscal.pdf")
        print("   python invoice_extractor.py /pasta/*.pdf")
        sys.exit(1)
    
    # Configurar modelo
    print("\n🔌 Conectando ao Gemini 2.5 Pro...")
    model = setup_gemini()
    print("✅ Modelo conectado!")
    
    # Processar cada arquivo
    file_paths = sys.argv[1:]
    
    for file_path in file_paths:
        # Extrair dados
        invoice_data = extract_invoice_data(model, file_path)
        
        if invoice_data:
            # Exibir resumo
            print_summary(invoice_data)
            
            # Salvar JSON individual
            save_json(invoice_data, file_path)
            
            # Acrescentar ao CSV
            append_to_csv(invoice_data)
    
    # Resumo final
    print("\n" + "=" * 60)
    print("✅ PROCESSAMENTO CONCLUÍDO!")
    print("=" * 60)
    print(f"\n📁 Arquivos gerados:")
    print(f"   • JSONs individuais: {OUTPUT_DIR}/")
    print(f"   • CSV consolidado: {CSV_FILE}")
    print("\n" + "=" * 60)


# ============================================================================
# EXECUÇÃO
# ============================================================================

if __name__ == "__main__":
    main()