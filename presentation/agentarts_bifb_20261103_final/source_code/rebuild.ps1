param(
    [string]$SkillDirectory = 'C:\Users\AHin0\.codex\skills\ppt-master',
    [string]$PythonExecutable = 'C:\Users\AHin0\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
)
$ErrorActionPreference = 'Stop'
$projectDirectory = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
function Invoke-PythonChecked([string[]]$Arguments) {
    & $PythonExecutable @Arguments
    if ($LASTEXITCODE -ne 0) { throw ('Python step failed with exit code {0}' -f $LASTEXITCODE) }
}
Invoke-PythonChecked @((Join-Path $PSScriptRoot 'build_deck.py'))
Invoke-PythonChecked @((Join-Path $SkillDirectory 'scripts\svg_authoring_view.py'),(Join-Path $projectDirectory 'authoring-svg-flat'),'--refresh-summary')
Invoke-PythonChecked @((Join-Path $SkillDirectory 'scripts\svg_quality_checker.py'),$projectDirectory,'--roundtrip','--json')
Invoke-PythonChecked @((Join-Path $SkillDirectory 'scripts\svg_to_pptx.py'),$projectDirectory,'--roundtrip','--primary-language','zh-CN','-o',(Join-Path $projectDirectory 'exports\AgentArts_BIFB_竞赛汇报_20页.pptx'))
