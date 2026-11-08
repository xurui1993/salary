$ErrorActionPreference='Stop'
[Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]|Out-Null
  [Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime]|Out-Null
  [Windows.Storage.Streams.InMemoryRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime]|Out-Null
  [Windows.Storage.Streams.DataWriter,Windows.Storage.Streams,ContentType=WindowsRuntime]|Out-Null
  [Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime]|Out-Null
  [Windows.Graphics.Imaging.SoftwareBitmap,Windows.Foundation,ContentType=WindowsRuntime]|Out-Null
  $request=[Console]::In.ReadToEnd()|ConvertFrom-Json
  $engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language('en-US')))
  if(-not $engine){$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()}
  if(-not $engine){throw 'OCR unavailable'}
  if($request.probe){@{available=$true}|ConvertTo-Json -Compress;exit 0}
  $bytes=[Convert]::FromBase64String($request.image)
  if($bytes.Length -gt 262144){throw 'Image too large'}
  $asTask=[System.WindowsRuntimeSystemExtensions].GetMethods()|Where-Object {$_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'}|Select-Object -First 1
  function Await-Operation($operation,$type){$task=$asTask.MakeGenericMethod($type).Invoke($null,@($operation));if(-not $task.Wait(4000)){throw 'OCR timeout'};return $task.Result}
  $stream=New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
  $writer=New-Object Windows.Storage.Streams.DataWriter($stream)
  $writer.WriteBytes($bytes)
  Await-Operation $writer.StoreAsync() ([uint32])|Out-Null
  $writer.DetachStream()|Out-Null
  $stream.Seek(0)
  $decoder=Await-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  if($decoder.PixelWidth -gt 1600 -or $decoder.PixelHeight -gt 800){throw 'Captcha dimensions too large'}
  $texts=@()
  foreach($scale in @(1,3)){
    $transform=New-Object Windows.Graphics.Imaging.BitmapTransform
    $transform.ScaledWidth=[uint32]($decoder.PixelWidth*$scale)
    $transform.ScaledHeight=[uint32]($decoder.PixelHeight*$scale)
    $bitmap=Await-Operation ($decoder.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,[Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied,$transform,[Windows.Graphics.Imaging.ExifOrientationMode]::IgnoreExifOrientation,[Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage)) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result=Await-Operation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $texts+=$result.Text
    $bitmap.Dispose()
  }
  $stream.Dispose()
  @{available=$true;texts=$texts}|ConvertTo-Json -Compress
} catch {
  @{available=$false;texts=@()}|ConvertTo-Json -Compress
  exit 0
}
