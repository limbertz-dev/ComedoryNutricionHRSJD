@echo off
title Automatizacion 4 Comidas y Casos Pendientes - Playwright
echo =========================================================================
echo INICIANDO CICLO COMPLETO: DESAYUNO - ALMUERZO - TE - CENA (MODO VISIBLE)
echo =========================================================================
node "%~dp0flujo_completo_4comidas_playwright.cjs" --visible
pause
