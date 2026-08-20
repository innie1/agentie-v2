from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True)
class DocumentStyle:
    id: str
    label: str
    accent: str
    accent2: str
    text: str
    muted: str
    soft: str
    title_size: int
    body_size: int


STYLE_PACKS: dict[str, DocumentStyle] = {
    "executive": DocumentStyle("executive","Executive","1F4E79","D9EAF7","17202A","5D6D7E","F4F7FA",28,11),
    "modern": DocumentStyle("modern","Modern","2563EB","DBEAFE","111827","6B7280","F8FAFC",27,11),
    "classic": DocumentStyle("classic","Classic","7A3E18","EFE5DB","201A17","756B65","FAF8F5",26,11),
    "research": DocumentStyle("research","Research","285943","DDEBE4","18211D","66756E","F6F9F7",25,10),
    "minimal": DocumentStyle("minimal","Minimal","30343B","ECEFF1","15181C","747B84","FAFAFA",25,11),
}


def choose_style(content: str, hint: str | None = None) -> DocumentStyle:
    hay=f"{hint or ''} {content[:5000]}".lower()
    explicit={
        "executive":("executive","board","management","business report","strategy"),
        "modern":("modern","product","launch","technology","startup","marketing"),
        "classic":("classic","formal letter","proposal","contract","memo"),
        "research":("research","analysis","study","findings","sources","citation","last30days"),
        "minimal":("minimal","simple","brief","summary","notes"),
    }
    for sid,words in explicit.items():
        if any(w in hay for w in words):return STYLE_PACKS[sid]
    return STYLE_PACKS["executive"] if len(content)>1800 else STYLE_PACKS["minimal"]


def clean_inline(text: str) -> str:
    value=str(text or "").strip()
    value=re.sub(r"\*\*(.+?)\*\*",r"\1",value)
    value=re.sub(r"__(.+?)__",r"\1",value)
    value=re.sub(r"`([^`]+)`",r"\1",value)
    return value


def document_title(content: str, fallback: str = "Document") -> str:
    for raw in content.replace("\r\n","\n").split("\n"):
        line=raw.strip()
        if line.startswith("# "):return clean_inline(line[2:])[:120]
    for raw in content.splitlines():
        line=clean_inline(re.sub(r"^[-*#\d.)\s]+","",raw))
        if 4 <= len(line) <= 100:return line
    return fallback


def parse_blocks(content: str) -> list[dict[str,Any]]:
    lines=content.replace("\r\n","\n").split("\n");blocks=[];paragraph=[]
    def flush():
        if paragraph:
            text=" ".join(x.strip() for x in paragraph if x.strip()).strip()
            if text:blocks.append({"type":"paragraph","text":clean_inline(text)})
            paragraph.clear()
    i=0
    while i<len(lines):
        raw=lines[i];line=raw.strip()
        if not line:flush();i+=1;continue
        if "|" in line and i+1<len(lines) and re.match(r"^\|?\s*:?-{3,}",lines[i+1].strip()):
            flush();rows=[];j=i
            while j<len(lines) and "|" in lines[j]:
                cells=[clean_inline(x.strip()) for x in lines[j].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?",c.replace(" ","")) for c in cells):rows.append(cells)
                j+=1
            blocks.append({"type":"table","rows":rows});i=j;continue
        h=re.match(r"^(#{1,4})\s+(.+)$",line)
        if h:
            flush();blocks.append({"type":"heading","level":len(h.group(1)),"text":clean_inline(h.group(2))});i+=1;continue
        b=re.match(r"^[-*]\s+(.+)$",line)
        if b:
            flush();items=[]
            while i<len(lines):
                m=re.match(r"^[-*]\s+(.+)$",lines[i].strip())
                if not m:break
                items.append(clean_inline(m.group(1)));i+=1
            blocks.append({"type":"bullets","items":items});continue
        n=re.match(r"^\d+[.)]\s+(.+)$",line)
        if n:
            flush();items=[]
            while i<len(lines):
                m=re.match(r"^\d+[.)]\s+(.+)$",lines[i].strip())
                if not m:break
                items.append(clean_inline(m.group(1)));i+=1
            blocks.append({"type":"numbered","items":items});continue
        paragraph.append(raw);i+=1
    flush();return blocks


def numeric_series(rows: list[list[str]]) -> tuple[list[str], list[float], str] | None:
    if len(rows)<3 or len(rows[0])<2:return None
    headers=rows[0]
    for col in range(1,len(headers)):
        labels=[];values=[]
        for row in rows[1:9]:
            if len(row)<=col:continue
            raw=re.sub(r"[^0-9.\-]","",str(row[col]))
            try:value=float(raw)
            except Exception:continue
            labels.append(str(row[0])[:18]);values.append(value)
        if len(values)>=2:return labels,values,str(headers[col] or "Value")
    return None


def first_numeric_series(content: str) -> tuple[list[str],list[float],str] | None:
    for block in parse_blocks(content):
        if block["type"]=="table":
            found=numeric_series(block["rows"])
            if found:return found
    return None


def chart_png_bytes(labels:list[str],values:list[float],title:str,style:DocumentStyle,width:int=1200,height:int=520)->bytes:
    image=Image.new("RGB",(width,height),"white");draw=ImageDraw.Draw(image)
    try:font=ImageFont.truetype("arial.ttf",24);small=ImageFont.truetype("arial.ttf",18);title_font=ImageFont.truetype("arialbd.ttf",30)
    except Exception:font=ImageFont.load_default();small=font;title_font=font
    draw.text((42,28),title,fill="#"+style.text,font=title_font)
    left,top,right,bottom=70,95,width-40,height-80;draw.line((left,bottom,right,bottom),fill="#C8CDD3",width=2)
    maxv=max([abs(v) for v in values] or [1]) or 1;gap=(right-left)/max(1,len(values));barw=max(16,int(gap*.56))
    for idx,(label,value) in enumerate(zip(labels,values)):
        x=left+gap*idx+gap/2;h=(abs(value)/maxv)*(bottom-top);y=bottom-h
        draw.rounded_rectangle((x-barw/2,y,x+barw/2,bottom),radius=5,fill="#"+style.accent)
        draw.text((x-barw/2,max(top,y-28)),f"{value:g}",fill="#"+style.text,font=small)
        draw.text((x-barw/2,bottom+12),label,fill="#"+style.muted,font=small)
    out=io.BytesIO();image.save(out,format="PNG",optimize=True);return out.getvalue()
