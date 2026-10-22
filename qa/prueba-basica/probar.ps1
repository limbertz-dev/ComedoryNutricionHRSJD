param([switch]$SinClave)

# Un solo arranque. Configuración y guardas compartidas con el lanzador original.
& (Join-Path $PSScriptRoot 'iniciar-laboratorio.ps1') -SinClave:$SinClave -Completo
exit $LASTEXITCODE
