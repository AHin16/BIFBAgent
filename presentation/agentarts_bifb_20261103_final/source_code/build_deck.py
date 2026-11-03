"""Author a source-preserving 20-slide AgentArts/BIFB competition deck.

Run with Python 3.10+. Export through PPT Master's round-trip exporter.
Source facts: ../sources/user_brief.txt. Source design: ../sources/source.pptx.
This script never edits the source PPTX, themes, layouts, or native payloads.
"""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import shutil
import sys
from xml.etree import ElementTree as E

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
AUTHOR = ROOT / 'authoring-svg-flat'
BACKUP = Path(__file__).resolve().parent / 'template_svgs'
NOTES = ROOT / 'notes'
BACKUP.mkdir(exist_ok=True)
NOTES.mkdir(exist_ok=True)
for original in AUTHOR.glob('slide_*.svg'):
    if not (BACKUP / original.name).exists():
        shutil.copy2(original, BACKUP / original.name)

NS = 'http://www.w3.org/2000/svg'
E.register_namespace('', NS)
E.register_namespace('xlink', 'http://www.w3.org/1999/xlink')
RED, ORANGE, GOLD = '#9D0B0B', '#EB8242', '#F6DA63'
INK, MUTED, TINT, BORDER = '#323232', '#666666', '#FBF4F2', '#DEC5BE'
# English family alias of the source theme's 等线; same installed Windows font.
# This prevents the exporter from assigning Microsoft YaHei to CJK text.
FONT = 'DengXian'
placeholders: list[dict] = []
roster: list[dict] = []
page_text: list[dict] = []


def el(parent, tag, **attrs):
    return E.SubElement(parent, f'{{{NS}}}{tag}', {k.replace('_', '-'):str(v) for k,v in attrs.items()})


def group(parent, gid, bounds=None):
    g = el(parent, 'g', id=gid)
    if bounds:
        g.set('data-pptx-bounds', ' '.join(map(str, bounds)))
    return g


def rect(parent, x, y, w, h, fill='#FFFFFF', stroke='none', sw=1, rx=0, dash=None):
    a = el(parent, 'rect', x=x, y=y, width=w, height=h, fill=fill, stroke=stroke, stroke_width=sw)
    if rx:
        a.set('rx',str(rx)); a.set('ry',str(rx))
    if dash:
        a.set('stroke-dasharray',dash)
    return a


def text(parent, x, y, content, size=22, color=INK, bold=False, anchor='start', leading=None, family=FONT):
    lines = content.split('\n') if isinstance(content,str) else content
    t = el(parent, 'text', x=x, y=y, font_family=family, font_size=size, fill=color,
           font_weight='bold' if bold else 'normal', text_anchor=anchor)
    t.text = str(lines[0])
    for line in lines[1:]:
        row = el(t,'tspan',x=x,dy=leading or round(size*1.42,2))
        row.text = str(line)
    return t


def line(parent,x1,y1,x2,y2,color=BORDER,sw=1.5,arrow=False,dash=None):
    a = el(parent,'line',x1=x1,y1=y1,x2=x2,y2=y2,stroke=color,stroke_width=sw)
    if arrow: a.set('marker-end','url(#agent-arrow)')
    if dash: a.set('stroke-dasharray',dash)
    return a


def formula(parent,x,y,runs,size=24,color=INK,bold=False):
    t=text(parent,x,y,'',size,color,bold)
    for run in runs:
        if isinstance(run,tuple):
            s=el(t,'tspan',font_size=round(size*.7,2))
            s.set('baseline-shift','sub');s.text=run[1]
        elif len(t)==0 and not t.text:
            t.text=run
        else:
            el(t,'tspan').text=run
    return t


def bullets(parent,x,y,items,size=22,step=42,color=INK):
    for i,item in enumerate(items):
        text(parent,x,y+i*step,'• '+item,size,color)


def section(parent,x,y,label,width=1148):
    text(parent,x,y,label,23,RED,True)
    line(parent,x,y+14,x+width,y+14,BORDER,1)


def node(parent,gid,x,y,w,h,label,detail='',active=False):
    g=group(parent,gid,(x,y,w,h))
    rect(g,x,y,w,h,RED if active else '#FFFFFF',RED,1.5,7)
    text(g,x+w/2,y+31,label,23,'#FFFFFF' if active else RED,True,'middle')
    if detail:
        text(g,x+w/2,y+62,detail,18,'#FFFFFF' if active else MUTED,False,'middle',25)
    return g


def flow(parent,gid,x,y,w,labels,detail=None,h=64,size=21):
    g=group(parent,gid,(x,y,w,h))
    gap=25; box=(w-gap*(len(labels)-1))/len(labels)
    for i,label in enumerate(labels):
        xx=x+i*(box+gap)
        rect(g,xx,y,box,h,TINT,RED,1,5)
        text(g,xx+box/2,y+(h/2+size*.35 if not detail else 28),label,size,RED,True,'middle')
        if detail:
            text(g,xx+box/2,y+58,detail[i],17,MUTED,False,'middle')
        if i<len(labels)-1:
            line(g,xx+box+3,y+h/2,xx+box+gap-5,y+h/2,RED,2,True)
    return g


def callout(parent,gid,x,y,w,h,headline,body=None):
    g=group(parent,gid,(x,y,w,h))
    rect(g,x,y,w,h,TINT)
    rect(g,x,y,5,h,ORANGE)
    text(g,x+20,y+31,headline,23,RED,True)
    if body: text(g,x+20,y+65,body,21,INK,leading=29)
    return g


def placeholder(parent,page,gid,x,y,w,h,label,ratio=None,note='待替换真实素材'):
    # Recommend the actual frame ratio so screenshots and plots are not distorted.
    actual=w/h
    standards=[(4/3,'4:3'),(16/9,'16:9'),(2,'2:1'),(3,'3:1'),(4,'4:1')]
    nearest=min(standards,key=lambda p:abs(p[0]-actual))
    ratio=nearest[1] if abs(nearest[0]-actual)/actual<.04 else f'{actual:.2f}:1'
    g=group(parent,gid,(x,y,w,h))
    rect(g,x,y,w,h,TINT,RED,1.4,0,'6,3')
    # Corner registration marks make an image slot recognizable at thumbnail scale.
    for xx,yy,dx,dy in [(x+8,y+8,18,18),(x+w-8,y+8,-18,18),(x+8,y+h-8,18,-18),(x+w-8,y+h-8,-18,-18)]:
        line(g,xx,yy,xx+dx,yy,ORANGE,2)
        line(g,xx,yy,xx,yy+dy,ORANGE,2)
    label_lines=label.split('\n')
    cy=y+h/2-(len(label_lines)-1)*14
    if h<110:
        text(g,x+w/2,y+24,'图片占位符',14,RED,True,'middle')
        text(g,x+w/2,y+48,label_lines,17,INK,True,'middle',24)
        text(g,x+w/2,y+h-12,f'{note} · 建议比例 {ratio}',12,MUTED,False,'middle')
    else:
        text(g,x+w/2,cy-18,'图片占位符',16,RED,True,'middle')
        text(g,x+w/2,cy+12,label_lines,21 if w>320 else 18,INK,True,'middle',27)
        text(g,x+w/2,y+h-18,f'{note} · 建议比例 {ratio}',15,MUTED,False,'middle')
    placeholders.append({'page':f'P{page:02d}','id':gid,'name':label.replace('\n',''),
                         'ratio':ratio,'width_px':w,'height_px':h,
                         'recommended_pixels':f'{round(w*2)} × {round(h*2)}',
                         'replacement_note':note+'；保留宽高比，不将示意图当作实验结果'})
    return g


def clear_content(root,keep_ids=()):
    for child in list(root):
        ref=child.get('data-pptx-source-ref','')
        if ref.startswith('slide:') and child.get('id') not in keep_ids:
            root.remove(child)


def replace_shape(root,gid,writer):
    g=next(e for e in root if e.get('id')==gid)
    # Imported semantic shapes require their original direct geometry carrier.
    # Retain the transparent native frame and change only the text content.
    for child in list(g):
        if child.tag==f'{{{NS}}}text': g.remove(child)
    writer(g)


def make_page(page,source,filename,section_label=None,headline=None,status='方案设计 · 待集成验证'):
    root=E.parse(BACKUP/f'slide_{source:02d}.svg').getroot()
    defs=next((c for c in root if c.tag.endswith('}defs')),None)
    if defs is None:
        defs=E.Element(f'{{{NS}}}defs');root.insert(0,defs)
    marker=el(defs,'marker',id='agent-arrow',markerWidth=7,markerHeight=7,refX=6,refY=3.5,orient='auto')
    el(marker,'polygon',points='0,0 7,3.5 0,7',fill=RED)
    if source not in (1,2,14):
        clear_content(root,('shape-12',))
        replace_shape(root,'shape-12',lambda g:text(g,76,70,section_label,24,INK,True))
        g=group(root,f'p{page:02d}-heading',(65,112,1150,64))
        text(g,65,147,headline,31,RED,True)
        g=group(root,f'p{page:02d}-page-number',(1000,690,220,20))
        text(g,1210,704,f'{page:02d} / 20',14,MUTED,anchor='end')
        if status:
            g=group(root,f'p{page:02d}-status',(65,621,1148,26))
            text(g,65,641,status,16,MUTED)
    roster.append({'source_slide':source,**({'svg':filename} if filename!=f'slide_{source:02d}.svg' else {})})
    return root


def save(root,filename,page,note):
    E.ElementTree(root).write(AUTHOR/filename,encoding='utf-8',xml_declaration=True)
    (NOTES/(Path(filename).stem+'.md')).write_text(note+'\n',encoding='utf-8')
    texts=[''.join(t.itertext()) for t in root.iter() if t.tag==f'{{{NS}}}text']
    page_text.append({'page':page,'svg':filename,'source_section':f'用户材料P{page}','text':texts,'notes':note})


# P01 — keep native cover, logo and GDUT watermark; edit existing text slots.
r=make_page(1,1,'slide_01.svg')
replace_shape(r,'shape-2',lambda g:text(g,67,199,['基于华为云AgentArts的','BIFB智能运行分析与','优化决策智能体'],42,'#FFFFFF',True,leading=54))
replace_shape(r,'shape-3',lambda g:text(g,67,391,'面向气泡诱导逆流化床的智能实验分析与运行优化',23,'#FFFFFF'))
replace_shape(r,'shape-4',lambda g:text(g,67,547,'指导老师：罗劭娟  |  汇报学生：温盈轩、张定康',20,RED))
g=group(r,'p01-cover-metadata',(67,568,1145,58))
text(g,67,583,'参赛团队：待补充    学校：广东工业大学    日期：2026年11月3日',18,INK)
text(g,67,614,'赛题：基于AgentArts智能体开发平台的Agent设计和应用',18,INK)
save(r,'slide_01.svg',1,'本项目面向气泡诱导逆流化床的实验分析与运行优化，提出基于华为云AgentArts的领域智能体方案。汇报将区分已有视觉研究基础与尚待集成、验证的智能体能力。')

# P02 — application problem, editable traditional process, experiment slot.
r=make_page(2,3,'slide_03.svg','项目背景与应用需求','复杂多相流过程亟需智能化分析与决策',status='项目目标：让专业工具、实验数据与领域知识围绕同一科研任务协同工作')
g=group(r,'p02-context',(65,178,1148,70))
text(g,65,202,['BIFB涉及气、液、固三相相互作用，','气泡行为与颗粒运动共同影响流化状态及传质特性。'],23,INK,leading=32)
placeholder(r,2,'p02-apparatus',65,277,365,278,'BIFB实验装置照片','4:3')
g=group(r,'p02-problems',(465,272,748,275))
section(g,465,297,'实验分析中的五类断点',748)
bullets(g,465,339,['图像数量大，识别统计依赖人工或独立算法','尺寸、速度与空间分布分散，难以统一分析','流化状态判断需要多指标综合支撑','专业知识、实验数据与计算工具彼此独立','参数优化涉及多约束，人工分析效率受限'],21,42)
flow(r,'p02-traditional-flow',65,575,1148,['采集图像','手动选工具','独立分析','人工汇总','经验调参'],h=40,size=19)
save(r,'slide_03.svg',2,'BIFB是气液固三相耦合体系，气泡和颗粒的运动共同影响运行状态。当前的主要问题是图像、参数、知识和计算工具彼此分散，分析人员需要反复手动衔接。项目希望以自然语言任务作为入口，自动组织专业分析并给出有依据的建议。')

# P03 — retain native five-item navigation page; fill the five numbered slots.
r=make_page(3,2,'slide_02.svg')
g=group(r,'p03-title',(90,75,1110,43))
text(g,90,104,'面向BIFB实验分析与运行优化的五类应用场景',27,RED,True)
items=[('实验图像智能分析','分割 · 追踪 · 尺寸/速度 · 统计图表'),('流化状态分析','多气泡特征 · 状态分析 · 工况对比'),('气含率估算','图像特征 · 几何估算 · 结果解释'),('运行参数优化','参数搜索 · 约束检查 · 方案比较'),('专业知识问答','文献检索 · 理论解释 · 模型边界')]
texts=[t for c in r if c.get('id')=='shape-21' for t in c.iter() if t.tag.endswith('}text')]
for i,(label,desc) in enumerate(items):
    t=texts[2*i+1]
    t.attrib.clear();t.set('x','824');t.set('y',str(153+i*106));t.set('font-family',FONT);t.set('font-size','26');t.set('fill',INK);t.set('font-weight','bold')
    for ch in list(t):t.remove(ch)
    t.text=label
    g=group(r,f'p03-detail-{i}',(824,167+i*106,358,43))
    text(g,824,194+i*106,desc,17,MUTED)
placeholder(r,3,'p03-scene',100,127,385,82,'BIFB实验场景图片','16:9')
placeholder(r,3,'p03-vision',100,511,385,118,'气泡视觉分析结果图片','16:9')
save(r,'slide_02.svg',3,'项目围绕五类应用场景展开：实验图像分析、流化状态分析、气含率估算、运行参数优化和知识问答。这些能力按照用户任务按需调用，不要求用户记住工具名称。图中实验场景与视觉结果位置均等待替换真实素材。')

# P04 — editable comparison table.
r=make_page(4,5,'slide_05.svg','传统模式与Agent方案','从独立算法工具走向智能任务编排',status='核心价值：将专业算法组织为可交互、可协作、可执行的任务体系')
g=group(r,'p04-comparison',(65,185,1148,355))
rect(g,65,185,1148,54,RED)
text(g,89,221,'任务环节',22,'#FFFFFF',True);text(g,300,221,'传统分析模式',24,'#FFFFFF',True);text(g,767,221,'Agent任务模式',24,'#FFFFFF',True)
rows=[('任务入口','人工选择算法','自然语言理解任务'),('输入准备','手动整理实验参数','自动识别所需输入'),('执行组织','独立运行分析脚本','规划工具调用并执行Workflow'),('结果汇总','人工汇总分析结果','综合多源信息与约束检查'),('参数决策','手动调整运行参数','比较候选方案并给出建议'),('依据表达','结果缺少统一解释','输出可解释的决策依据')]
for i,(a,b,c) in enumerate(rows):
    y=239+i*50
    rect(g,65,y,1148,50,TINT if i%2==0 else '#FFFFFF')
    text(g,89,y+33,a,21,RED,True);text(g,300,y+33,b,22);text(g,767,y+33,c,22)
    line(g,65,y+50,1213,y+50,BORDER,1)
callout(r,'p04-takeaway',65,560,1148,50,'Agent组织专业算法的执行，并让分析过程与结论依据可见。')
save(r,'slide_05.svg',4,'传统模式要求分析人员选择脚本、准备参数，再手工汇总输出。Agent方案把任务理解、工具选择、流程执行与解释连接起来，专业算法仍承担检测和数值计算。核心改变是任务组织方式，使用户能够直接提出科研目标。')

# P05 — known visual-model evidence, not agent performance.
r=make_page(5,4,'slide_04.svg','项目基础：气泡视觉感知','以自主研发的气泡视觉分析技术为专业能力基础',status='数据来源：用户提供的已有视觉模型实验结果；不是本次复测结果，也不是Agent整体性能')
metrics=[('0.970','mAP@0.5'),('0.941','Recall'),('6.26M','参数量'),('27.5','GFLOPs'),('约13 MB','模型权重')]
for i,(value,label) in enumerate(metrics):
    x=65+i*233
    g=group(r,f'p05-metric-{i}',(x,181,216,86))
    text(g,x,220,value,38,RED,True);text(g,x,253,label,20,MUTED)
flow(r,'p05-foundation',65,289,1148,['实例分割','跨帧关联','掩膜尺寸计算','质心轨迹测速','群体统计'],h=55,size=21)
placeholder(r,5,'p05-segmentation',65,366,365,200,'YOLO11-BUBBLE\n气泡实例分割结果','16:9')
placeholder(r,5,'p05-tracking',457,366,365,200,'气泡追踪结果','16:9')
placeholder(r,5,'p05-statistics',849,366,365,200,'气泡尺寸/速度统计图','16:9')
g=group(r,'p05-role',(65,579,1148,31));text(g,65,602,'已有检测、追踪与测量能力 → 封装为Agent可调用的专业视觉工具',22,RED,True)
save(r,'slide_04.svg',5,'已有视觉研究以YOLO11-BUBBLE为基础，覆盖气泡实例分割、跨帧追踪、掩膜尺寸计算和质心轨迹测速。页面五项数值均来自用户提供的已有视觉模型结果，其中mAP@0.5为0.970、Recall为0.941。它们不能代表Agent任务完成率或端到端优化效果，相关接入与评估仍需单独验证。')

# P06 — transparent agent loop and evidence boundaries.
r=make_page(6,6,'slide_06.svg','Agent任务定义与机制','构建具备任务理解、工具调用与结果综合能力的领域Agent')
g=group(r,'p06-input',(65,183,1148,55));text(g,65,211,'用户以自然语言提出实验分析或优化需求，Agent组织执行并输出可解释报告。',24)
xs=[65,365,665,965]
for i,(lab,det) in enumerate([('用户输入','任务 + 实验数据'),('意图识别','明确目标与缺失信息'),('任务规划','分解分析步骤'),('工具选择','匹配专业能力')]):
    node(r,f'p06-stage-{i}',xs[i],260,248,98,lab,det,active=i==0)
    if i<3:
        g=group(r,f'p06-link-a{i}');line(g,xs[i]+252,309,xs[i+1]-7,309,RED,2,True)
for i,(lab,det) in enumerate([('报告生成','结果、建议与依据'),('结果校验','模型边界与约束'),('结果整合','统一结构化输出'),('Workflow执行','工具运行并返回观察')]):
    node(r,f'p06-stage-{i+4}',xs[i],408,248,98,lab,det,active=i==0)
    if i<3:
        g=group(r,f'p06-link-b{i}');line(g,xs[i+1]-6,457,xs[i]+254,457,RED,2,True)
g=group(r,'p06-observation-loop',(787,360,310,45));line(g,1089,362,1089,402,RED,2,True)
line(g,789,403,789,380,RED,1.5);line(g,789,380,789,364,RED,1.5,True,dash='8,4')
text(g,810,390,'观察后按需补充调用',17,MUTED)
callout(r,'p06-boundary',65,541,1148,69,'LLM负责理解、规划与解释；专业工具负责推理、测量与数值计算。')
save(r,'slide_06.svg',6,'Agent首先理解用户意图并确认输入，再规划任务并选择工具。Workflow调用视觉、知识和计算能力，返回的结构化观察可触发后续调用。最终报告需要经过结果整合与校验，LLM负责解释，专业工具负责真实计算。')

# P07 — six-layer architecture with cross-cutting quality rail.
r=make_page(7,7,'slide_07.svg','Agent总体架构','构建面向BIFB的分层智能体架构')
layers=[('01 用户交互层','自然语言输入  ·  实验数据上传  ·  结果可视化'),('02 主控Agent','任务理解 / 意图识别  ·  任务规划 / 工具选择  ·  结果整合 / 交互追问'),('03 专业能力层','Bubble Vision  |  Hydrodynamics  |  Knowledge  |  Optimization'),('04 Workflow与工具层','图像分析  ·  水动力计算  ·  知识检索  ·  参数优化  ·  Python/API'),('05 知识与数据层','实验数据  ·  BIFB文献  ·  流体力学知识  ·  模型方法  ·  历史工况')]
for i,(lab,body) in enumerate(layers):
    y=188+i*81
    g=group(r,f'p07-layer-{i}',(65,y,933,64))
    rect(g,65,y,933,64,TINT if i!=1 else RED,BORDER,1)
    text(g,83,y+28,lab,21,'#FFFFFF' if i==1 else RED,True)
    text(g,83,y+54,body,19,'#FFFFFF' if i==1 else INK)
    if i<4:
        g=group(r,f'p07-layer-link-{i}');line(g,530,y+66,530,y+77,RED,1.7,True)
g=group(r,'p07-quality',(1020,188,193,388))
rect(g,1020,188,193,388,TINT,RED,1.5)
text(g,1116,223,['06 质量保障层','跨层贯穿'],21,RED,True,'middle',31)
text(g,1041,320,['输入校验','模型适用范围','约束检查','执行日志','效果评估'],20,INK,leading=44)
for i in range(5):line(g,1001,220+i*81,1017,220+i*81,RED,1.4)
save(r,'slide_07.svg',7,'架构以主控Agent为任务组织中心，向下调用四类专业能力和Workflow工具，向上服务自然语言交互。知识与数据层提供实验记录、文献及模型方法。第六层质量保障贯穿输入、模型、执行和决策全程，目前这是一份待集成验证的架构设计。')

# P08 — dynamic task planning and optional tools.
r=make_page(8,8,'slide_08.svg','Agent任务规划与工具编排','基于任务理解实现专业能力的动态调用与协同')
callout(r,'p08-request',65,181,1148,71,'“分析这组实验图像，判断气泡行为特征，并给出通气参数调整建议。”')
steps=[('任务识别','图像分析 / 工况诊断 / 参数建议'),('输入检查','图像、通气量、颗粒浓度是否完整'),('任务规划','视觉 → 特征 → 状态 → 参数搜索'),('工具调用','按输入与目标调用必要的工具'),('结果整合','汇总气泡统计、模型与约束结果'),('任务输出','生成报告、建议与结论依据')]
g=group(r,'p08-task-chain',(65,273,635,337))
for i,(a,b) in enumerate(steps):
    y=278+i*54
    el(g,'circle',cx=82,cy=y+11,r=15,fill=RED)
    text(g,82,y+18,str(i+1),18,'#FFFFFF',True,'middle')
    text(g,111,y+19,a,22,RED,True);text(g,246,y+19,b,20)
    if i<5:line(g,82,y+29,82,y+40,RED,1.5,True)
g=group(r,'p08-tool-map',(752,279,461,314))
section(g,752,300,'按需调用专业能力',461)
for i,(a,b) in enumerate([('视觉模型','分割、追踪与特征提取'),('计算脚本','水动力预测与参数搜索'),('知识检索','理论依据与模型适用范围'),('校验工具','输入完整性与约束满足')]):
    y=327+i*66
    rect(g,752,y,461,55,TINT)
    text(g,770,y+24,a,21,RED,True);text(g,770,y+47,b,18,MUTED)
line(g,720,440,745,440,RED,2,True,dash='8,4')
save(r,'slide_08.svg',8,'以一组实验图像的分析任务为例，Agent同时识别图像分析、工况诊断和参数建议三个目标。它先检查图像与运行参数，再决定是否需要视觉计算、知识检索和参数搜索。输入不完整时先追问，工具结果返回后再综合并校验，不要求每个任务机械执行全部工具。')

# P09 — four editable input/function/output skill cards.
r=make_page(9,5,'p09_skills.svg','四类专业Skill设计','构建面向BIFB业务的专业Skill体系')
cards=[('01 Bubble Vision','图像 / 视频 + 标定信息','实例分割、气泡追踪、尺寸/速度计算','数量、尺寸、速度与统计分布'),('02 Hydrodynamics','气泡特征 + 工况参数','多特征融合、状态分析、模型预测','状态特征、气含率估算及边界'),('03 Knowledge','专业问题 + 当前任务上下文','文献检索、知识问答、理论解释','专业回答、文献依据、模型范围'),('04 Optimization','运行目标 + 约束 + 可用模型','参数搜索、多约束评估、方案比较','推荐参数、候选方案与决策依据')]
for i,(title,inp,fn,out) in enumerate(cards):
    x=65+(i%2)*590;y=184+(i//2)*216
    g=group(r,f'p09-skill-{i}',(x,y,558,196))
    rect(g,x,y,558,196,TINT,BORDER,1)
    rect(g,x,y,558,42,RED)
    text(g,x+18,y+29,title,25,'#FFFFFF',True)
    for j,(lab,body) in enumerate([('输入',inp),('功能',fn),('输出',out)]):
        text(g,x+18,y+77+j*44,lab,20,RED,True);text(g,x+78,y+77+j*44,body,20)
save(r,'p09_skills.svg',9,'四类Skill把专业能力封装成明确的输入、处理与输出契约。Bubble Vision提供测量结果，Hydrodynamics处理流化特征与预测，Knowledge提供理论依据，Optimization比较约束下的候选参数。它们是按业务划分的专业能力模块，并不表示已经实现多Agent系统。')

# P10 — vision pipeline and five explicit material slots.
r=make_page(10,4,'p10_vision.svg','智能气泡视觉分析','实现从实验图像到气泡行为特征的自动提取',status='测量所需输入：尺寸标定、帧率/时间间隔；追踪与速度计算需要连续帧，单张图像不提供速度')
flow(r,'p10-vision-flow',65,183,1148,['实验图像','YOLO分割','气泡追踪','尺寸/速度','多维统计','结果输出'],h=53,size=20)
for i,(gid,label) in enumerate([('raw','原始实验图像'),('seg','实例分割结果'),('track','气泡跟踪结果')]):
    placeholder(r,10,'p10-'+gid,65+i*391,258,366,182,label,'16:9')
placeholder(r,10,'p10-size-dist',65,460,366,145,'尺寸分布图','16:9')
placeholder(r,10,'p10-speed-dist',456,460,366,145,'速度分布图','16:9')
g=group(r,'p10-output',(849,463,364,142))
text(g,849,488,'结构化输出指标',23,RED,True)
text(g,849,521,['数量 · 等效直径 · 上升速度','尺寸分布 · 速度分布','数量密度 · 投影面积占比'],21,INK,leading=34)
save(r,'p10_vision.svg',10,'视觉流程从实验图像进入YOLO实例分割，通过跨帧追踪得到质心轨迹，再计算尺寸、速度与群体统计。物理尺寸需要空间标定，速度还需要连续帧及已知时间间隔，不能仅凭单张图像计算。页面所有实验图和分布图都保留明确占位，等待导入真实结果。')

# P11 — observable vs estimate; editable geometry is not a fake measurement.
r=make_page(11,11,'slide_11.svg','流化状态与气含率','融合气泡视觉特征开展流化状态分析',status='关键边界：二维投影面积占比不等于三维真实气含率；几何假设与参考实验校准必须明确')
flow(r,'p11-feature-flow',65,181,1148,['多维气泡特征','特征融合','状态分析','工况对比','状态特征输出'],h=53,size=20)
g=group(r,'p11-features',(65,256,484,65));text(g,65,280,['特征：尺寸分布、数量密度、速度及波动、','投影面积占比与空间分布。'],21,INK,leading=31)
placeholder(r,11,'p11-condition-comparison',65,342,484,119,'不同工况气泡特征对比','16:9')
placeholder(r,11,'p11-bubble-distribution',65,482,484,119,'气泡分布图','16:9')
g=group(r,'p11-estimation',(584,256,629,345))
section(g,584,280,'气含率估算：观测—假设—校准',629)
for i,(title,body) in enumerate([('直接观测','二维投影面积占比：图像直接观测指标'),('几何假设','由投影特征推算三维体积分数的估计值'),('实验校准','使用参考值检验并校准误差与适用范围')]):
    y=309+i*91
    rect(g,584,y,629,73,TINT)
    text(g,600,y+29,title,22,RED,True);text(g,600,y+58,body,20)
    if i<2:line(g,900,y+74,900,y+86,RED,1.6,True)
text(g,600,594,'输出为估算值，并附假设、校准依据和不确定性。',20,RED,True)
save(r,'slide_11.svg',11,'流化状态分析融合尺寸分布、数量密度、速度波动和空间分布，避免仅用单一特征判断状态。气含率部分先区分二维投影面积占比与三维真实气含率，它们并不相等。三维估算需要几何假设和参考实验校准，输出必须说明适用范围与不确定性。')

# P12 — knowledge retrieval and grounded explanation.
r=make_page(12,12,'slide_12.svg','知识增强与专业问答','通过知识库增强Agent专业理解与结果解释能力')
flow(r,'p12-retrieval',65,182,1148,['用户提问','识别知识需求','知识库检索','相关内容召回','结合上下文','回答与依据'],h=53,size=19)
g=group(r,'p12-knowledge',(65,261,538,170))
section(g,65,286,'知识库内容',538)
text(g,65,326,['BIFB基础理论 · 气泡动力学','三相逆流化床文献 · 气含率模型','流化状态方法 · 实验操作与数据说明'],22,INK,leading=38)
callout(r,'p12-example',65,461,538,142,'示例问题','不同通气量下，气泡速度分布\n变化的原因是什么？')
g=group(r,'p12-basis',(645,261,568,62));text(g,645,286,'回答同时对照：实验数据、理论、文献与模型边界。',21,RED,True)
placeholder(r,12,'p12-kb-config',645,327,568,125,'AgentArts知识库配置截图','16:9')
placeholder(r,12,'p12-retrieval-result',645,475,568,128,'知识检索结果截图','16:9')
save(r,'slide_12.svg',12,'知识库拟收录BIFB理论、气泡动力学、气含率模型、相关文献和实验说明。Agent识别知识需求后检索相关内容，再结合当前实验数据作解释。专业回答需要同时给出理论或文献依据与模型适用范围，平台配置和检索结果尚待真实截图替换。')

# P13 — no invented candidate values: editable concept, plot slot.
r=make_page(13,9,'slide_09.svg','多约束参数优化','构建基于多约束条件的通气参数优化决策',status='定位：基于模型与实验数据的离线决策支持；建议参数需要实验验证，不宣称在线闭环控制')
g=group(r,'p13-formulation',(65,183,408,279))
rect(g,65,183,408,279,TINT)
text(g,86,219,'优化目标',23,RED,True)
formula(g,86,265,['min Q',('sub','g')],36,RED,True)
text(g,86,305,'在满足流化与传质需求下寻找合理通气量',18)
formula(g,86,350,['ε',('sub','g'),' ≥ ε',('sub','g,min')],24)
formula(g,86,389,['OTR ≥ OTR',('sub','required')],24)
formula(g,86,428,['Q',('sub','g,min'),' ≤ Q',('sub','g'),' ≤ Q',('sub','g,max')],24)
g=group(r,'p13-definition',(65,482,408,118));text(g,65,508,['Q_g：通气量    ε_g：气含率','OTR：氧传递速率','阈值与搜索范围由实验及工艺需求给定'],20,INK,leading=34)
flow(r,'p13-search-a',506,183,707,['工况输入','候选参数生成','水动力模型计算'],h=60,size=20)
flow(r,'p13-search-b',506,271,707,['约束检查','可行方案筛选','候选方案排序'],h=60,size=20)
g=group(r,'p13-search-link')
line(g,1103,246,1103,257,RED,1.7);line(g,1103,257,616,257,RED,1.7);line(g,616,257,616,267,RED,1.7,True)
placeholder(r,13,'p13-candidate-comparison',506,355,707,160,'候选工况对比图','16:9',note='待优化计算完成后替换')
g=group(r,'p13-output',(506,538,707,66));text(g,506,560,'推荐输出',22,RED,True)
text(g,506,592,'通气量 · 预测气含率 · 约束状态 · 候选对比 · 决策依据',20)
save(r,'slide_09.svg',13,'优化问题以合理降低通气量为目标，同时满足气含率、氧传递和参数范围约束。Agent组织候选生成、水动力预测、约束检查和方案排序，输出推荐参数及其依据。该能力定位为基于模型和实验数据的离线决策支持，当前不展示未经计算的候选数值或优化收益。')

# P14 — three-layer quality checks, paths for missing/out-of-range information.
r=make_page(14,10,'slide_10.svg','结果校验与可信决策','通过多层验证提升Agent输出的可靠性')
checks=[('01 输入校验',['实验参数是否完整','输入单位是否一致','参数范围是否合理'],'不完整 → 主动追问'),('02 模型校验',['检查模型适用范围','核查预测结果合理性','检查图像与数据质量'],'超范围 → 提示风险'),('03 决策校验',['核查约束满足情况','确认候选方案可行','比对各工具结果一致性'],'不通过 → 返回修正')]
for i,(title,items,action) in enumerate(checks):
    x=65+i*391
    g=group(r,f'p14-check-{i}',(x,206,366,274))
    rect(g,x,206,366,274,TINT,BORDER,1)
    text(g,x+20,247,title,28,RED,True)
    bullets(g,x+20,299,items,22,44)
    line(g,x+20,405,x+346,405,BORDER,1)
    text(g,x+20,451,action,21,RED,True)
    if i<2:line(g,x+370,344,x+385,344,RED,2,True)
callout(r,'p14-output-policy',65,519,1148,84,'输出机制：结果依据 + 不确定性提示 + 数据不足时追问 + 超模型范围时风险提示')
save(r,'slide_10.svg',14,'可靠输出需要逐层检查输入、模型和决策。输入缺失时主动追问，模型超出适用范围时提示风险，约束未满足时返回修正。最终报告同时列出结果依据和不确定性，而不是仅输出一个推荐数值。')

# P15 — AgentArts mapping, no false screenshots or unsupported completion claims.
r=make_page(15,6,'p15_agentarts.svg','AgentArts平台实现方案','基于AgentArts完成Agent构建、工具编排与部署',status='平台实现方案：待实际接入、运行与验证；MCP、多Agent仅作为后续可选能力，接入后再展示')
g=group(r,'p15-platform-map',(65,181,507,425))
mapping=[('Agent配置','主控角色、系统指令、理解与选工具'),('Workflow','视觉分析、水动力预测、优化与校验'),('知识库','BIFB文献、实验知识、模型说明'),('工具集成','Python计算工具、自定义API'),('效果评估','调用日志、执行结果、任务评价'),('部署应用','Demo界面、用户交互、系统运行')]
for i,(a,b) in enumerate(mapping):
    y=185+i*69
    text(g,65,y+25,a,23,RED,True);text(g,65,y+54,b,20)
    line(g,65,y+64,557,y+64,BORDER,1)
for i,(gid,label) in enumerate([('agent','主控Agent配置截图'),('workflow','Workflow画布截图'),('knowledge','知识库截图'),('tools','工具配置截图')]):
    placeholder(r,15,'p15-'+gid,600+(i%2)*317,185+(i//2)*214,296,188,'AgentArts\n'+label,'16:9')
save(r,'p15_agentarts.svg',15,'本页给出AgentArts平台能力与项目模块的对应方案，包括Agent配置、Workflow、知识库、工具、评估和部署。四处平台截图明确保留占位，说明这些位置需要实际配置和运行后的证据。MCP接入与多Agent协作属于后续可选能力，当前不作为已完成成果展示。')

# P16 — ten editable nodes and input/output labels.
r=make_page(16,8,'p16_workflow.svg','Workflow设计与自动执行','通过可视化Workflow实现专业分析流程自动化')
labs=['开始','输入参数检查','视觉分析工具','特征提取','知识检索','水动力预测','参数优化','结果校验','综合报告生成','结束']
details=['任务 / 数据','完整性 / 单位','图像 → 实例','实例 → 统计','问题 → 依据','工况 → 预测','目标 → 候选','约束 → 状态','多源 → 报告','结果交付']
flow(r,'p16-workflow-top',65,187,1148,labs[:5],details[:5],h=83,size=21)
flow(r,'p16-workflow-bottom',65,312,1148,labs[5:],details[5:],h=83,size=21)
g=group(r,'p16-row-bridge')
line(g,1110,274,1110,291,RED,1.7);line(g,1110,291,171,291,RED,1.7);line(g,171,291,171,306,RED,1.7,True)
placeholder(r,16,'p16-runtime',65,426,760,179,'AgentArts实际Workflow运行截图','16:9')
g=group(r,'p16-runtime-observability',(858,427,355,178))
text(g,858,454,'执行可观测信息',23,RED,True)
text(g,858,493,['节点输入与输出','工具状态与调用日志','错误位置与校验结果','任务完成状态'],21,INK,leading=33)
save(r,'p16_workflow.svg',16,'示例Workflow从输入检查开始，依次组织视觉、特征、知识、水动力、优化和校验，再生成报告。每个关键节点标注了输入与输出类型，便于对照专业工具接口。实际AgentArts运行画布需要后续截图佐证，目前图中链路是可编辑的流程设计。')

# P17 — explicit screenshot slot, diagram labels are a design explanation.
r=make_page(17,6,'p17_demo.svg','Demo：BIFB智能分析工作台','构建面向实验分析与优化决策的可交互智能工作台',status='工作台为界面设计方案；中央区域待替换真实Demo截图，不表示系统已部署或运行成功')
placeholder(r,17,'p17-demo-screen',65,184,823,362,'BIFB智能分析Demo界面截图','16:9',note='待可运行Demo完成后替换')
g=group(r,'p17-layout-labels',(916,184,297,362))
for i,(a,b) in enumerate([('左侧｜任务交互','Agent对话、任务输入、数据上传'),('中间｜视觉与统计','图像、分割、跟踪、尺寸/速度'),('右侧｜分析与决策','状态、优化、约束与解释'),('底部｜执行状态','Workflow进度、日志、完成状态')]):
    y=188+i*88
    text(g,916,y+22,a,22,RED,True)
    text(g,916,y+56,b,17)
g=group(r,'p17-example',(65,560,1148,62))
text(g,65,582,'示例：“分析这组图像，并判断当前工况是否需要调整通气量。”',21,RED,True)
text(g,65,612,'识别任务 → Bubble Vision → 气泡统计 → 知识检索 → 状态分析 → 参数优化 → 约束检查 → 报告',18)
save(r,'p17_demo.svg',17,'工作台设计将自然语言交互、实验视觉结果和优化决策放在同一界面，并展示底部Workflow进度与工具日志。用户只需提出分析目标，Agent组织视觉、知识、状态分析、优化和校验。此处界面为待实现方案，截图区域在Demo能够真实运行后替换。')

# P18 — evaluation protocol, never invented KPI values.
r=make_page(18,5,'p18_evaluation.svg','Agent效果评估','建立覆盖模型、工具、Workflow与决策质量的评价体系',status='评估状态：下列任务与指标均为计划评估；P5已有视觉模型指标不等于本页Agent评估结果')
g=group(r,'p18-metrics-table',(65,184,1148,292))
rect(g,65,184,1148,50,RED)
for x,lab in [(83,'评价维度'),(283,'指标'),(837,'证据/状态')]:text(g,x,218,lab,22,'#FFFFFF',True)
rows=[('视觉分析','Precision / Recall / mAP / MAE / RMSE','标注集与测量参考值'),('Agent任务','任务完成率 / 工具成功率 / 理解准确率','预设任务集与调用记录'),('Workflow','执行成功率 / 执行耗时 / 节点错误率','节点日志与耗时记录'),('决策质量','约束满足率 / 预测误差 / 结果一致性','实验参考值与可行性复核')]
for i,(a,b,c) in enumerate(rows):
    y=234+i*60
    rect(g,65,y,1148,60,TINT if i%2==0 else '#FFFFFF')
    text(g,83,y+36,a,22,RED,True);text(g,283,y+36,b,21)
    text(g,837,y+26,c,18);text(g,837,y+49,'计划评估',17,RED,True)
    line(g,65,y+60,1213,y+60,BORDER,1)
g=group(r,'p18-tests',(65,502,1148,112))
section(g,65,525,'测试任务设计',1148)
for i,(a,b) in enumerate([('T1 图像分析','验证分割、测量与统计'),('T2 缺参追问','验证输入检查与补全'),('T3 约束优化','验证可行性与依据输出')]):
    x=65+i*391
    text(g,x,570,a,22,RED,True);text(g,x,600,b,20)
save(r,'p18_evaluation.svg',18,'评估需要覆盖视觉模型、Agent任务、Workflow执行和决策质量四个层级。图像任务、缺参任务和约束优化任务分别检验专业计算、交互补全和决策依据。除前文已有视觉模型数据外，本页所有指标都标为计划评估，不能填入未经测试的完成率或运行耗时。')

# P19 — innovation plus future roadmap.
r=make_page(19,13,'slide_13.svg','项目创新与未来发展','面向多相流过程的专业智能体应用探索',status='创新定位为方案设计与应用探索；后续方向需要数据、工具接入和实验验证逐步支撑')
innov=[('领域Agent','以统一任务入口连接实验分析与运行优化'),('多源信息融合','联合图像、工况、领域知识与计算模型'),('智能任务编排','组织工具调用、Workflow执行与结果整合'),('可信决策','显式检查模型范围、约束和结果依据')]
g=group(r,'p19-innovation',(65,183,1148,223))
for i,(a,b) in enumerate(innov):
    x=65+(i%2)*590;y=184+(i//2)*108
    text(g,x,y+30,f'0{i+1}  {a}',27,RED,True);text(g,x,y+69,b,22)
g=group(r,'p19-future-title',(65,425,1148,45));section(g,65,450,'未来发展方向',1148)
flow(r,'p19-roadmap',65,483,1148,['多Agent协同','实验数据库','气含率/状态预测','在线动态决策','多相流迁移'],h=72,size=20)
g=group(r,'p19-development-note',(65,574,1148,35));text(g,65,599,'持续积累实验数据，完善预测与校验，再探索在线监测和动态决策。',22)
save(r,'slide_13.svg',19,'项目探索以领域Agent组织多相流实验分析，融合图像、工况、知识和计算模型。创新重点在任务编排与可信决策，使专业计算结果可以解释并接受校验。未来逐步积累实验数据库、完善气含率与状态预测，再探索多Agent协同、在线动态决策和领域迁移。')

# P20 — retain native ending artwork and replace text only/add sourced summary.
r=make_page(20,14,'slide_14.svg')
replace_shape(r,'shape-5',lambda g:text(g,1223,235,['让专业算法成为','可交互、可协作、','可决策的智能体'],43,'#FFFFFF',True,'end',58))
replace_shape(r,'shape-7',lambda g:text(g,1223,461,'感谢聆听，欢迎交流。',27,'#FFFFFF',True,'end'))
g=group(r,'p20-summary',(641,506,573,109))
text(g,1213,532,['基于AgentArts，整合气泡视觉、水动力计算、','知识检索与参数优化，形成可交互、可编排、','可解释的BIFB智能分析与决策系统。'],21,'#FFFFFF',anchor='end',leading=34)
save(r,'slide_14.svg',20,'项目以AgentArts为目标平台，整合气泡视觉、水动力计算、知识检索和参数优化，探索可交互、可编排、可解释的BIFB领域智能体。感谢聆听，欢迎就专业模型、实验验证与智能体实现展开交流。')

(ROOT/'page_plan.json').write_text(json.dumps({'schema':'ppt-master.roundtrip-page-plan.v1','pages':roster},ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'slide_content.json').write_text(json.dumps(page_text,ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'素材替换清单.json').write_text(json.dumps(placeholders,ensure_ascii=False,indent=2),encoding='utf-8')
with (ROOT/'素材替换清单.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(placeholders[0]));w.writeheader();w.writerows(placeholders)
lines=['# 素材替换清单','',f'共{len(placeholders)}处图片占位框；所有框均为可编辑PPT元素，未伪造图片、运行截图或实测图。','',
       '比例按素材内容建议；替换时可在既有框内等比裁切。建议像素尺寸为占位框约2倍，不代表原始数据分辨率要求。','',
       '| 页码 | 占位框名称 | 建议比例 | 建议像素 | 替换要求 |','|---|---|---|---|---|']
for p in placeholders:lines.append(f"| {p['page']} | {p['name']} | {p['ratio']} | {p['recommended_pixels']} | {p['replacement_note']} |")
lines += ['', '## 手动替换方式','',
          '在PowerPoint中插入真实图片，按本清单找到对应占位框。将图片等比缩放/裁切到框内，删除整个占位框组（含“图片占位符”和比例文字）。请保留页面标题、说明与真实性标注。',
          '', '## 需要补充素材的页面','', 'P2、P3、P5、P10、P11、P12、P13、P15、P16、P17。',
          '', '## 需要补充的信息','', 'P1参赛团队名称；如实际汇报人员、学校、指导老师或日期变更，请直接编辑封面。']
(ROOT/'素材替换清单.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

pending='''# 内容真实性与待实现事项

## 已有研究基础（引用用户材料）

- YOLO11-BUBBLE实例分割、气泡追踪、掩膜尺寸计算、质心轨迹速度计算与统计能力。
- mAP@0.5：0.970；Recall：0.941；参数量6.26M；GFLOPs 27.5；权重约13 MB。
- 上述数值未在本次PPT制作中重新测试，缺少测试集、划分和实验细节时不扩大其解释范围；不代表Agent整体效果。

## 仍属方案设计、待接入或待验证

- P6—P9：主控Agent、动态规划、分层架构与四类Skill集成。
- P10：Agent视觉调用端到端链路及真实统计素材；速度必须使用连续帧和时间标定。
- P11：多特征状态分析、三维气含率几何假设及参考实验校准。
- P12：AgentArts知识库配置、实际检索与答案依据核验。
- P13：水动力模型、OTR与气含率约束阈值、候选搜索和实验复核；离线决策支持，无在线闭环承诺。
- P14：输入、模型、决策三级校验机制的真实运行验证。
- P15—P16：AgentArts Agent、工具、Workflow、评估与部署的实际配置和运行证据。
- P17：可运行工作台及真实Demo截图。
- P18：任务完成率、工具成功率、理解准确率、Workflow耗时/成功率、节点错误率、决策质量与测量误差等计划评估。
- P19：多Agent、在线监测、动态决策与跨场景迁移均是未来方向；MCP仅在实际接入后展示。

## 图形与素材边界

架构、流程、Skill卡片、约束公式和评价表均为可编辑概念/方案图；它们不代表真实运行日志或实验结果。
所有实验图、模型结果图、分布图、平台截图、候选工况图和Demo截图均为明确图片占位框，详见素材替换清单。
'''
(ROOT/'待实现与真实性说明.md').write_text(pending,encoding='utf-8')
print(f'Authored {len(roster)} pages; {len(placeholders)} image slots; {len(page_text)} notes.')
