<#
  Laboratorio QA en un solo comando.

    .\qa\laboratorio\iniciar.ps1              base real de desarrollo (bd_nutricion)
    .\qa\laboratorio\iniciar.ps1 -Base sim    base sintetica (bd_nutricion_escenario_sim)

  Abre dos ventanas (API + laboratorio, y front) y luego la app en el
  navegador. El laboratorio se abre con el boton "Laboratorio QA" de la app.
  Para detener: cerrar las dos ventanas. Si MySQL tiene contrasena, definir
  antes $env:DB_PASSWORD en esta consola.
#>
param(
    [ValidateSet('real', 'sim')][string]$Base = 'real',
    [int]$Puerto = 8000
)

$ErrorActionPreference = 'Stop'
$raiz = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$python = Join-Path $raiz 'comedorback\.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) { throw "Falta el entorno de Python: $python" }

# Libera los puertos solo si los ocupa un proceso de este worktree (un
# laboratorio o front anterior). Otro programa se informa y no se toca.
foreach ($p in @($Puerto, 8001, 8002, 5173)) {
    $conexiones = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue
    foreach ($id in ($conexiones.OwningProcess | Sort-Object -Unique)) {
        $linea = [string](Get-CimInstance Win32_Process -Filter "ProcessId=$id").CommandLine
        if ($linea.Contains($raiz) -or $linea -match 'scripts[\\/]iniciar-qa\.mjs') {
            Write-Host "  Cerrando proceso anterior en el puerto $p (pid $id)"
            Stop-Process -Id $id -Force
        } elseif ($p -eq $Puerto -or $p -eq 5173) {
            throw "El puerto $p lo usa otro programa (pid $id): $linea"
        }
    }
}
$marca = Join-Path $raiz 'qa\prueba-basica\api.activa'
if (Test-Path -LiteralPath $marca) { Remove-Item -LiteralPath $marca -Force }

# Cada parte en su propia ventana: siguen vivas aunque se cierre esta consola,
# y si algo falla el error queda a la vista.
$api = "`$host.UI.RawUI.WindowTitle = 'Laboratorio QA - API'; Set-Location -LiteralPath '$raiz'; & '$python' -B qa\laboratorio\lab.py --base $Base --port $Puerto"
$web = "`$host.UI.RawUI.WindowTitle = 'Laboratorio QA - Front'; Set-Location -LiteralPath '$raiz'; node qa\laboratorio\front.mjs $Puerto"
Start-Process powershell -ArgumentList '-NoExit', '-NoProfile', '-Command', $api | Out-Null
Start-Process powershell -ArgumentList '-NoExit', '-NoProfile', '-Command', $web -WindowStyle Minimized | Out-Null

Write-Host '  Esperando a la API y al front...'
$limite = (Get-Date).AddSeconds(60)
$listo = $false
while ((Get-Date) -lt $limite -and -not $listo) {
    Start-Sleep -Milliseconds 700
    try {
        $null = Invoke-WebRequest "http://127.0.0.1:$Puerto/salud" -UseBasicParsing -TimeoutSec 2
        $null = Invoke-WebRequest 'http://localhost:5173' -UseBasicParsing -TimeoutSec 2
        $listo = $true
    } catch { }
}
if (-not $listo) { throw 'No arrancaron en 60 segundos: revisa las ventanas "Laboratorio QA - API" y "Laboratorio QA - Front".' }

Start-Process 'http://localhost:5173'
Write-Host ''
Write-Host '  Listo. App: http://localhost:5173  ->  boton "Laboratorio QA" (abajo a la izquierda) o Ctrl+Shift+L'
