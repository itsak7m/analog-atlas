# Builds pitch\AnalogAtlas_CosmicCats.pptx from slides.json and bg\*.png, using the PowerPoint on this computer.
# Every word is an editable text box; speaker notes are added to each slide; pictures are the bg\*.png backgrounds.
# Run:  powershell -ExecutionPolicy Bypass -File pitch\deck\build_deck.ps1
# It also writes a PNG preview of each slide to pitch\deck\preview\.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$out = Join-Path (Split-Path -Parent $here) 'AnalogAtlas_CosmicCats.pptx'
$previewDir = Join-Path $here 'preview'
New-Item -ItemType Directory -Force $previewDir | Out-Null
$deck = Get-Content -Raw -Encoding UTF8 (Join-Path $here 'slides.json') | ConvertFrom-Json

function Rgb([string]$hex) { $h = $hex.TrimStart('#'); [Convert]::ToInt32($h.Substring(0, 2), 16) + 256 * [Convert]::ToInt32($h.Substring(2, 2), 16) + 65536 * [Convert]::ToInt32($h.Substring(4, 2), 16) }
function Opt($o, [string]$name, $default) { if ($o.PSObject.Properties[$name]) { $o.$name } else { $default } }
$AMBER = '#FFB547'; $CARD = '#0F1626'; $EDGE = '#2A3550'

function Add-Text($slide, $it) {
  $tb = $slide.Shapes.AddTextbox(1, $it.x, $it.y, $it.w, $it.h)
  $tf = $tb.TextFrame
  $tf.AutoSize = 0; $tf.WordWrap = -1
  $tf.MarginLeft = 0; $tf.MarginRight = 0; $tf.MarginTop = 0; $tf.MarginBottom = 0
  $tf.VerticalAnchor = @{ t = 1; m = 3; b = 4 }[(Opt $it 'valign' 't')]
  $tr = $tf.TextRange
  $tr.Text = ($it.text -replace "`r?`n", "`r")
  $tr.Font.Name = (Opt $it 'font' 'Segoe UI')
  $tr.Font.Size = [single]$it.size
  $tr.Font.Bold = $(if (Opt $it 'bold' $false) { -1 } else { 0 })
  $tr.Font.Color.RGB = Rgb (Opt $it 'color' '#F6F8FC')
  $tr.ParagraphFormat.Alignment = @{ l = 1; c = 2; r = 3 }[(Opt $it 'align' 'l')]
  $sp = Opt $it 'spacing' 0
  if ($sp -ne 0) { $tb.TextFrame2.TextRange.Font.Spacing = [single]$sp }
  $after = Opt $it 'spaceAfter' 0
  if ($after -gt 0) { $tr.ParagraphFormat.LineRuleAfter = 0; $tr.ParagraphFormat.SpaceAfter = [single]$after }
  if ((Opt $it 'bullets' $false) -or (Opt $it 'numbered' $false)) {
    $b = $tr.ParagraphFormat.Bullet
    $b.Visible = -1
    if (Opt $it 'numbered' $false) { $b.Type = 2; $b.Style = 3 } else { $b.Type = 1; $b.Character = 8226 }
    $b.Font.Color.RGB = Rgb $AMBER
    $tf.Ruler.Levels(1).FirstMargin = 0; $tf.Ruler.Levels(1).LeftMargin = 18
  }
  $tb
}
function Add-Rect($slide, $x, $y, $w, $h, $fill, $transparency, $line, $radius) {
  $shape = $(if ($radius -gt 0) { 5 } else { 1 })
  $r = $slide.Shapes.AddShape($shape, $x, $y, $w, $h)
  if ($radius -gt 0) { $r.Adjustments.Item(1) = [single]$radius }
  $r.Fill.Solid(); $r.Fill.ForeColor.RGB = Rgb $fill; $r.Fill.Transparency = [single]$transparency
  if ($line) { $r.Line.Visible = -1; $r.Line.ForeColor.RGB = Rgb $line; $r.Line.Weight = 0.75 } else { $r.Line.Visible = 0 }
  $r.Shadow.Visible = 0
  $r
}
function T($x, $y, $w, $h, $text, $size, $color, $extra = @{}) {
  $o = [pscustomobject]@{ x = $x; y = $y; w = $w; h = $h; text = $text; size = $size; color = $color }
  foreach ($k in $extra.Keys) { $o | Add-Member -NotePropertyName $k -NotePropertyValue $extra[$k] }
  $o
}

$wasOpen = [bool](Get-Process POWERPNT -ErrorAction SilentlyContinue)  # never close a PowerPoint the user has open
$app = New-Object -ComObject PowerPoint.Application
try {
  $pres = $app.Presentations.Add(0)
  $pres.PageSetup.SlideWidth = 960; $pres.PageSetup.SlideHeight = 540
  $n = $deck.slides.Count
  for ($i = 0; $i -lt $n; $i++) {
    $sd = $deck.slides[$i]
    $slide = $pres.Slides.Add($i + 1, 12)
    $slide.FollowMasterBackground = 0
    $slide.Background.Fill.Solid(); $slide.Background.Fill.ForeColor.RGB = Rgb '#070A12'
    $pic = $slide.Shapes.AddPicture((Join-Path $here ('bg\' + $sd.bg)), 0, -1, 0, 0, 960, 540)
    $pic.Name = 'Background'
    foreach ($it in $sd.items) {
      switch ($it.type) {
        'text' { Add-Text $slide $it | Out-Null }
        'rect' { Add-Rect $slide $it.x $it.y $it.w $it.h $it.fill (Opt $it 'transparency' 0) (Opt $it 'line' $null) (Opt $it 'radius' 0) | Out-Null }
        'card' {
          Add-Rect $slide $it.x $it.y $it.w $it.h $CARD 0.08 $EDGE 0.06 | Out-Null
          Add-Rect $slide ($it.x + 14) ($it.y + 14) 26 3 $AMBER 0 $null 0 | Out-Null
          Add-Text $slide (T ($it.x + 14) ($it.y + 24) ($it.w - 28) 16 $it.num 11 $AMBER @{ font = 'Segoe UI Semibold'; spacing = 2 }) | Out-Null
          Add-Text $slide (T ($it.x + 14) ($it.y + 42) ($it.w - 28) 26 $it.title 19 '#F6F8FC' @{ bold = $true }) | Out-Null
          Add-Text $slide (T ($it.x + 14) ($it.y + 76) ($it.w - 28) 100 $it.body 11.5 '#C9D1E0') | Out-Null
          Add-Text $slide (T ($it.x + 14) ($it.y + $it.h - 60) ($it.w - 28) 46 $it.source 8.5 '#9AA6BD' @{ valign = 'b' }) | Out-Null
        }
        'row' {
          Add-Rect $slide 60 $it.y 450 46 $CARD 0.1 $EDGE 0.12 | Out-Null
          Add-Text $slide (T 74 ($it.y + 6) 300 13 $it.tag 8.5 $AMBER @{ font = 'Segoe UI Semibold'; spacing = 1.2 }) | Out-Null
          Add-Text $slide (T 74 ($it.y + 20) 300 22 $it.site 14 '#F6F8FC' @{ bold = $true }) | Out-Null
          Add-Text $slide (T 370 $it.y 126 46 $it.pct 18 $AMBER @{ bold = $true; align = 'r'; valign = 'm' }) | Out-Null
        }
      }
    }
    if ($i -gt 0) { Add-Text $slide (T 820 22 110 12 ('{0:D2} / {1:D2}' -f ($i + 1), $n) 8 '#5C6780' @{ align = 'r'; spacing = 1 }) | Out-Null }
    # Space Apps 2026 rule: SI-generated images carry a visible mark (the backgrounds and drawings were made by code written with Claude).
    Add-Text $slide (T 20 8 400 11 'SI-assisted: backgrounds and drawings made with Claude (Anthropic)' 7.5 '#7A859C') | Out-Null
    $slide.NotesPage.Shapes.Placeholders(2).TextFrame.TextRange.Text = ($sd.notes -replace "`r?`n", "`r")
    $slide.Export((Join-Path $previewDir ('slide{0}.png' -f ($i + 1))), 'PNG', 1920, 1080)
  }
  $pres.SaveAs($out, 24)
  $pres.Close()
  "Saved $out ($n slides)"
} finally {
  if (-not $wasOpen) { $app.Quit() }
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null
}
