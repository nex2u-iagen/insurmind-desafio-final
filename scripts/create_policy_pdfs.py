"""Gera duas apólices D&O sintéticas para demonstração e testes."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "policies"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
if Path(FONT).exists():
    pdfmetrics.registerFont(TTFont("DejaVu", FONT))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", FONT_BOLD))
    BASE = "DejaVu"
    BOLD = "DejaVu-Bold"
else:
    BASE = "Helvetica"
    BOLD = "Helvetica-Bold"

styles = getSampleStyleSheet()
styles.add(
    ParagraphStyle(name="BodyPT", parent=styles["BodyText"], fontName=BASE, fontSize=9.5, leading=13, spaceAfter=6)
)
styles.add(
    ParagraphStyle(
        name="HeadingPT",
        parent=styles["Heading2"],
        fontName=BOLD,
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#17324d"),
        spaceBefore=6,
        spaceAfter=8,
    )
)
styles.add(
    ParagraphStyle(
        name="TitlePT",
        parent=styles["Title"],
        fontName=BOLD,
        fontSize=20,
        leading=24,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#17324d"),
    )
)
styles.add(
    ParagraphStyle(
        name="SmallPT",
        parent=styles["BodyText"],
        fontName=BASE,
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#4b5563"),
    )
)


def p(text: str, style: str = "BodyPT") -> Paragraph:
    return Paragraph(text, styles[style])


def make_policy(
    filename: str,
    insurer: str,
    limit: str,
    aggregate: str,
    deductible: str,
    territory: str,
    defense: str,
    extended: str,
    control: str,
    pollution: str,
    entity: str,
    retroactive: str,
) -> None:
    path = OUT / filename
    doc = SimpleDocTemplate(
        str(path), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm
    )
    story = []
    story += [
        Spacer(1, 24 * mm),
        p("APÓLICE D&O", "TitlePT"),
        Spacer(1, 8 * mm),
        p("Documento sintético autoral para demonstração acadêmica", "SmallPT"),
        Spacer(1, 12 * mm),
    ]
    cover_table = Table(
        [
            [p("SEGURADORA", "SmallPT"), p(insurer, "BodyPT")],
            [p("PRODUTO", "SmallPT"), p("Seguro de Responsabilidade Civil de Diretores e Administradores", "BodyPT")],
            [p("VIGÊNCIA", "SmallPT"), p("01/01/2026 a 31/12/2026", "BodyPT")],
            [p("FONTE", "SmallPT"), p("Documento sintético autoral — uso didático", "BodyPT")],
        ],
        colWidths=[42 * mm, 125 * mm],
    )
    cover_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef2f7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story += [
        cover_table,
        Spacer(1, 18 * mm),
        p(
            "Este documento foi criado exclusivamente para demonstração do Projeto Final InsurMinds. Não representa uma oferta, contrato ou produto comercial real.",
            "BodyPT",
        ),
        PageBreak(),
    ]

    story += [p("1. Identificação, vigência e limites", "HeadingPT")]
    story += [
        p(f"SEGURADORA: {insurer}"),
        p("VIGÊNCIA: 01/01/2026 a 31/12/2026"),
        p(f"ÂMBITO GEOGRÁFICO: {territory}"),
        p(f"LIMITE MÁXIMO DE RESPONSABILIDADE: {limit}"),
        p(f"LIMITE AGREGADO: {aggregate}"),
        p(f"FRANQUIA / RETENÇÃO: {deductible}"),
        p(f"ATOS ANTERIORES / DATA RETROATIVA: {retroactive}"),
    ]
    story += [
        p("2. Coberturas básicas", "HeadingPT"),
        p(
            "COBERTURA A — INDENIZAÇÃO AO SEGURADO: garante o pagamento de perdas indenizáveis sofridas por pessoa segurada quando a sociedade não puder ou não dever indenizar, observados os termos desta apólice."
        ),
        p(
            "COBERTURA B — REEMBOLSO À SOCIEDADE: reembolsa a sociedade pelos valores pagos para indenizar pessoa segurada em razão de reclamação coberta."
        ),
        p(f"COBERTURA C — ENTIDADE: {entity}"),
        p(f"CUSTOS DE DEFESA: {defense}"),
    ]
    story += [
        p("3. Extensões", "HeadingPT"),
        p(
            "CUSTOS DE INVESTIGAÇÃO: despesas razoáveis de investigação podem ser cobertas quando relacionadas a procedimento formal contra pessoa segurada."
        ),
        p(
            "NOVAS SUBSIDIÁRIAS: cobertura para subsidiárias adquiridas durante a vigência, sujeita às condições da apólice."
        ),
        p(f"PERÍODO ADICIONAL DE NOTIFICAÇÃO: {extended}"),
    ]
    bodily_exclusion = (
        "excluídos, salvo extensão expressa" if "A" in filename else "excluídos, salvo cobertura adicional"
    )
    story += [
        PageBreak(),
        p("4. Riscos excluídos", "HeadingPT"),
        p(
            "FRAUDE OU DOLO: excluem-se perdas decorrentes de ato doloso, fraudulento ou de vantagem pessoal ilícita comprovado por decisão final."
        ),
        p(f"DANOS CORPORAIS OU MATERIAIS: {bodily_exclusion}."),
        p(f"POLUIÇÃO: {pollution}."),
        p(
            "RECLAMAÇÕES PRÉVIAS: não estão cobertas reclamações ou circunstâncias conhecidas antes da data de retroatividade."
        ),
        p(
            "MULTAS E PENALIDADES: somente quando legalmente seguráveis e expressamente previstas nas condições particulares."
        ),
        p("GUERRA E CONTAMINAÇÃO: excluídas conforme a legislação aplicável e os termos desta apólice."),
        p("5. Condições de operação", "HeadingPT"),
        p(
            "NOTIFICAÇÃO DE RECLAMAÇÕES: o segurado deve comunicar a reclamação por escrito tão logo seja razoavelmente possível, observados os canais indicados na apólice."
        ),
        p(f"MUDANÇA DE CONTROLE: {control}"),
        p(
            "ACORDOS E CONSENTIMENTO: nenhum acordo ou admissão de responsabilidade deve ser realizado sem consentimento prévio, salvo disposição expressa."
        ),
        p("COOPERAÇÃO: o segurado deve cooperar com a investigação e defesa da reclamação."),
        p("6. Limitações e observação", "HeadingPT"),
        p(
            "Este documento sintético possui finalidade exclusivamente acadêmica. A interpretação de coberturas, exclusões e limites deve considerar o texto integral e não substitui análise jurídica ou securitária."
        ),
        Spacer(1, 10 * mm),
        p(f"Identificador da versão: {filename}", "SmallPT"),
    ]
    doc.build(story)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    make_policy(
        "Apolice_DO_A.pdf",
        "SeguraMente Seguros S.A. — Documento Sintético A",
        "R$ 10.000.000,00",
        "R$ 10.000.000,00",
        "R$ 50.000,00 por reclamação",
        "Mundial, excluídos Estados Unidos e Canadá",
        "dentro do limite máximo de responsabilidade",
        "24 meses, mediante prêmio adicional",
        "a cobertura continua para reclamações relativas a atos anteriores, sujeita à notificação",
        "excluída, salvo extensão expressa",
        "não incluída",
        "01/01/2023",
    )
    make_policy(
        "Apolice_DO_B.pdf",
        "SeguraMente Seguros S.A. — Documento Sintético B",
        "R$ 15.000.000,00",
        "R$ 15.000.000,00",
        "R$ 100.000,00 por reclamação",
        "Mundial, incluindo Estados Unidos e Canadá",
        "fora do limite máximo de responsabilidade, até o sublimite indicado",
        "36 meses, sem prêmio adicional em caso de encerramento",
        "a cobertura termina para atos posteriores à data efetiva da mudança de controle",
        "coberta somente quando decorrente de reclamação de terceiros",
        "incluída até o sublimite de R$ 2.000.000,00",
        "01/01/2024",
    )
    print("Documentos gerados em", OUT)
