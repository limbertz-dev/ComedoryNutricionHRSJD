@echo off
title Automatizacion de Casos con Playwright - Comedor Hospitalario
echo ==============================================================
echo INICIANDO AUTOMATIZACION EN MODO VISIBLE CON PLAYWRIGHT
echo Observa tu pantalla: el navegador se abrira y realizara el flujo.
echo ==============================================================
node "%~dp0flujo_automatizacion_playwright.cjs" --visible
pause
