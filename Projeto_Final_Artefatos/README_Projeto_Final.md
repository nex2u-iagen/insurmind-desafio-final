# D&O Policy Intelligence

## Projeto Final — InsurMinds

MVP para receber, extrair, estruturar, consultar e comparar duas apólices de seguro D&O, apresentando diferenças com evidências por página.

> A aplicação é um protótipo acadêmico. A saída apoia a análise documental e não constitui parecer jurídico, subscrição ou decisão de cobertura.

## Integrantes

Preencher antes da entrega oficial:

| Nome | E-mail |>
|---|---|
| `[Adelson N. de Almeida]` | `[naortier@gmail.com]` |
| `[Daniel Correa Rodrigues]` | `[E-MAIL]` |
| `[NOME DO INTEGRANTE 3]` | `[E-MAIL]` |

Os placeholders existem porque os nomes dos integrantes não foram fornecidos nesta execução e não devem ser inventados.

## O que o projeto demonstra

| Requisito do Projeto Final | Evidência |
|---|---|
| Ler PDF ou imagem | `seguramente_final/ingest.py`, `pypdf`, OCR e upload Streamlit |
| Extrair conteúdo automaticamente | Provider offline determinístico e provider OpenAI-compatible |
| Estruturar informações | Schema com 19 campos, status, confiança, página e evidência |
| Armazenar dados | SQLite com documentos, páginas, fatos e comparações |
| Comparar duas apólices | `seguramente_final/compare.py` e tabela na interface |
| Apresentar diferenças | Resumo, busca, tabela lado a lado e evidências expansíveis |
| Utilizar IA Generativa | Extração JSON e resumo comparativo por modelo de linguagem |
| Interface demonstrável | `app.py` com Streamlit |

## Instalação

Requer Python 3.11 ou superior e Tesseract OCR. Em Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-por
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Configure `OPENAI_API_KEY` em `.env` para usar o provider de IA. O provider offline não requer chave e é usado nos testes e na demonstração reprodutível.

## Executar a interface

```bash
streamlit run app.py
```

Por padrão, a interface usa as duas apólices sintéticas autorais incluídas em `data/policies`. Para testar outros documentos, desmarque “Usar corpus sintético incluso” e faça upload de dois PDFs ou imagens.

## Gerar evidências pela linha de comando

Modo offline:

```bash
python3 scripts/run_demo.py --provider offline --output evidence/demo_analysis_offline.json
```

Modo com IA:

```bash
python3 scripts/run_demo.py --provider openai --output evidence/demo_analysis_openai.json
```

O ambiente de validação utilizou `gpt-5-mini`. O resultado registra documentos, páginas, fatos, diferenças, evidências, provider e modelo; não registra chaves.

## Testes

```bash
pytest -q
```

A suíte valida leitura de PDF, preservação de páginas, extração de campos, comparação, armazenamento SQLite, exigência de dois documentos e rejeição de formatos inválidos.

## Arquitetura

```text
PDF/imagem → ingestão → PDF nativo/OCR → texto por página
          → extração estruturada → validação de evidências
          → SQLite → consulta → comparação → interface
```

Os detalhes estão no [Relatório Técnico](docs/Relatorio_Tecnico_Projeto_Final.pdf). O diagrama fonte está em `docs/assets/architecture.mmd`.

## Corpus

`data/policies/Apolice_DO_A.pdf` e `Apolice_DO_B.pdf` são documentos sintéticos, autorais e redistribuíveis, criados para demonstrar diferenças de limites, franquias, território, coberturas, exclusões e condições. Eles não representam contratos de seguradoras reais.

A referência pública de domínio utilizada durante a modelagem foi a [Condições Gerais D&O da Berkley](https://www.berkley.com.br/wp-content/uploads/2022/03/CG_DEO.pdf). O texto incluído neste repositório não é uma cópia desse documento.

## Estrutura de entrega

```text
.
├── app.py
├── data/policies/                 # corpus sintético e SQLite local
├── docs/                          # relatório, Markdown e arquitetura
├── evidence/                      # JSONs e imagem de evidência
├── Projeto_Final_Artefatos/       # Pitch Deck, vídeo e auxiliares
├── seguramente_final/             # módulos do MVP
├── scripts/                       # geração de corpus e demonstração
├── tests/
├── LICENSE
├── README.md
└── requirements.txt
```

## Artefatos multimídia

A pasta `Projeto_Final_Artefatos` contém os arquivos exigidos pelo edital:

- `InsurMinds_Projeto_Final.pptx`;
- `InsurMinds_Projeto_Final.mp4`;
- `architecture.png` e `demo_analysis_openai.json` como auxiliares.

## Licença

MIT License. Consulte o arquivo `LICENSE`.
