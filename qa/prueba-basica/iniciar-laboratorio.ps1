param([switch]$SinClave, [switch]$Completo)

$ErrorActionPreference = 'Stop'
$qaRaiz = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$qaPython = Join-Path $qaRaiz 'comedorback/.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $qaPython)) { throw 'Falta el entorno Python propio de wt-qa.' }

foreach ($qaPar in @(
    @('ENTORNO', 'desarrollo'),
    @('DB_NAME', 'bd_nutricion_escenario_sim'),
    @('DB_NAME_TURNOS', 'bd_turnos_escenario_demo')
)) {
    $qaValor = [Environment]::GetEnvironmentVariable($qaPar[0], 'Process')
    if ($qaValor -and $qaValor -ne $qaPar[1]) { throw "Configuración fuera de QA: $($qaPar[0])." }
    [Environment]::SetEnvironmentVariable($qaPar[0], $qaPar[1], 'Process')
}
if (!$env:DB_HOST) { $env:DB_HOST = '127.0.0.1' }
if (!$env:DB_PORT) { $env:DB_PORT = '3306' }
if (!$env:DB_USER) { $env:DB_USER = 'root' }
if ($SinClave) {
    if ($env:DB_PASSWORD) { throw 'DB_PASSWORD está definida: no se combina con -SinClave.' }
    $env:QA_DB_SIN_CLAVE = '1'
}
if (!$env:DB_PASSWORD -and $env:QA_DB_SIN_CLAVE -ne '1') {
    throw 'Configura la contraseña MySQL en la sesión o usa -SinClave para el Laragon local sin contraseña.'
}
Set-Location -LiteralPath $qaRaiz
$qaEntrada = if ($Completo) { 'arrancar_qa.py' } else { 'laboratorio.py' }
& $qaPython -B (Join-Path $PSScriptRoot $qaEntrada)
exit $LASTEXITCODE
