import html
import re
from pathlib import Path

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from agentie.core.artifact_naming import artifact_filename,creator_from_session
from agentie.core.document_design import choose_style, document_title, first_numeric_series, parse_blocks
from agentie.core.file_service import UPLOADS, inspect_file, unique_path
from agentie.core.memory_store import latest_assistant_text

_PDF_INTENT_RE=re.compile(r"\b(?:create|make|generate|export|save|turn|convert)\b.*\bpdf\b|\bpdf\b.*\b(?:create|make|generate|export|save|turn|convert)\b",re.I)
_REFERENCE_RE=re.compile(r"\b(?:this|that|it|the previous answer|previous answer|last answer|above|what you just wrote|what you wrote)\b",re.I)

def _clean_filename(name:str|None,creator:str="Agentie")->str:return artifact_filename(creator,name,'.pdf','report')
def _extract_filename(message:str)->str|None:
    m=re.search(r"\b(?:called|named|as)\s+[\"']?([^\"']+?\.pdf)\b",message,re.I);return m.group(1).strip() if m else None
def _explicit_content(message:str)->str|None:
    m=re.search(r"\b(?:with|using|from)\s+(?:the\s+)?(?:text|content)\s*[:\-]?\s*(.+)$",message,re.I|re.S)
    if not m:return None
    value=m.group(1).strip();return value.strip(" \"'") if value and not _REFERENCE_RE.fullmatch(value.strip(" .?!\"'")) else None
def _markdown_inline(text:str)->str:
    value=html.escape(text);value=re.sub(r"\*\*(.+?)\*\*",r"<b>\1</b>",value);value=re.sub(r"__(.+?)__",r"<b>\1</b>",value);value=re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)",r"<i>\1</i>",value);value=re.sub(r"`([^`]+)`",r"<font name='Courier'>\1</font>",value);return value
def _c(hexv:str):return colors.HexColor('#'+hexv)

def _chart(labels,values,title,accent):
    d=Drawing(470,230);chart=VerticalBarChart();chart.x=50;chart.y=45;chart.height=135;chart.width=385;chart.data=[values];chart.categoryAxis.categoryNames=labels;chart.categoryAxis.labels.fontSize=7;chart.valueAxis.labels.fontSize=7;chart.bars[0].fillColor=_c(accent);chart.bars[0].strokeColor=None;chart.valueAxis.gridStrokeColor=colors.HexColor('#E5E7EB');d.add(chart);d.add(String(50,205,title,fontName='Helvetica-Bold',fontSize=12,fillColor=colors.HexColor('#222222')));return d

def create_pdf(content:str,filename:str|None=None,creator:str="Agentie",style_hint:str|None=None)->dict:
    if not content or not content.strip():raise ValueError('PDF content is empty.')
    UPLOADS.mkdir(parents=True,exist_ok=True);path=unique_path(_clean_filename(filename,creator));style=choose_style(content,style_hint);title=document_title(content,'Report');styles=getSampleStyleSheet()
    title_style=ParagraphStyle('TitleX',parent=styles['Title'],fontName='Helvetica-Bold',fontSize=24,textColor=_c(style.accent),leading=28,alignment=TA_LEFT,spaceAfter=4)
    byline=ParagraphStyle('Byline',parent=styles['BodyText'],fontSize=8.5,textColor=_c(style.muted),spaceAfter=12)
    h1=ParagraphStyle('H1X',parent=styles['Heading1'],fontName='Helvetica-Bold',fontSize=16,textColor=_c(style.accent),leading=20,spaceBefore=12,spaceAfter=6)
    h2=ParagraphStyle('H2X',parent=styles['Heading2'],fontName='Helvetica-Bold',fontSize=12.5,textColor=_c(style.text),leading=16,spaceBefore=9,spaceAfter=4)
    body=ParagraphStyle('BodyX',parent=styles['BodyText'],fontName='Helvetica',fontSize=10.5,textColor=_c(style.text),leading=15,spaceAfter=7)
    bullet=ParagraphStyle('BulletX',parent=body,leftIndent=14,firstLineIndent=-8,spaceAfter=4)
    doc=SimpleDocTemplate(str(path),pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=16*mm,bottomMargin=17*mm,title=title,author=creator)
    story=[Paragraph(_markdown_inline(title),title_style),Paragraph(f"Prepared by {html.escape(creator)} · Agentie",byline),Table([['']],colWidths=[174*mm],rowHeights=[1.5],style=TableStyle([('BACKGROUND',(0,0),(-1,-1),_c(style.accent2)),('LINEBELOW',(0,0),(-1,-1),1,_c(style.accent))])),Spacer(1,8)]
    title_consumed=False
    for block in parse_blocks(content):
        typ=block['type']
        if typ=='heading':
            if block['level']==1 and not title_consumed and block['text']==title:title_consumed=True;continue
            story.append(Paragraph(_markdown_inline(block['text']),h1 if block['level']<=2 else h2))
        elif typ=='paragraph':story.append(Paragraph(_markdown_inline(block['text']),body))
        elif typ in {'bullets','numbered'}:
            for idx,item in enumerate(block['items'],1):story.append(Paragraph(('• ' if typ=='bullets' else f'{idx}. ')+_markdown_inline(item),bullet))
        elif typ=='table':
            rows=[[Paragraph(_markdown_inline(str(cell)),body) for cell in row] for row in block['rows']]
            if rows:
                width=max(len(r) for r in rows);rows=[r+[Paragraph('',body)]*(width-len(r)) for r in rows];tbl=Table(rows,repeatRows=1,hAlign='LEFT')
                commands=[('BACKGROUND',(0,0),(-1,0),_c(style.accent)),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('GRID',(0,0),(-1,-1),.35,colors.HexColor('#D7DCE1')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]
                for r in range(2,len(rows),2):commands.append(('BACKGROUND',(0,r),(-1,r),_c(style.soft)))
                tbl.setStyle(TableStyle(commands));story.extend([tbl,Spacer(1,8)])
    series=first_numeric_series(content)
    if series:
        labels,values,label=series;story.extend([Spacer(1,6),Paragraph('Visual summary',h1),KeepTogether(_chart(labels,values,label,style.accent))])
    def page(canvas,_doc):
        canvas.saveState();canvas.setFillColor(_c(style.muted));canvas.setFont('Helvetica',7.5);canvas.drawString(18*mm,8*mm,f'{creator} · Agentie');canvas.drawRightString(A4[0]-18*mm,8*mm,f'Page {_doc.page}');canvas.restoreState()
    doc.build(story,onFirstPage=page,onLaterPages=page);card=inspect_file(path);card.update({'document_style':style.id,'creator':creator});return card

def try_pdf_request(session_id:str,message:str)->dict|None:
    if not _PDF_INTENT_RE.search(message):return None
    filename=_extract_filename(message);content=_explicit_content(message)
    if content is None and (_REFERENCE_RE.search(message) or len(message.split())<=12):content=latest_assistant_text(session_id,max_chars=40000)
    if not content:return {'message':'What should I put in the PDF? You can paste the content or say “use the previous answer.”','card':None,'needs_content':True}
    creator=creator_from_session(session_id);card=create_pdf(content,filename,creator,message);return {'message':f"Created {card['name']} using the {card.get('document_style','professional')} document style.",'card':card,'needs_content':False}
