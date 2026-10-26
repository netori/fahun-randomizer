$ErrorActionPreference='Continue'
$pack='F:/game/studygame/elden ring/THE_COVERAGE-随机开发/法魂mod V3.0.3 汉化本体（适配游戏版本1.17.1）（新YAFSML引擎V0.10.4）'
$out='F:/game/studygame/elden ring/THE_COVERAGE-随机开发/随机mod\investigation\_tmp_shots3\frames_ve'
$live="$env:APPDATA\EldenRing\76561197960271872"
$cfg="$env:APPDATA\EldenRing\GraphicsConfig.xml"
if(Test-Path $cfg){
  $xml=Get-Content $cfg -Raw -Encoding Unicode
  if($xml -notmatch '<ScreenMode>WINDOWED</ScreenMode>'){
    $xml=$xml -replace '<ScreenMode>[A-Z]+</ScreenMode>','<ScreenMode>WINDOWED</ScreenMode>'
    [System.IO.File]::WriteAllText($cfg,$xml,[System.Text.Encoding]::Unicode)
  }
  Write-Output ('screenmode windowed')
}
Get-Process eldenring -ErrorAction SilentlyContinue | Where-Object { $_.StartTime -gt (Get-Date).AddMinutes(-40) } | ForEach-Object { Stop-Process -Id $_.Id -Force }
Start-Sleep -Seconds 2
$F=Join-Path $pack '存档库\敌人v1.5.0_二阶段携带_验证F'
Copy-Item (Join-Path $F 'ER0000.cnv') (Join-Path $live 'ER0000.cnv') -Force
Copy-Item (Join-Path $F 'ER0000.cnv.bak') (Join-Path $live 'ER0000.cnv.bak') -Force
Write-Output ('save: ' + (Get-FileHash (Join-Path $live 'ER0000.cnv') -Algorithm SHA1).Hash.Substring(0,16))
if(-not (Test-Path $out)){ New-Item -ItemType Directory -Path $out | Out-Null }
Get-ChildItem $out -Filter 'fr_*.jpg' -ErrorAction SilentlyContinue | Remove-Item -Force
Add-Type -AssemblyName System.Drawing
$sig=@"
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
[DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, System.UIntPtr dwExtraInfo);
"@
Add-Type -Namespace W -Name U -MemberDefinition $sig
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','启动法魂.bat' -WorkingDirectory $pack -WindowStyle Minimized | Out-Null
$sw=[System.Diagnostics.Stopwatch]::StartNew()
$i=0
$lastSave=(Get-Item (Join-Path $live 'ER0000.cnv')).LastWriteTime
$enc=[System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq 'image/jpeg' }
$enters=@(38,44,50,56)
$enterdone=@{}
while($sw.Elapsed.TotalSeconds -lt 135){
  $i++
  $b=New-Object System.Drawing.Bitmap 2560,1600
  $g=[System.Drawing.Graphics]::FromImage($b)
  try { $g.CopyFromScreen(0,0,0,0,$b.Size) } catch {}
  $g.Dispose()
  $sm=New-Object System.Drawing.Bitmap 960,600
  $g2=[System.Drawing.Graphics]::FromImage($sm)
  $g2.InterpolationMode=[System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g2.DrawImage($b,0,0,960,600)
  $g2.Dispose()
  $ep=New-Object System.Drawing.Imaging.EncoderParameters 1
  $ep.Param[0]=New-Object System.Drawing.Imaging.EncoderParameter ([System.Drawing.Imaging.Encoder]::Quality),60
  $sm.Save((Join-Path $out ('fr_{0:d3}.jpg' -f $i)),$enc,$ep)
  $sm.Dispose(); $b.Dispose()
  $t=[int]$sw.Elapsed.TotalSeconds
  foreach($et in $enters){
    if($t -ge $et -and -not $enterdone.ContainsKey($et)){
      $p=Get-Process eldenring -ErrorAction SilentlyContinue | Select-Object -First 1
      if($p){
        [void][W.U]::SetForegroundWindow($p.MainWindowHandle)
        Start-Sleep -Milliseconds 250
        [W.U]::keybd_event(0x0D,0,0,[System.UIntPtr]::Zero)
        [W.U]::keybd_event(0x0D,0,2,[System.UIntPtr]::Zero)
        Write-Output "enter@$t"
      }
      $enterdone[$et]=1
    }
  }
  $sn=(Get-Item (Join-Path $live 'ER0000.cnv')).LastWriteTime
  if($sn -ne $lastSave){ Write-Output ("t=" + $t + " SAVE"); $lastSave=$sn }
  Start-Sleep -Milliseconds 700
}
Write-Output ("frames " + $i)