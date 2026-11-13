"""Text-only extraction of received documents; no macros or external links run."""
import io
import re
import zipfile
from xml.etree import ElementTree as ET


def tag(node):
    return node.tag.rsplit('}', 1)[-1]


def office_text(extension, raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        parts = archive.infolist()
        if len(parts) > 3000 or sum(p.file_size for p in parts) > 32 * 1024 * 1024:
            raise ValueError('文档解压后过大，未分析。')

        def xml(name):
            if archive.getinfo(name).file_size > 4 * 1024 * 1024:
                raise ValueError('文档单页过大，未分析。')
            data = archive.read(name)
            if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                raise ValueError('不支持文档实体声明。')
            return ET.fromstring(data)

        pattern = r'ppt/slides/slide(\d+)\.xml' if extension == '.pptx' else r'xl/worksheets/sheet(\d+)\.xml'
        names = sorted((p.filename for p in parts if re.fullmatch(pattern, p.filename)),
                       key=lambda n: int(re.fullmatch(pattern, n).group(1)))
        shared = []
        if extension == '.xlsx' and 'xl/sharedStrings.xml' in archive.namelist():
            shared = [''.join(n.text or '' for n in item.iter() if tag(n) == 't')
                      for item in xml('xl/sharedStrings.xml') if tag(item) == 'si']
        output = ['[仅提取文字和已缓存单元格值；未分析图表、嵌入图片，未执行公式或宏。工作表/幻灯片按文件编号排列。]']
        has_text = False
        for name in names[:30]:
            root = xml(name)
            output.append('\n[' + name + ']')
            if extension == '.pptx':
                texts = [n.text or '' for n in root.iter() if tag(n) == 't']
                has_text = has_text or any(t.strip() for t in texts)
                output.extend(texts)
            else:
                for cell in (n for n in root.iter() if tag(n) == 'c'):
                    value = next((n.text or '' for n in cell if tag(n) == 'v'), '')
                    if cell.get('t') == 's':
                        index = int(value)
                        if not 0 <= index < len(shared):
                            raise ValueError('表格文本索引无效。')
                        value = shared[index]
                    elif cell.get('t') == 'inlineStr':
                        value = ''.join(n.text or '' for n in cell.iter() if tag(n) == 't')
                    if value.strip():
                        has_text = True
                        output.append(cell.get('r', '?') + '=' + value)
                    if sum(map(len, output)) >= 12000:
                        break
            if sum(map(len, output)) >= 12000:
                output.append('[达到内容上限，后续内容未分析。]')
                break
        if len(names) > 30:
            output.append('[仅提取前 30 个工作表或幻灯片。]')
        return '\n'.join(output) if has_text else ''


def pdf_text(raw):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:
        raise ValueError('PDF 已加密，请提供未加密版本。')
    output = ['[仅提取 PDF 文字；未识别扫描图片、图表或版面。]']
    has_text = False
    for index, page in enumerate(reader.pages[:30]):
        content = page.get_contents()
        if content and len(content.get_data()) > 8 * 1024 * 1024:
            raise ValueError('PDF 单页内容过大，未分析。')
        text = page.extract_text() or ''
        has_text = has_text or bool(text.strip())
        output.append('[第 %s 页]\n%s' % (index + 1, text or '[未提取到文字；可能为扫描页，未识别图片内容。]'))
        if sum(map(len, output)) >= 12000:
            output.append('[达到内容上限，后续内容未分析。]')
            break
    if len(reader.pages) > 30:
        output.append('[仅提取前 30 页。]')
    return '\n'.join(output) if has_text else ''
