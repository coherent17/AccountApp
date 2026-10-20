param([string]$textFile, [string]$out)
Add-Type -AssemblyName System.Speech
$text = Get-Content -Raw -Encoding UTF8 $textFile
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
try { $s.SelectVoice('Microsoft Hanhan Desktop') } catch {}
$s.Rate = 0
$s.Volume = 100
$s.SetOutputToWaveFile($out)
$s.Speak($text)
$s.Dispose()
