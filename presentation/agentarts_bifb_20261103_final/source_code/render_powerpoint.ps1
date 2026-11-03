param(
    [Parameter(Mandatory=$true)][string]$PresentationPath,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$resolvedPresentation = (Resolve-Path -LiteralPath $PresentationPath).Path
$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$resolvedOutput = (Resolve-Path -LiteralPath $OutputDirectory).Path
$app = $null
$presentation = $null
$oldAlerts = $null
try {
    $app = New-Object -ComObject PowerPoint.Application
    $oldAlerts = $app.DisplayAlerts
    $app.DisplayAlerts = 1
    # ReadOnly=true, Untitled=false, WithWindow=false. Preserve user's open decks.
    $presentation = $app.Presentations.Open($resolvedPresentation, -1, 0, 0)
    $rows = @()
    for ($i = 1; $i -le $presentation.Slides.Count; $i++) {
        $slide = $presentation.Slides.Item($i)
        $imagePath = Join-Path $resolvedOutput ('P{0:D2}.png' -f $i)
        $slide.Export($imagePath, 'PNG', 1600, 900)
        $rows += [pscustomobject]@{ page=$i; png=$imagePath; shapeCount=$slide.Shapes.Count }
    }
    $report = [pscustomobject]@{
        presentation=$resolvedPresentation
        renderer='Microsoft PowerPoint native export'
        slides=$presentation.Slides.Count
        width=[double]$presentation.PageSetup.SlideWidth
        height=[double]$presentation.PageSetup.SlideHeight
        renderedPages=$rows
    }
    $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $resolvedOutput 'render_report.json') -Encoding utf8
    Write-Output ('Rendered {0} slides to {1}' -f $presentation.Slides.Count, $resolvedOutput)
}
finally {
    if ($null -ne $presentation) { $presentation.Close() }
    if ($null -ne $app) {
        if ($null -ne $oldAlerts) { $app.DisplayAlerts = $oldAlerts }
        if ($app.Presentations.Count -eq 0) { $app.Quit() }
        $null = [Runtime.InteropServices.Marshal]::ReleaseComObject($app)
    }
}
