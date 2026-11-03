# AgentArts × BIFB 20页中文竞赛汇报

本项目基于用户提供的《华为大赛汇报2.pptx》制作，采用已确认的20页内容映射。桌面原文件未修改。

## 主要文件

- `exports/AgentArts_BIFB_竞赛汇报_20页.pptx`：最终可编辑PowerPoint。
- `素材替换清单.md`、`.csv`、`.json`：22处素材占位框的页码、名称、比例和建议尺寸。
- `待实现与真实性说明.md`：已有视觉研究基础与计划实现/评估项目的边界。
- `source_code/build_deck.py`：完整20页文案、可编辑图形、占位框、讲者备注和清单生成逻辑。
- `source_code/template_svgs/`：制作前模板的可编辑页面快照；重复执行制作脚本以此为基准。
- `authoring-svg-flat/`：最终20页的可编辑SVG源文件。
- `notes/`：每页中文讲者备注。
- `page_plan.json`：输出顺序与原模板骨架映射。
- `sources/original_template.pptx`：原始模板副本；`sources/source.pptx`为清理旧嵌入式公式后的导入副本。
- `analysis/`、`native-payloads/`：PPT Master原生往返导入生成的数据，保留以便再导出，不要手工改动。
- `validation/powerpoint-preview/`：Microsoft PowerPoint对最终文件逐页导出的1600×900 PNG与总览图。

## 重新生成

依赖PPT Master 6.8.0及其Python依赖；本包包含此次制作的全部源文件与项目代码，不重复打包第三方Skill软件包。页面编写脚本本身仅用Python标准库；导出依赖PPT Master（包含python-pptx）。

在Windows PowerShell中运行：

```powershell
.\source_code\rebuild.ps1
```

如果本机路径不同，传入对应的`-SkillDirectory`与`-PythonExecutable`。脚本先按源文案重写SVG，再运行容量检查和原生往返导出。若已手动修改SVG而希望保留改动，应跳过`build_deck.py`，直接运行检查与导出步骤。

需要从原始模板重新导入时：先用`source_code/prepare_template.py <原始PPTX> <新工作副本PPTX>`，再用PPT Master的`pptx_to_svg.py --inheritance-mode both --roundtrip`导入到一个新目录。工作副本只移除将被替换的旧OLE公式及其幻灯片关联，未改母版、版式、主题或原始文件；准备记录见`validation/template_preparation.json`。

## 实际排版验证

```powershell
.\source_code\render_powerpoint.ps1 -PresentationPath .\exports\AgentArts_BIFB_竞赛汇报_20页.pptx -OutputDirectory .\validation\powerpoint-preview
```

需要安装Microsoft PowerPoint。脚本以只读、无文档窗口方式打开成品并导出逐页PNG，保留用户已打开的其他演示文稿。

## 模板与字体

母版、布局、主题、校徽、封面、结尾曲线及页眉页脚保留原模板。新增文字采用源主题的“等线”，代码中使用其同字体英文名称`DengXian`，使导出器正确识别中文字体，而不自动替换为其他字体。源母版中原有的思源、优设等字体声明保持原样；最终排版通过本机PowerPoint实际渲染核验。

## 使用前补充

P1参赛团队名称仍为“待补充”。真实实验图、视觉结果图、平台截图、分布图、候选工况图与Demo截图均需按清单替换。已有视觉指标按用户材料引用，非本次复测；AgentArts集成、Workflow执行、优化与Agent评估未提供真实运行证据，均以设计/计划/待验证形式呈现。

第三方工具：PPT Master，Copyright (c) 2025–2026 Hugo He，MIT License。官方项目：https://github.com/hugohe3/ppt-master
